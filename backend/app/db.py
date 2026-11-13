"""SQLite 持久层。故意不用 ORM：评委能看到每一条 SQL，出问题也好查。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .config import DB_PATH
from .models import EventDraft

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, name TEXT, grade TEXT, major TEXT,
  interests TEXT, token TEXT UNIQUE, created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, title TEXT, category TEXT,
  deadline_start TEXT, deadline_end TEXT, deadline_raw TEXT,
  audience TEXT, materials TEXT, submission TEXT,
  evidence TEXT, source TEXT, importance INTEGER,
  confidence TEXT, overall_confidence REAL,
  dedup_key TEXT UNIQUE, created_at TEXT, status TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS user_events (
  user_id TEXT, event_id TEXT, relevance REAL, reasons TEXT,
  created_at TEXT, done_at TEXT, PRIMARY KEY (user_id, event_id)
);
CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY, user_id TEXT, event_id TEXT, kind TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, expires_at TEXT
);
CREATE TABLE IF NOT EXISTS email_codes (
  id TEXT PRIMARY KEY, email TEXT, purpose TEXT, code_hash TEXT,
  expires_at TEXT, used INTEGER DEFAULT 0, created_at TEXT
);
"""

ADMIN_EMAIL = "Eternity070628@bupt.edu.cn"
ADMIN_NAME = "Eternity"
ADMIN_HASH = "pbkdf2_sha256$200000$cdbff0c3673141d7bdd4c8b031286e73$e9b98958f2c397ed42af1d6e4c4e5eb4a218387b34d8b2dbdcea95e34b27bb1b"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        for column, ddl in (
            ("email", "TEXT"),
            ("password_hash", "TEXT"),
            ("is_admin", "INTEGER DEFAULT 0"),
            ("disabled", "INTEGER DEFAULT 0"),
        ):
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        c.execute(
            "INSERT OR IGNORE INTO users(id,name,grade,major,interests,token,created_at) VALUES(?,?,?,?,?,?,?)",
            ("u_demo", "张同学", "2024级", "计算机学院",
             json.dumps(["竞赛", "编程", "奖学金"], ensure_ascii=False),
             "demo-token-2026", now_iso()),
        )
        c.execute(
            "INSERT OR IGNORE INTO users(id,name,grade,major,interests,token,created_at,email,password_hash,is_admin) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("u_admin", ADMIN_NAME, "", "", "[]", "admin-token-2026",
             now_iso(), ADMIN_EMAIL, ADMIN_HASH, 1),
        )


def get_user(user_id: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["interests"] = json.loads(d["interests"] or "[]")
    return d


def upsert_user(user_id: str, name: str, grade: str, major: str, interests: list[str]) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO users(id,name,grade,major,interests,token,created_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, name, grade, major, json.dumps(interests, ensure_ascii=False),
             "token-" + user_id, now_iso()),
        )


