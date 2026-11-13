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
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

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


def _mail_text(action: str, code: str) -> str:
    return (
        f"你的 Nudge {action}验证码是 {code}，10 分钟内有效。\n"
        f"如果不是你本人操作，请忽略这封邮件。\n\n"
        f"—— Nudge · 校园截止管家"
    )


def _smtp_configured() -> bool:
    return bool(config.SMTP_USER and config.SMTP_PASS)


def _smtp_send(to_email: str, subject: str, text: str) -> None:
    """用邮箱自己的 SMTP 发信（学校/企业邮箱如腾讯企业邮）。"""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config.SMTP_SENDER_NAME, config.SMTP_SENDER))
    message["To"] = to_email
    message.set_content(text)

    host, port = config.SMTP_HOST, config.SMTP_PORT
    context = ssl.create_default_context()
    if not config.SMTP_VERIFY_TLS:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        if config.SMTP_SECURITY == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=25, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=25)
            if config.SMTP_SECURITY == "starttls":
                server.starttls(context=context)
    except ssl.SSLCertVerificationError as error:
        raise MailError(
            f"SMTP 证书校验失败（{host}）：{error}。"
            "通常是主机名和证书不匹配，改用服务商的标准主机名"
            "（腾讯企业邮用 smtp.exmail.qq.com）；"
            "确知安全时也可在 .env 里设 SMTP_VERIFY_TLS=0 临时跳过。"
        ) from error
    except OSError as error:
        raise MailError(
            f"SMTP 连不上 {host}:{port}：{error}。检查网络是否放行该端口，"
            "或换 SMTP_SECURITY=starttls / SMTP_PORT=587。"
        ) from error
    except smtplib.SMTPException as error:
        raise MailError(f"SMTP 握手失败（{host}:{port}）：{error}") from error

    try:
        server.login(config.SMTP_USER, config.SMTP_PASS)
    except smtplib.SMTPAuthenticationError as error:
        raise MailError(
            "SMTP 认证失败：账号或密码不对。腾讯企业邮/学校邮箱通常要先去邮箱设置里"
            "开启 SMTP 并生成「客户端专用密码」，用它填 SMTP_PASS。"
        ) from error
    except smtplib.SMTPException as error:
        raise MailError(f"SMTP 登录失败：{error}") from error
    try:
        server.send_message(message)
    except smtplib.SMTPRecipientsRefused as error:
        raise MailError(f"收件地址被拒绝：{error}") from error
    except smtplib.SMTPException as error:
        raise MailError(f"SMTP 发信失败：{error}") from error
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_code(to_email: str, code: str, purpose: str) -> dict:
    """发送验证码；开发模式返回 dev=True，由接口决定是否回显。"""
    if config.NUDGE_EMAIL_DEV:
        print(f"[DEV] 未真实发信，验证码 {code} -> {to_email}")
        return {"dev": True}
    action = "注册" if purpose == "register" else "重置密码"
    subject = f"Nudge {action}验证码"
    text = _mail_text(action, code)
    if status()["mode"] == "smtp":
        _smtp_send(to_email, subject, text)
        return {"dev": False}

    token = _access_token()
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": text},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
            # 发件箱里能看到自己发出的验证码，答辩时可以现场翻给对方看
            "saveToSentItems": True,
        },
    }
    _json(GRAPH_SEND, token, payload)
    return {"dev": False}


def status() -> dict:
    """给前端/运维看的真实状态：真发信走哪条通道、还是开发模式 / 缺配置。"""
    authorized = bool(_stored_token())
    smtp_ready = _smtp_configured()
    transport = config.MAIL_TRANSPORT
    if config.NUDGE_EMAIL_DEV or transport == "dev":
        mode = "dev"
    elif transport == "smtp":
        mode = "smtp" if smtp_ready else "unconfigured"
    elif transport == "graph":
        mode = "graph" if authorized else "unconfigured"
    elif smtp_ready:  # auto：有 SMTP 凭据就优先它，学校邮箱通常更稳
        mode = "smtp"
    elif authorized:
        mode = "graph"
    else:
        mode = "unconfigured"
    return {
        "mode": mode,
        "transport": transport,
        "real_sending": mode in ("smtp", "graph"),
        "sender": config.SMTP_SENDER if mode == "smtp" else config.GRAPH_SENDER,
        "smtp": {
            "host": config.SMTP_HOST,
            "port": config.SMTP_PORT,
            "security": config.SMTP_SECURITY,
            "user": config.SMTP_USER,
        },
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
