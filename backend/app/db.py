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
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        c.execute(
            "INSERT OR IGNORE INTO users(id,name,grade,major,interests,token,created_at) VALUES(?,?,?,?,?,?,?)",
            ("u_demo", "张同学", "2024级", "计算机学院",
             json.dumps(["竞赛", "编程", "奖学金"], ensure_ascii=False),
             "demo-token-2026", now_iso()),
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
        if row:
            eid, created = row["id"], False
        else:
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
        c.execute(
            "INSERT OR REPLACE INTO user_events(user_id,event_id,relevance,reasons,created_at) VALUES(?,?,?,?,COALESCE((SELECT created_at FROM user_events WHERE user_id=? AND event_id=?),?))",
            (user_id, eid, relevance, json.dumps(reasons or [], ensure_ascii=False), user_id, eid, now_iso()),
        )
    return eid, created


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
               WHERE ue.user_id=? AND e.status='active'
               ORDER BY COALESCE(e.deadline_end, '9999') ASC""",
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