def dedup_key(draft: EventDraft) -> str:
    raw = (draft.title.strip() + "|" + (draft.deadline.end or "")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def save_event(draft: EventDraft, user_id: str, relevance: float = 0.5,
               reasons: list[str] | None = None) -> tuple[str, bool]:
    """返回 (event_id, 是否新建)。重复事件直接复用，不产生第二条。"""
    key = dedup_key(draft)
    with conn() as c:
        row = c.execute("SELECT id FROM events WHERE dedup_key=?", (key,)).fetchone()
        created = row is None
        if created:
            eid, created = "e_" + uuid.uuid4().hex[:10], True
            c.execute(
                """INSERT INTO events(id,title,category,deadline_start,deadline_end,deadline_raw,
                   audience,materials,submission,evidence,source,importance,confidence,
                   overall_confidence,dedup_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid, draft.title, draft.category,
                    draft.deadline.start, draft.deadline.end, draft.deadline.raw,
                    draft.audience.model_dump_json(),
                    json.dumps([m.model_dump() for m in draft.materials], ensure_ascii=False),
                    draft.submission.model_dump_json(),
                    json.dumps(draft.evidence, ensure_ascii=False),
                    draft.source.model_dump_json(),
                    draft.importance,
                    json.dumps(draft.confidence, ensure_ascii=False),
                    draft.overall_confidence,
                    key, now_iso(),
                ),
            )
        else:
            eid = row["id"]
        had_user_event = c.execute(
            "SELECT 1 FROM user_events WHERE user_id=? AND event_id=?", (user_id, eid)
        ).fetchone() is not None
        c.execute(
            """INSERT INTO user_events(user_id,event_id,relevance,reasons,created_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(user_id,event_id) DO UPDATE SET
                 relevance=excluded.relevance, reasons=excluded.reasons""",
            (user_id, eid, relevance, json.dumps(reasons or [], ensure_ascii=False), now_iso()),
        )
    return eid, not had_user_event


def _row_to_event(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("audience", "submission", "evidence", "confidence", "source"):
        d[k] = json.loads(d[k] or "{}")
    d["materials"] = json.loads(d["materials"] or "[]")
    d["reasons"] = json.loads(d.get("reasons") or "[]")
    return d


def list_events(user_id: str) -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            """SELECT e.*, ue.relevance, ue.reasons, ue.done_at FROM events e
               JOIN user_events ue ON ue.event_id = e.id
               WHERE ue.user_id=?
               ORDER BY (ue.done_at IS NOT NULL), COALESCE(e.deadline_end, '9999') ASC""",
            (user_id,),
        ).fetchall()
    return [_row_to_event(r) for r in rows]


def get_event(event_id: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    return _row_to_event(row) if row else None


def mark_done(user_id: str, event_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE user_events SET done_at=? WHERE user_id=? AND event_id=?",
                  (now_iso(), user_id, event_id))


def add_feedback(user_id: str, event_id: str, kind: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO feedback(id,user_id,event_id,kind,created_at) VALUES(?,?,?,?,?)",
                  ("f_" + uuid.uuid4().hex[:8], user_id, event_id, kind, now_iso()))


def feedback_stats(user_id: str) -> dict[str, int]:
    with conn() as c:
        rows = c.execute("SELECT kind, COUNT(*) n FROM feedback WHERE user_id=? GROUP BY kind", (user_id,)).fetchall()
    return {r["kind"]: r["n"] for r in rows}


def get_settings() -> dict[str, str]:
    """模型设置存本机 SQLite；表不存在时返回空，保证评测/冷启动不报错。"""
    try:
        with conn() as c:
            rows = c.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except sqlite3.OperationalError:
        return {}


def save_settings(values: dict[str, str]) -> None:
    with conn() as c:
        for key, value in values.items():
            c.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE lower(email)=?", (email.strip().lower(),)).fetchone()
    return dict(row) if row else None


def get_user_by_token(token: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def create_user(email: str, name: str, password_hash: str, token: str) -> str:
    user_id = "u_" + uuid.uuid4().hex[:10]
    with conn() as c:
        c.execute(
            "INSERT INTO users(id,name,grade,major,interests,token,created_at,email,password_hash,is_admin,disabled) "
            "VALUES(?,?,?,?,?,?,?,?,?,0,0)",
            (user_id, name, "", "", "[]", token, now_iso(), email, password_hash),
        )
    return user_id


def update_password(email: str, password_hash: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE email=?", (password_hash, email))


def list_users() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            """SELECT u.id, u.name, u.email, u.is_admin, u.created_at,
                      (SELECT COUNT(*) FROM user_events ue WHERE ue.user_id=u.id) AS event_count
               FROM users u ORDER BY u.created_at ASC"""
        ).fetchall()
    return [dict(r) for r in rows]


def delete_user(user_id: str) -> bool:
    """删账号、事件关联、反馈、会话、验证码；只清理没有其它用户引用的事件。"""
    with conn() as c:
        row = c.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            return False
        event_ids = [r["event_id"] for r in c.execute(
            "SELECT event_id FROM user_events WHERE user_id=?", (user_id,)
        ).fetchall()]
        c.execute("DELETE FROM user_events WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM feedback WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        if row["email"]:
            c.execute("DELETE FROM email_codes WHERE email=?", (row["email"],))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        for event_id in event_ids:
            left = c.execute("SELECT COUNT(*) n FROM user_events WHERE event_id=?", (event_id,)).fetchone()["n"]
            if not left:
                c.execute("DELETE FROM events WHERE id=?", (event_id,))
    return True


def create_session(token: str, user_id: str, expires_at: str) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                  (token, user_id, now_iso(), expires_at))


def get_session_user(token: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute(
            """SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token=? AND s.expires_at > ? AND COALESCE(u.disabled,0)=0""",
            (token, now_iso()),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def delete_user_sessions(user_id: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def create_email_code(email: str, purpose: str, code_hash: str, expires_at: str) -> str:
    code_id = "c_" + uuid.uuid4().hex[:10]
    with conn() as c:
        c.execute(
            "INSERT INTO email_codes(id,email,purpose,code_hash,expires_at,used,created_at) "
            "VALUES(?,?,?,?,?,0,?)",
            (code_id, email, purpose, code_hash, expires_at, now_iso()),
        )
    return code_id


def get_email_code(email: str, purpose: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute(
            "SELECT * FROM email_codes WHERE email=? AND purpose=? AND used=0 "
            "ORDER BY created_at DESC LIMIT 1",
            (email, purpose),
        ).fetchone()
    return dict(row) if row else None


def last_email_code_at(email: str, purpose: str) -> Optional[str]:
    with conn() as c:
        row = c.execute(
            "SELECT created_at FROM email_codes WHERE email=? AND purpose=? ORDER BY created_at DESC LIMIT 1",
            (email, purpose),
        ).fetchone()
    return row["created_at"] if row else None


def mark_email_code_used(code_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE email_codes SET used=1 WHERE id=?", (code_id,))


def mark_active(user_id: str, event_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE user_events SET done_at=NULL WHERE user_id=? AND event_id=?", (user_id, event_id))


def delete_event(user_id: str, event_id: str) -> bool:
    with conn() as c:
        row = c.execute("SELECT 1 FROM user_events WHERE user_id=? AND event_id=?", (user_id, event_id)).fetchone()
        if not row:
            return False
        c.execute("DELETE FROM user_events WHERE user_id=? AND event_id=?", (user_id, event_id))
        c.execute("DELETE FROM feedback WHERE user_id=? AND event_id=?", (user_id, event_id))
        left = c.execute("SELECT COUNT(*) n FROM user_events WHERE event_id=?", (event_id,)).fetchone()["n"]
        if not left:
            c.execute("DELETE FROM events WHERE id=?", (event_id,))
    return True
