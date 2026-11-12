"""Nudge 后端入口：FastAPI + 静态单页，一条命令就能跑。

    uvicorn app.main:app --port 8000
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .agents import extractor, matcher, planner, verifier
from .config import BASE_DIR
from .models import EventCreate, ExtractRequest
from .services import ics
from .services.seed import SAMPLES

app = FastAPI(title="Nudge · 校园截止管家", version="0.1.0")
STATIC_DIR = BASE_DIR / "app" / "static"

db.init()


def _decorate(event: dict[str, Any]) -> dict[str, Any]:
    event["days_left"] = planner.days_left(event)
    event["urgency"] = planner.urgency(event)
    event["checklist"] = planner.build_checklist(event)
    event["reminders"] = planner.build_reminders(event)
    return event


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "llm": extractor.llm.available(), "time": datetime.now().isoformat(timespec="seconds")}


@app.post("/api/extract")
def api_extract(req: ExtractRequest) -> dict[str, Any]:
    if len(req.text.strip()) < 10:
        raise HTTPException(400, "文本太短，粘贴一段完整通知再来")
    anchor = date.today()
    if req.published_at:
        try:
            anchor = datetime.fromisoformat(req.published_at).date()
        except ValueError:
            pass
    draft = extractor.extract(req.text, anchor=anchor)
    draft.source.type = req.source_type  # type: ignore[assignment]
    draft.source.url = req.url
    draft = verifier.verify(req.text, draft)
    relevance, reasons = matcher.match(draft, db.get_user("u_demo") or {})
    return {
        "draft": draft.model_dump(),
        "relevance": relevance,
        "reasons": reasons,
        "checklist": planner.build_checklist(draft),
        "preview_urgency": planner.urgency({"deadline_end": draft.deadline.end}),
    }


@app.post("/api/events")
def api_create(body: EventCreate) -> dict[str, Any]:
    user = db.get_user(body.user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    draft = body.draft
    relevance, reasons = matcher.match(draft, user)
    event_id, created = db.save_event(draft, body.user_id, relevance, reasons)
    return {"id": event_id, "created": created}


@app.get("/api/events")
def api_events(user_id: str = "u_demo") -> list[dict[str, Any]]:
    return [_decorate(e) for e in db.list_events(user_id)]


@app.post("/api/events/{event_id}/done")
def api_done(event_id: str, user_id: str = "u_demo") -> dict[str, Any]:
    db.mark_done(user_id, event_id)
    return {"ok": True}


@app.get("/api/dashboard")
def api_dashboard(user_id: str = "u_demo") -> dict[str, Any]:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    events = [_decorate(e) for e in db.list_events(user_id)]
    upcoming = [e for e in events if (e["days_left"] is None or e["days_left"] >= 0)]
    urgent = [e for e in upcoming if e["days_left"] is not None and e["days_left"] <= 7]
    conflicts = planner.detect_conflicts(upcoming)
    total_materials = sum(len(e["checklist"]) for e in upcoming)
    return {
        "user": user,
        "stats": {
            "upcoming": len(upcoming),
            "urgent_7d": len(urgent),
            "materials": total_materials,
            "saved_minutes": len(events) * 12,
        },
        "events": upcoming,
        "conflicts": conflicts,
        "brief": planner.weekly_brief(events, user),
        "feedback": db.feedback_stats(user_id),
    }


@app.get("/api/weekly")
def api_weekly(user_id: str = "u_demo") -> dict[str, Any]:
    user = db.get_user(user_id) or {}
    return planner.weekly_brief(db.list_events(user_id), user)


@app.get("/api/calendar/{token}.ics", response_class=PlainTextResponse)
def api_calendar(token: str, user_id: str = Query("u_demo")) -> PlainTextResponse:
    user = db.get_user(user_id)
    if not user or user.get("token") != token:
        raise HTTPException(403, "日历订阅链接无效")
    body = ics.build_calendar(db.list_events(user_id), name="Nudge · " + (user.get("name") or "我的截止"))
    return PlainTextResponse(body, media_type="text/calendar; charset=utf-8",
                             headers={"Content-Disposition": 'inline; filename="nudge.ics"'})


@app.post("/api/feedback")
def api_feedback(event_id: str, kind: str = "useful", user_id: str = "u_demo") -> dict[str, Any]:
    if kind not in ("useful", "not_relevant", "wrong_deadline"):
        raise HTTPException(400, "未知反馈类型")
    db.add_feedback(user_id, event_id, kind)
    return {"ok": True}


@app.get("/api/samples")
def api_samples() -> list[dict[str, str]]:
    return SAMPLES


@app.post("/api/seed")
def api_seed(user_id: str = "u_demo") -> dict[str, Any]:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    added = 0
    for s in SAMPLES:
        draft = extractor.extract(s["text"])
        draft = verifier.verify(s["text"], draft)
        rel, reasons = matcher.match(draft, user)
        _, created = db.save_event(draft, user_id, rel, reasons)
        added += 1 if created else 0
    return {"ok": True, "added": added, "total": len(SAMPLES)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
