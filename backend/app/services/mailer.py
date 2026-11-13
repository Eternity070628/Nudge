"""Microsoft Graph 邮件发送：Nudge 的注册 / 重置密码验证码。

为什么不用 SMTP：2024-09-16 起 Outlook 个人账户停用 SMTP 基本认证，应用专用密码也失效，
而且很多校园网封出站 587/465。Graph 的 /me/sendMail 走 HTTPS 443，用的还是你本人邮箱，
发件人、签名、已发送文件夹全都对得上。

授权方式：设备码（公共客户端流）
    python -m app.services.mailer auth
    1. 终端会打印一个 8 位代码和 https://www.microsoft.com/link；
    2. 用要发信的邮箱登录并同意 Mail.Send；
    3. refresh token 写进本机 SQLite 的 settings 表，不进仓库。

已经拿到 refresh token 时也可以直接导入（适合部署）：
    python -m app.services.mailer auth --import-token "M.C5..."

没有凭据时用 NUDGE_EMAIL_DEV=1 让接口把验证码回显到页面，并明确标注开发模式。
"""
from __future__ import annotations

import argparse
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

# 这几类状态码几乎都是微软侧的问题（服务降级 / 故障），不该让用户以为是自己配错了
OUTAGE_CODES = {500, 502, 503, 504}
AUTH_HINTS = ("invalid_grant", "InvalidAuthenticationToken", "AADSTS70000", "AADSTS50173", "AADSTS700082")


class MailError(RuntimeError):
    """邮件服务不可用；调用方应把原因原样告诉用户，绝不假装发信成功。"""


def _http_error(prefix: str, code: int, raw: str) -> MailError:
    if code in OUTAGE_CODES:
        return MailError(
            f"{prefix}：Microsoft Graph 暂时不可用（HTTP {code}）。这是微软侧故障，"
            "不是配置问题，稍后重试即可；本地可设 NUDGE_EMAIL_DEV=1 先走开发模式。"
        )
    if code == 401 or any(hint in raw for hint in AUTH_HINTS):
        return MailError(
            f"{prefix}：邮箱授权已失效（HTTP {code}），请在服务器运行 "
            "python -m app.services.mailer auth 重新授权一次。"
        )
    if code == 403:
        return MailError(
            f"{prefix}：应用没有发信权限（HTTP 403），请确认授权时同意了 Mail.Send。"
        )
    return MailError(f"{prefix}：Graph 返回 HTTP {code}：{raw[:300]}")


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
        raise _http_error("Graph 授权失败", error.code, raw) from error
    except Exception as error:
        raise MailError(f"Graph 连接失败：{error}（检查服务器能否访问 443 端口的 Microsoft 域名）") from error


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
        raise _http_error("Graph 发信失败", error.code, raw) from error
    except Exception as error:
        raise MailError(f"Graph 发信失败：{error}") from error


def _stored_token() -> str:
    return (db.get_settings().get("graph_refresh_token") or "").strip()


def ensure_token() -> bool:
    """把环境变量里的 refresh token 落进本机数据库（首次启动 / 新机器部署用）。

    返回数据库里现在是否有令牌。已存在时不覆盖，避免把环境变量里过期的旧值写回去。
    """
    if _stored_token():
        return True
    if config.GRAPH_REFRESH_TOKEN:
        db.save_settings({"graph_refresh_token": config.GRAPH_REFRESH_TOKEN})
        return True
    return False


def _access_token() -> str:
    if not config.GRAPH_TENANT_ID or not config.GRAPH_CLIENT_ID:
        raise MailError("邮件服务未配置：请设置 GRAPH_TENANT_ID 和 GRAPH_CLIENT_ID")
    if not ensure_token():
        raise MailError(
            "邮件服务未授权：请先在服务器运行 python -m app.services.mailer auth "
            "（或把 GRAPH_REFRESH_TOKEN 放进环境变量）"
        )
    result = _form(GRAPH_TOKEN.format(tenant=config.GRAPH_TENANT_ID), {
        "client_id": config.GRAPH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": _stored_token(),
        "scope": config.GRAPH_SCOPES,
    })
    if "access_token" not in result:
        raise MailError("Graph 刷新令牌失败：" + str(result)[:300])
    # 微软每次刷新都会换发新的 refresh token，必须回写，否则下次就失效
    if result.get("refresh_token"):
        db.save_settings({"graph_refresh_token": result["refresh_token"]})
    return result["access_token"]


