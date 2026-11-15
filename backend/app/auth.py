"""登录、注册、重置密码、会话与管理员用户管理。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from . import db
from .agents import llm
from .models import (AdminUserUpdate, BindCodeRequest, BindRequest, LoginRequest,
                     RegisterRequest, ResetRequest, SendCodeRequest)
from .services import accounts, central, mailer

SESSION_COOKIE = "nudge_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE, "")
    user = accounts.session_user(token)
    if not user:
        raise HTTPException(401, "请先登录")
    db.touch_last_seen(user["id"])
    central.touch_presence(user)
    return user


def require_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(403, "需要管理员权限")
    return user


def _set_session(response: Response, user_id: str) -> None:
    token = accounts.create_session(user_id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=accounts.SESSION_DAYS * 24 * 3600,
        path="/",
    )


def _mirror_central(data: dict, token: str) -> dict[str, Any]:
    central_user = (data or {}).get("user") or {}
    central_id = str(central_user.get("id") or "")
    if not central_id:
        raise HTTPException(502, "共享账号中心返回缺少用户 id")
    user = db.upsert_central_user(
        central_id, central_user.get("name", ""), central_user.get("email", ""),
        bool(central_user.get("is_admin")),
    )
    central.save_session(user["id"], token)
    return accounts.public_user(user) or {}


def _central_failure(error: central.CentralError) -> None:
    status = error.status if 400 <= error.status <= 599 else 502
    raise HTTPException(status, str(error))


@router.post("/login")
def api_login(body: LoginRequest, response: Response) -> dict[str, Any]:
    if central.enabled():
        try:
            data, token = central.login(body.email, body.password)
        except central.CentralError as error:
            if error.status == 401 and accounts.login(body.email, body.password):
                try:
                    sent = central.send_code(body.email, "register")
                except central.CentralError as send_error:
                    if send_error.status == 400:
                        raise HTTPException(409, "该邮箱已有共享账号，请使用共享密码登录") from send_error
                    _central_failure(send_error)
                return {
                    "bind_required": True,
                    "email": body.email,
                    "dev": sent.get("dev", False),
                    "dev_code": sent.get("dev_code", ""),
                    "notice": sent.get("notice", ""),
                }
            _central_failure(error)
        user = _mirror_central(data, token)
        _set_session(response, user["id"])
        return {"user": user}
    user = accounts.login(body.email, body.password)
    if not user:
        raise HTTPException(401, "邮箱或密码错误")
    _set_session(response, user["id"])
    return {"user": user}


@router.post("/register")
def api_register(body: RegisterRequest, response: Response) -> dict[str, Any]:
    if central.enabled():
        try:
            data, token = central.register(body.nickname, body.email, body.password,
                                           body.confirm, body.code)
        except central.CentralError as error:
            _central_failure(error)
        user = _mirror_central(data, token)
        _set_session(response, user["id"])
        return {"user": user}
    try:
        user = accounts.register(body.nickname, body.email, body.password, body.confirm, body.code)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    _set_session(response, user["id"])
    return {"user": user}


@router.post("/bind-code")
def api_bind_code(body: BindCodeRequest) -> dict[str, Any]:
    if not central.enabled() or not accounts.login(body.email, body.password):
        raise HTTPException(401, "原邮箱或密码错误")
    try:
        sent = central.send_code(body.email, "register")
    except central.CentralError as error:
        if error.status == 400:
            raise HTTPException(409, "该邮箱已有共享账号，请使用共享密码登录") from error
        _central_failure(error)
    return {
        "ok": True, "dev": sent.get("dev", False),
        "dev_code": sent.get("dev_code", ""), "notice": sent.get("notice", ""),
    }


@router.post("/bind")
def api_bind(body: BindRequest, response: Response) -> dict[str, Any]:
    local_user = accounts.login(body.email, body.password)
    if not local_user:
        raise HTTPException(401, "原邮箱或密码错误")
    if not central.enabled():
        raise HTTPException(400, "未配置共享账号服务")
    try:
        data, token = central.register(
            local_user.get("name") or "Nudge 用户", body.email, body.password,
            body.password, body.code,
        )
    except central.CentralError as error:
        _central_failure(error)
    user = _mirror_central(data, token)
    _set_session(response, user["id"])
    return {"user": user}


@router.post("/reset")
def api_reset(body: ResetRequest) -> dict[str, Any]:
    if central.enabled():
        try:
            central.reset(body.email, body.code, body.password, body.confirm)
        except central.CentralError as error:
            _central_failure(error)
        return {"ok": True}
    try:
        accounts.reset_password(body.email, body.code, body.password, body.confirm)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"ok": True}


@router.post("/send-code")
def api_send_code(body: SendCodeRequest) -> dict[str, Any]:
    if central.enabled():
        try:
            result = central.send_code(body.email, body.purpose)
        except central.CentralError as error:
            _central_failure(error)
        return result
    try:
        result = accounts.issue_code(body.email, body.purpose)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except mailer.MailError as error:
        raise HTTPException(503, str(error)) from error
    return {
        "ok": True,
        "dev": result["dev"],
        "dev_code": result["code"] if result["dev"] else "",
        "expires_in": result["expires_in"],
        "notice": (
            "开发模式：未真实发信，验证码只显示在本页和服务端日志"
            if result["dev"] else ""
        ),
    }


@router.get("/mail-status")
def api_mail_status() -> dict[str, Any]:
    """前端用来诚实展示「真发信 / 开发模式 / 未授权」，不暴露令牌。"""
    return mailer.status()


@router.post("/logout")
def api_logout(request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE, "")
    local_user = accounts.session_user(token)
    if central.enabled() and local_user:
        central.logout(central.session_token(local_user["id"]))
        central.clear_session(local_user["id"])
    accounts.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def api_me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user": user}


@router.post("/demo")
def api_demo(response: Response) -> dict[str, Any]:
    if central.enabled():
        try:
            data, token = central.demo()
        except central.CentralError as error:
            _central_failure(error)
        user = _mirror_central(data, token)
        _set_session(response, user["id"])
        return {"user": user}
    user = accounts.demo_user()
    if not user:
        raise HTTPException(404, "演示账号不存在")
    _set_session(response, user["id"])
    return {"user": user}


@admin_router.get("/users")
def api_admin_users(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return {"users": db.list_users()}


@admin_router.get("/global-users")
def api_admin_global_users(admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """本地管理端拉取中心全部账号和各实例状态；账号只读，事件仍本地。"""
    if not central.enabled():
        return {"central": False, "users": [], "presence": []}
    token = central.session_token(admin["id"])
    if not token:
        raise HTTPException(403, "请退出后重新登录，以取得共享账号中心会话")
    try:
        data = central.admin_users(token)
    except central.CentralError as error:
        _central_failure(error)
    return {"central": True, **data}


def _admin_detail(user_id: str) -> dict[str, Any]:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    base, model, key = llm.current(user_id)
    listed = next((item for item in db.list_users() if item["id"] == user_id), {})
    public = accounts.public_user(user) or {}
    public.update({
        "online": listed.get("online", False),
        "status": listed.get("status", "未活跃"),
        "status_key": listed.get("status_key", "idle"),
        "event_count": listed.get("event_count", 0),
        "has_saved_key": listed.get("has_key", False),
    })
    return {
        "user": public,
        "model": {"base_url": base, "model": model, "has_key": bool(key),
                  "mode": llm.mode(user_id) or "auto"},
        "events": db.list_events(user_id),
    }


@admin_router.get("/users/detail")
def api_admin_users_detail(ids: str = Query(""),
                           _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """一次看多个用户的事件与模型配置，方便管理端并排对比。"""
    wanted = [item.strip() for item in ids.split(",") if item.strip()][:6]
    if not wanted:
        raise HTTPException(400, "请至少选择一个用户")
    return {"users": [_admin_detail(user_id) for user_id in wanted if db.get_user(user_id)]}


@admin_router.get("/users/{user_id}/detail")
def api_admin_user_detail(user_id: str, _: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """管理员看某个用户的事件与模型配置；只返回是否有 Key，不返回 Key。"""
    return _admin_detail(user_id)


@admin_router.patch("/users/{user_id}")
def api_admin_update_user(user_id: str, body: AdminUserUpdate,
                          admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """管理员直接改邮箱/昵称/密码，不需要邮箱验证码。"""
    target = db.get_user(user_id)
    if not target:
        raise HTTPException(404, "用户不存在")
    if central.enabled() and target.get("central_id"):
        token = central.session_token(admin["id"])
        if not token:
            raise HTTPException(403, "请退出后重新登录，以取得共享账号中心会话")
        try:
            result = central.admin_update(token, target["central_id"], {
                "name": (body.name or "").strip(),
                "email": (body.email or "").strip(),
                "password": body.password or "",
            })
        except central.CentralError as error:
            _central_failure(error)
        central_user = (result or {}).get("user") or {}
        if central_user.get("id"):
            db.upsert_central_user(
                central_user["id"], central_user.get("name", ""), central_user.get("email", ""),
                bool(central_user.get("is_admin")),
            )
        detail = _admin_detail(user_id)
        return {"ok": True, "user": detail["user"]}
    name = (body.name or "").strip()
    email = (body.email or "").strip()
    password = body.password or ""
    if name:
        if not 1 <= len(name) <= 20:
            raise HTTPException(400, "昵称长度需要 1–20 个字")
        db.update_name(user_id, name)
    if email:
        try:
            email = accounts.validate_email(email)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        existing = db.get_user_by_email(email)
        if existing and existing["id"] != user_id:
            raise HTTPException(400, "该邮箱已被其他用户使用")
        db.update_email(user_id, email)
    if password:
        if len(password) < 8:
            raise HTTPException(400, "密码至少 8 位")
        db.update_password_by_id(user_id, accounts.hash_password(password))
        if user_id != admin["id"]:
            db.delete_user_sessions(user_id)
    detail = _admin_detail(user_id)
    return {"ok": True, "user": detail["user"]}


@admin_router.delete("/users/{user_id}")
def api_admin_delete_user(user_id: str, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    if user_id in ("u_admin", "u_demo"):
        raise HTTPException(400, "内置账号不能删除")
    if user_id == admin["id"]:
        raise HTTPException(400, "不能删除自己")
    if not db.delete_user(user_id):
        raise HTTPException(404, "用户不存在")
    return {"ok": True}