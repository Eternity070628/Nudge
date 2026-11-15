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
  interests TEXT, token TEXT UNIQUE, created_at TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, title TEXT, category TEXT, campus TEXT,
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
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_settings (
  user_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS central_sessions (
  user_id TEXT PRIMARY KEY, token TEXT NOT NULL, created_at TEXT
);
CREATE TABLE IF NOT EXISTS central_presence (
  user_id TEXT NOT NULL, instance_id TEXT NOT NULL, last_seen TEXT,
  event_count INTEGER DEFAULT 0, has_key INTEGER DEFAULT 0, campus TEXT,
  PRIMARY KEY (user_id, instance_id)
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
            ("campus", "TEXT"),
            ("last_seen", "TEXT"),
            ("central_id", "TEXT"),
        ):
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")
            except sqlite3.OperationalError:
                pass
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_central ON users(central_id)")
        instance = c.execute("SELECT value FROM settings WHERE key='instance_id'").fetchone()
        if not instance:
            c.execute("INSERT INTO settings(key,value) VALUES('instance_id',?)", (uuid.uuid4().hex[:12],))
        try:
            c.execute("ALTER TABLE events ADD COLUMN campus TEXT")
        except sqlite3.OperationalError:
            pass
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
        # 演示账号默认给海淀校区，方便评委直接看到校区判定效果
        c.execute(
            "UPDATE users SET campus=? WHERE id=? AND (campus IS NULL OR campus='')",
            ("haidian", "u_demo"),
        )
        _migrate_events_per_user(c)


def _migrate_events_per_user(c: sqlite3.Connection) -> None:
    """把历史共享事件拆成每用户一份；之后新事件也按用户各自去重。"""
    if c.execute("SELECT 1 FROM settings WHERE key='events_per_user'").fetchone():
        return
    events = c.execute("SELECT * FROM events").fetchall()
    for event in events:
        user_ids = [
            row["user_id"] for row in c.execute(
                "SELECT user_id FROM user_events WHERE event_id=?", (event["id"],)
            ).fetchall()
        ]
        if not user_ids:
            c.execute("DELETE FROM events WHERE id=?", (event["id"],))
            continue
        data = dict(event)
        # 先删除原行，否则 u1 的新去重键会和原事件行上的旧键冲突
        c.execute("DELETE FROM events WHERE id=?", (data["id"],))
        for user_id in user_ids:
            new_id = "e_" + uuid.uuid4().hex[:10]
            key = hashlib.sha1(
                (user_id + "|" + data["title"].strip() + "|" + (data["deadline_end"] or "")).encode("utf-8")
            ).hexdigest()[:16]
            c.execute(
                """INSERT INTO events(id,title,category,campus,deadline_start,deadline_end,
                   deadline_raw,audience,materials,submission,evidence,source,importance,
                   confidence,overall_confidence,dedup_key,created_at,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id, data["title"], data["category"], data["campus"],
                    data["deadline_start"], data["deadline_end"], data["deadline_raw"],
                    data["audience"], data["materials"], data["submission"],
                    data["evidence"], data["source"], data["importance"],
                    data["confidence"], data["overall_confidence"], key,
                    data["created_at"], data["status"],
                ),
            )
            c.execute(
                "UPDATE user_events SET event_id=? WHERE user_id=? AND event_id=?",
                (new_id, user_id, data["id"]),
            )
            c.execute(
                "UPDATE feedback SET event_id=? WHERE user_id=? AND event_id=?",
                (new_id, user_id, data["id"]),
            )
    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('events_per_user','1')")


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


def dedup_key(draft: EventDraft, user_id: str | None = None) -> str:
    raw = (draft.title.strip() + "|" + (draft.deadline.end or "")).encode("utf-8")
    if user_id:
        raw = (user_id + "|").encode("utf-8") + raw
    return hashlib.sha1(raw).hexdigest()[:16]


def save_event(draft: EventDraft, user_id: str, relevance: float = 0.5,
               reasons: list[str] | None = None) -> tuple[str, bool]:
    """返回 (event_id, 是否新建)。每个用户一条事件，同一用户重复保存直接复用。"""
    key = dedup_key(draft, user_id)
    with conn() as c:
        row = c.execute("SELECT id FROM events WHERE dedup_key=?", (key,)).fetchone()
        created = row is None
        if created:
            eid, created = "e_" + uuid.uuid4().hex[:10], True
            c.execute(
                """INSERT INTO events(id,title,category,campus,deadline_start,deadline_end,deadline_raw,
                   audience,materials,submission,evidence,source,importance,confidence,
                   overall_confidence,dedup_key,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid, draft.title, draft.category, draft.campus,
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
        c.execute(
            "UPDATE events SET campus=? WHERE id=? AND (campus IS NULL OR campus='')",
            (draft.campus, eid),
        )
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
    if isinstance(d["submission"], dict) and not d["submission"].get("campus"):
        d["submission"]["campus"] = d.get("campus") or "unknown"
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


def get_user_settings(user_id: str) -> dict[str, str]:
    """每个用户自己的模型设置，覆盖全局设置。"""
    try:
        with conn() as c:
            rows = c.execute("SELECT key, value FROM user_settings WHERE user_id=?", (user_id,)).fetchall()
        return {r["key"]: r["value"] for r in rows}
    except sqlite3.OperationalError:
        return {}


def save_user_settings(user_id: str, values: dict[str, str]) -> None:
    with conn() as c:
        for key, value in values.items():
            c.execute(
                "INSERT INTO user_settings(user_id,key,value) VALUES(?,?,?) "
                "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                (user_id, key, value),
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


def update_email(user_id: str, email: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET email=? WHERE id=?", (email, user_id))


def update_name(user_id: str, name: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))


def update_password_by_id(user_id: str, password_hash: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))


def get_user_by_central_id(central_id: str) -> Optional[dict[str, Any]]:
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE central_id=?", (central_id,)).fetchone()
    if not row:
        return None
    user = dict(row)
    user["interests"] = json.loads(user["interests"] or "[]")
    return user


def upsert_central_user(central_id: str, name: str, email: str,
                        is_admin: bool = False) -> dict[str, Any]:
    """中心账号 → 本地镜像；邮箱相同的旧本地账号自动绑定 central_id。"""
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE central_id=?", (central_id,)).fetchone()
        if row:
            c.execute(
                "UPDATE users SET name=?, email=?, is_admin=? WHERE id=?",
                ((name or "").strip(), (email or "").strip().lower(), 1 if is_admin else 0, row["id"]),
            )
            user_id = row["id"]
        else:
            row = c.execute("SELECT * FROM users WHERE id=?", (central_id,)).fetchone()
            if not row:
                row = c.execute("SELECT * FROM users WHERE lower(email)=?", ((email or "").strip().lower(),)).fetchone()
            if row:
                c.execute(
                    "UPDATE users SET central_id=?, name=?, is_admin=? WHERE id=?",
                    (central_id, (name or "").strip(), 1 if is_admin else 0, row["id"]),
                )
                user_id = row["id"]
            else:
                user_id = "u_" + uuid.uuid4().hex[:10]
                c.execute(
                    """INSERT INTO users(id,name,grade,major,interests,token,created_at,
                       email,is_admin,central_id) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (user_id, (name or "Nudge 用户").strip(), "", "", "[]",
                     "cal-" + uuid.uuid4().hex, now_iso(), (email or "").strip().lower(),
                     1 if is_admin else 0, central_id),
                )
    return get_user(user_id) or {}


def save_central_session(user_id: str, token: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO central_sessions(user_id,token,created_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET token=excluded.token, created_at=excluded.created_at",
            (user_id, token, now_iso()),
        )


def get_central_session(user_id: str) -> str:
    with conn() as c:
        row = c.execute("SELECT token FROM central_sessions WHERE user_id=?", (user_id,)).fetchone()
    return row["token"] if row else ""


def delete_central_session(user_id: str) -> None:
    with conn() as c:
        c.execute("DELETE FROM central_sessions WHERE user_id=?", (user_id,))


def upsert_presence(user_id: str, instance_id: str, event_count: int,
                    has_key: bool, campus: str) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO central_presence(user_id,instance_id,last_seen,event_count,has_key,campus)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(user_id,instance_id) DO UPDATE SET
                 last_seen=excluded.last_seen, event_count=excluded.event_count,
                 has_key=excluded.has_key, campus=excluded.campus""",
            (user_id, instance_id, now_iso(), int(event_count), 1 if has_key else 0, campus or ""),
        )


def list_presence() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            "SELECT user_id,instance_id,last_seen,event_count,has_key,campus "
            "FROM central_presence ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def touch_last_seen(user_id: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET last_seen=? WHERE id=?", (now_iso(), user_id))


def update_campus(user_id: str, campus: str) -> None:
    with conn() as c:
        c.execute("UPDATE users SET campus=? WHERE id=?", (campus, user_id))


def list_users() -> list[dict[str, Any]]:
    with conn() as c:
        rows = c.execute(
            """SELECT u.id, u.name, u.email, u.is_admin, u.created_at, u.last_seen,
                      u.campus, u.disabled, u.central_id,
                      (SELECT COUNT(*) FROM user_events ue WHERE ue.user_id=u.id) AS event_count,
                      EXISTS(SELECT 1 FROM user_settings s
                             WHERE s.user_id=u.id AND s.key='api_key' AND s.value<>'') AS has_key
               FROM users u ORDER BY u.created_at ASC"""
        ).fetchall()
    now = datetime.now(timezone.utc)
    users = []
    for row in rows:
        user = dict(row)
        last_seen = user.get("last_seen")
        online = False
        if last_seen:
            try:
                online = (now - datetime.fromisoformat(last_seen)).total_seconds() <= 300
            except ValueError:
                online = False
        user["online"] = online
        user["status"] = "在线" if online else ("离线" if last_seen else "未活跃")
        user["status_key"] = "online" if online else ("offline" if last_seen else "idle")
        users.append(user)
    return users


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
        c.execute("DELETE FROM user_settings WHERE user_id=?", (user_id,))
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
