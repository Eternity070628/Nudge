"""登录、注册、重置密码、会话与管理员用户管理。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from . import db
from .models import LoginRequest, RegisterRequest, ResetRequest, SendCodeRequest
from .services import accounts, mailer

SESSION_COOKIE = "nudge_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE, "")
    user = accounts.session_user(token)
    if not user:
        raise HTTPException(401, "请先登录")
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


@router.post("/login")
def api_login(body: LoginRequest, response: Response) -> dict[str, Any]:
    user = accounts.login(body.email, body.password)
    if not user:
        raise HTTPException(401, "邮箱或密码错误")
    _set_session(response, user["id"])
    return {"user": user}


@router.post("/register")
def api_register(body: RegisterRequest, response: Response) -> dict[str, Any]:
    try:
        user = accounts.register(body.nickname, body.email, body.password, body.confirm, body.code)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    _set_session(response, user["id"])
    return {"user": user}


@router.post("/reset")
def api_reset(body: ResetRequest) -> dict[str, Any]:
    try:
        accounts.reset_password(body.email, body.code, body.password, body.confirm)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return {"ok": True}


@router.post("/send-code")
def api_send_code(body: SendCodeRequest) -> dict[str, Any]:
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
    accounts.logout(request.cookies.get(SESSION_COOKIE, ""))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def api_me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user": user}


@router.post("/demo")
def api_demo(response: Response) -> dict[str, Any]:
    user = accounts.demo_user()
    if not user:
        raise HTTPException(404, "演示账号不存在")
    _set_session(response, user["id"])
    return {"user": user}


@admin_router.get("/users")
def api_admin_users(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return {"users": db.list_users()}


@admin_router.delete("/users/{user_id}")
def api_admin_delete_user(user_id: str, admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    if user_id in ("u_admin", "u_demo"):
        raise HTTPException(400, "内置账号不能删除")
    if user_id == admin["id"]:
        raise HTTPException(400, "不能删除自己")
    if not db.delete_user(user_id):
        raise HTTPException(404, "用户不存在")
    return {"ok": True}