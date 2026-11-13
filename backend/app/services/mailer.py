"""Microsoft Graph 邮件发送。

验证码由 Eternity070628@outlook.com 本人邮箱发出，使用设备码授权（公共客户端流）：
  1. 在 Entra 注册应用，允许公共客户端流，授予 delegated Mail.Send；
  2. 服务器上运行 `python -m app.services.mailer auth`，按提示完成一次授权；
  3. refresh token 存本机 SQLite settings 表，不进仓库。

本地没有 Graph 凭据时，可用 NUDGE_EMAIL_DEV=1 让接口把验证码回显到页面，明确标注开发模式。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import config, db

GRAPH_TOKEN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_DEVICE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode"
GRAPH_SEND = "https://graph.microsoft.com/v1.0/me/sendMail"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class MailError(RuntimeError):
    """邮件服务不可用；调用方应把原因原样告诉用户。"""


def _form(url: str, data: dict[str, str], timeout: int = 30) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = ""
        try:
            raw = error.read().decode("utf-8", "replace")
        except Exception:
            pass
        raise MailError(f"Graph 返回 {error.code}: {raw[:300]}") from error
    except Exception as error:
        raise MailError(f"Graph 连接失败: {error}") from error


def _json(url: str, token: str, payload: dict, timeout: int = 30) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
    except urllib.error.HTTPError as error:
        raw = ""
        try:
            raw = error.read().decode("utf-8", "replace")
        except Exception:
            pass
        raise MailError(f"Graph 发信返回 {error.code}: {raw[:300]}") from error
    except Exception as error:
        raise MailError(f"Graph 发信失败: {error}") from error


def _access_token() -> str:
    tenant = config.GRAPH_TENANT_ID
    client = config.GRAPH_CLIENT_ID
    if not tenant or not client:
        raise MailError("邮件服务未配置：请设置 GRAPH_TENANT_ID 和 GRAPH_CLIENT_ID")
    refresh = (db.get_settings().get("graph_refresh_token") or "").strip()
    if not refresh:
        raise MailError("邮件服务未授权：请先在服务器运行 python -m app.services.mailer auth")
    result = _form(GRAPH_TOKEN.format(tenant=tenant), {
        "client_id": client,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "scope": config.GRAPH_SCOPES,
    })
    if "access_token" not in result:
        raise MailError("Graph 刷新令牌失败：" + str(result)[:300])
    if result.get("refresh_token"):
        db.save_settings({"graph_refresh_token": result["refresh_token"]})
    return result["access_token"]


def send_code(to_email: str, code: str, purpose: str) -> dict:
    """发送验证码；开发模式返回 dev=True，由接口决定是否回显。"""
    if config.NUDGE_EMAIL_DEV:
        return {"dev": True}
    token = _access_token()
    action = "注册" if purpose == "register" else "重置密码"
    payload = {
        "message": {
            "subject": f"Nudge {action}验证码",
            "body": {
                "contentType": "Text",
                "content": f"你的 Nudge {action}验证码是 {code}，10 分钟内有效。\n如果不是你本人操作，请忽略这封邮件。",
            },
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": True,
    }
    _json(GRAPH_SEND, token, payload)
    return {"dev": False}


def device_auth() -> None:
    """一次性设备码授权：授权后把 refresh token 存进本机 SQLite。"""
    tenant = config.GRAPH_TENANT_ID
    client = config.GRAPH_CLIENT_ID
    if not tenant or not client:
        raise SystemExit("先设置 GRAPH_TENANT_ID 和 GRAPH_CLIENT_ID")
    start = _form(GRAPH_DEVICE.format(tenant=tenant), {
        "client_id": client,
        "scope": config.GRAPH_SCOPES,
    })
    print("打开：" + start.get("verification_uri", ""))
    print("输入代码：" + start.get("user_code", ""))
    print("账号：" + config.GRAPH_SENDER)
    interval = int(start.get("interval", 5))
    while True:
        time.sleep(interval)
        result = _form(GRAPH_TOKEN.format(tenant=tenant), {
            "client_id": client,
            "grant_type": DEVICE_GRANT,
            "device_code": start["device_code"],
        })
        error = result.get("error")
        if not error:
            refresh = result.get("refresh_token", "")
            if not refresh:
                raise SystemExit("授权成功但没有拿到 refresh_token")
            db.save_settings({"graph_refresh_token": refresh})
            print("授权完成，refresh token 已保存到本机数据库。")
            return
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise SystemExit("授权失败：" + str(result))


if __name__ == "__main__":
    device_auth()