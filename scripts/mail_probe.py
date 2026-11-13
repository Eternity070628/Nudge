"""从学校邮箱里读出最近 N 封邮件（用于自动取 Brevo 验证链接/验证码）。"""
from __future__ import annotations

import email
import imaplib
import os
import re
import sys
from email.header import decode_header, make_header
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for name in ("REPO/.env", "REPO/backend/.env"):
        pass
    path = REPO / ".env"
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    env = load_env()
    user = env.get("SMTP_USER") or os.getenv("SMTP_USER", "")
    password = env.get("SMTP_PASS") or os.getenv("SMTP_PASS", "")
    if not user or not password:
        raise SystemExit("缺 SMTP_USER / SMTP_PASS")
    conn = imaplib.IMAP4_SSL("imap.exmail.qq.com", 993)
    conn.login(user, password)
    conn.select("INBOX")
    status, data = conn.search(None, "ALL")
    ids = data[0].split()[-limit:]
    for uid in reversed(ids):
        status, raw = conn.fetch(uid, "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])
        subject = str(make_header(decode_header(msg.get("Subject", ""))))
        sender = str(make_header(decode_header(msg.get("From", ""))))
        date = msg.get("Date", "")
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        body += part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", "replace")
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", "replace")
            except Exception:
                body = str(msg.get_payload())
        links = re.findall(r"https?://[^\s\"'<>)]+", body)
        codes = re.findall(r"\b\d{6}\b", body)
        print("=" * 70)
        print("DATE:", date)
        print("FROM:", sender)
        print("SUBJ:", subject)
        if links:
            print("LINKS:", *links[:4], sep="\n  ")
        if codes:
            print("CODES:", codes[:5])
        print("TEXT:", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))[:400])
    conn.logout()


if __name__ == "__main__":
    main()
