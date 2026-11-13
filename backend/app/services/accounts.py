"""账号、密码、会话与邮箱验证码。密码只存 PBKDF2 哈希，不存明文。"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from . import mailer

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
SESSION_DAYS = 7
CODE_MINUTES = 10
CODE_INTERVAL_SECONDS = 60


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return f"pbkdf2_sha256$200000${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(actual, digest)
    except Exception:
        return False


def public_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not user:
        return None
    result = {key: value for key, value in user.items() if key not in ("password_hash", "disabled")}
    if isinstance(result.get("interests"), str):
        try:
            result["interests"] = json.loads(result["interests"] or "[]")
        except Exception:
            result["interests"] = []
    return result


def find_by_email(email: str) -> dict[str, Any] | None:
    return db.get_user_by_email(normalize_email(email))


def login(email: str, password: str) -> dict[str, Any] | None:
    user = find_by_email(email)
    if not user or user.get("disabled") or not user.get("password_hash"):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return public_user(user)


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc).astimezone() + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    db.create_session(token, user_id, expires)
    return token


def session_user(token: str) -> dict[str, Any] | None:
    if not token:
        return None
    return public_user(db.get_session_user(token))


def logout(token: str) -> None:
    if token:
        db.delete_session(token)


def _code_hash(email: str, purpose: str, code: str) -> str:
    return hashlib.sha256(f"{purpose}:{email}:{code}".encode("utf-8")).hexdigest()


def _validate_email(email: str) -> str:
    email = normalize_email(email)
    if not EMAIL_RE.match(email):
        raise ValueError("邮箱格式不正确")
    return email


def issue_code(email: str, purpose: str) -> dict[str, Any]:
    email = _validate_email(email)
    user = find_by_email(email)
    if purpose == "register" and user:
        raise ValueError("该邮箱已注册，请直接登录")
    if purpose == "reset" and not user:
        raise ValueError("该邮箱尚未注册")
    last = db.last_email_code_at(email, purpose)
    if last:
        try:
            elapsed = (datetime.now(timezone.utc).astimezone() - datetime.fromisoformat(last)).total_seconds()
            if elapsed < CODE_INTERVAL_SECONDS:
                raise ValueError("验证码发送太频繁，请稍后再试")
        except ValueError:
            raise
        except Exception:
            pass
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = (datetime.now(timezone.utc).astimezone() + timedelta(minutes=CODE_MINUTES)).isoformat(timespec="seconds")
    code_id = db.create_email_code(email, purpose, _code_hash(email, purpose, code), expires)
    try:
        result = mailer.send_code(email, code, purpose)
    except mailer.MailError:
        db.mark_email_code_used(code_id)
        raise
    return {"dev": bool(result.get("dev")), "code": code if result.get("dev") else "", "expires_in": CODE_MINUTES * 60}


def _consume_code(email: str, purpose: str, code: str) -> None:
    row = db.get_email_code(email, purpose)
    if not row or row["expires_at"] <= datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"):
        raise ValueError("验证码错误或已过期")
    if not hmac.compare_digest(row["code_hash"], _code_hash(email, purpose, code.strip())):
        raise ValueError("验证码错误或已过期")
    db.mark_email_code_used(row["id"])


def register(nickname: str, email: str, password: str, confirm: str, code: str) -> dict[str, Any]:
    nickname = (nickname or "").strip()
    email = _validate_email(email)
    if not 1 <= len(nickname) <= 20:
        raise ValueError("昵称长度需要 1–20 个字")
    if len(password or "") < 8:
        raise ValueError("密码至少 8 位")
    if password != confirm:
        raise ValueError("两次输入的密码不一致")
    if find_by_email(email):
        raise ValueError("该邮箱已注册，请直接登录")
    _consume_code(email, "register", code)
    user_id = db.create_user(email, nickname, hash_password(password), "cal-" + secrets.token_urlsafe(18))
    user = db.get_user(user_id)
    return public_user(user)


def reset_password(email: str, code: str, password: str, confirm: str) -> None:
    email = _validate_email(email)
    user = find_by_email(email)
    if not user:
        raise ValueError("该邮箱尚未注册")
    if len(password or "") < 8:
        raise ValueError("密码至少 8 位")
    if password != confirm:
        raise ValueError("两次输入的密码不一致")
    _consume_code(email, "reset", code)
    db.update_password(email, hash_password(password))
    db.delete_user_sessions(user["id"])


def demo_user() -> dict[str, Any] | None:
    return public_user(db.get_user("u_demo"))