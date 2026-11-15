"""共享账号中心客户端（方案 A：PythonAnywhere 实例）。

本地安装版把注册/登录/验证码/密码修改代理给中心；本地只保存用户镜像、
事件和中心会话 token。中心不可达时明确报错，不伪造成功。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import config, db


class CentralError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


def configure() -> None:
    """中心 URL 可由管理端保存到本机库；没有配置时保持单机模式。"""
    saved = db.get_settings()
    if "nudge_central_url" in saved:
        config.NUDGE_CENTRAL_URL = (saved.get("nudge_central_url") or "").strip().rstrip("/")


def url() -> str:
    return (config.NUDGE_CENTRAL_URL or "").strip().rstrip("/")


def enabled() -> bool:
    return bool(url())


def _request(path: str, method: str = "POST", payload=None, token: str = ""):
    base = url()
    if not base:
        raise CentralError("未配置共享账号中心")
    data = None
    headers = {"Content-Type": "application/json", "User-Agent": "nudge-client"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Cookie"] = "nudge_session=" + urllib.parse.quote(token, safe="")
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
            new_token = token
            for header in response.headers.get_all("Set-Cookie") or []:
                if header.startswith("nudge_session="):
                    new_token = header.split(";", 1)[0].split("=", 1)[1]
            return body, new_token
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw).get("detail", raw)
        except Exception:
            detail = raw
        raise CentralError(str(detail)[:500], error.code) from error
    except Exception as error:
        raise CentralError(f"无法连接共享账号中心：{error}") from error


def send_code(email: str, purpose: str) -> dict:
    body, _ = _request("/api/auth/send-code", payload={"email": email, "purpose": purpose})
    return body


def login(email: str, password: str) -> tuple[dict, str]:
    return _request("/api/auth/login", payload={"email": email, "password": password})


def register(nickname: str, email: str, password: str, confirm: str, code: str) -> tuple[dict, str]:
    return _request("/api/auth/register", payload={
        "nickname": nickname, "email": email, "password": password,
        "confirm": confirm, "code": code,
    })


def reset(email: str, code: str, password: str, confirm: str) -> dict:
    body, _ = _request("/api/auth/reset", payload={
        "email": email, "code": code, "password": password, "confirm": confirm,
    })
    return body


def demo() -> tuple[dict, str]:
    return _request("/api/auth/demo", payload={})


def logout(token: str) -> None:
    if token:
        try:
            _request("/api/auth/logout", payload={}, token=token)
        except Exception:
            pass


def settings_code(token: str, target: str, new_email: str = "") -> dict:
    body, _ = _request("/api/settings/code", payload={"target": target, "new_email": new_email}, token=token)
    return body


def settings_email(token: str, old_code: str, new_email: str, new_code: str) -> dict:
    body, _ = _request("/api/settings/email", payload={
        "old_code": old_code, "new_email": new_email, "new_code": new_code,
    }, token=token)
    return body


def settings_password(token: str, method: str, old_password: str, code: str,
                      password: str, confirm: str) -> dict:
    body, _ = _request("/api/settings/password", payload={
        "method": method, "old_password": old_password, "code": code,
        "password": password, "confirm": confirm,
    }, token=token)
    return body


def admin_users(token: str) -> dict:
    body, _ = _request("/api/central/users", method="GET", token=token)
    return body


def admin_update(token: str, central_id: str, payload: dict) -> dict:
    body, _ = _request("/api/admin/users/" + urllib.parse.quote(central_id, safe=""),
                       method="PATCH", payload=payload, token=token)
    return body


def session_token(user_id: str) -> str:
    return db.get_central_session(user_id)


def save_session(user_id: str, token: str) -> None:
    if token:
        db.save_central_session(user_id, token)


def clear_session(user_id: str) -> None:
    db.delete_central_session(user_id)


_last_presence: dict[str, float] = {}
_last_lock = threading.Lock()


def touch_presence(user: dict) -> None:
    """登录/活跃时异步上报在线状态，60 秒节流；失败不影响本地请求。"""
    if not enabled():
        return
    user_id = user.get("id")
    token = session_token(user_id)
    if not token:
        return
    now = time.time()
    with _last_lock:
        if now - _last_presence.get(user_id, 0) < 60:
            return
        _last_presence[user_id] = now
    settings = db.get_settings()
    payload = {
        "instance_id": settings.get("instance_id", ""),
        "event_count": len(db.list_events(user_id)),
        "has_key": bool((db.get_user_settings(user_id) or {}).get("api_key")),
        "campus": user.get("campus") or "",
    }
    threading.Thread(target=_send_presence, args=(token, payload), daemon=True).start()


def _send_presence(token: str, payload: dict) -> None:
    try:
        _request("/api/central/presence", payload=payload, token=token)
    except Exception:
        pass