def send_code(to_email: str, code: str, purpose: str) -> dict:
    """发送验证码；开发模式返回 dev=True，由接口决定是否回显。"""
    if config.NUDGE_EMAIL_DEV:
        print(f"[DEV] 未真实发信，验证码 {code} -> {to_email}")
        return {"dev": True}
    token = _access_token()
    action = "注册" if purpose == "register" else "重置密码"
    payload = {
        "message": {
            "subject": f"Nudge {action}验证码",
            "body": {
                "contentType": "Text",
                "content": (
                    f"你的 Nudge {action}验证码是 {code}，10 分钟内有效。\n"
                    f"如果不是你本人操作，请忽略这封邮件。\n\n"
                    f"—— Nudge · 校园截止管家"
                ),
            },
            "toRecipients": [{"emailAddress": {"address": to_email}}],
            # 发件箱里能看到自己发出的验证码，答辩时可以现场翻给对方看
            "saveToSentItems": True,
        },
    }
    _json(GRAPH_SEND, token, payload)
    return {"dev": False}


def status() -> dict:
    """给前端/运维看的真实状态：现在是真发信、开发模式，还是缺授权。"""
    authorized = bool(_stored_token())
    if config.NUDGE_EMAIL_DEV:
        mode = "dev"
    elif authorized:
        mode = "graph"
    else:
        mode = "unconfigured"
    return {
        "mode": mode,
        "real_sending": mode == "graph",
        "sender": config.GRAPH_SENDER,
        "tenant": config.GRAPH_TENANT_ID,
        "client_id": config.GRAPH_CLIENT_ID,
        "authorized": authorized,
        "dev_code_visible": config.NUDGE_EMAIL_DEV,
    }


def device_auth(client_id: str = "", tenant: str = "", scope: str = "") -> None:
    """一次性设备码授权：授权后把 refresh token 存进本机 SQLite。"""
    tenant = (tenant or config.GRAPH_TENANT_ID).strip()
    client_id = (client_id or config.GRAPH_CLIENT_ID).strip()
    scope = (scope or config.GRAPH_SCOPES).strip()
    if not tenant or not client_id:
        raise SystemExit("先设置 GRAPH_TENANT_ID 和 GRAPH_CLIENT_ID")
    start = _form(GRAPH_DEVICE.format(tenant=tenant), {
        "client_id": client_id,
        "scope": scope,
    })
    if "device_code" not in start:
        raise SystemExit("申请设备码失败：" + str(start)[:300])
    print("1. 打开：" + start.get("verification_uri", "https://www.microsoft.com/link"))
    print("2. 输入代码：" + start.get("user_code", ""))
    print("3. 用要发信的邮箱登录并同意 Mail.Send：" + config.GRAPH_SENDER)
    print("   等待授权…（15 分钟内有效）")
    interval = int(start.get("interval", 5))
    while True:
        time.sleep(interval)
        result = _form(GRAPH_TOKEN.format(tenant=tenant), {
            "client_id": client_id,
            "grant_type": DEVICE_GRANT,
            "device_code": start["device_code"],
        })
        error = result.get("error")
        if not error:
            refresh = result.get("refresh_token", "")
            if not refresh:
                raise SystemExit("授权成功但没有拿到 refresh_token")
            db.save_settings({"graph_refresh_token": refresh})
            print("授权完成，refresh token 已保存到本机数据库：" + str(config.DB_PATH))
            return
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        raise SystemExit("授权失败：" + str(result))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.mailer",
        description="Nudge 邮箱验证码：Microsoft Graph 设备码授权 / 导入 refresh token / 查看状态",
    )
    parser.add_argument("command", nargs="?", default="auth", choices=["auth", "status"])
    parser.add_argument("--client-id", default="", help="自己的 Entra 应用 id，默认用微软 Graph 命令行客户端")
    parser.add_argument("--tenant", default="", help="租户：consumers（个人号）/ 租户 id / 域名")
    parser.add_argument("--scope", default="", help="默认 https://graph.microsoft.com/Mail.Send offline_access")
    parser.add_argument("--import-token", default="", help="已有 refresh token 时直接写入本机数据库")
    args = parser.parse_args(argv)

    if args.command == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
        return

    if args.import_token:
        db.save_settings({"graph_refresh_token": args.import_token.strip()})
        print("refresh token 已写入本机数据库：" + str(config.DB_PATH))
        return

    device_auth(args.client_id, args.tenant, args.scope)


if __name__ == "__main__":
    main()
