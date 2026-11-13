"""Nudge 后端入口：FastAPI + 静态单页，一条命令就能跑。

    uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import hmac
import os
import subprocess
import sys
from datetime import date, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .agents import extractor, llm, matcher, planner, verifier
from .auth import admin_router, current_user, require_admin, router as auth_router
from .config import BASE_DIR
from .models import EventCreate, ExtractRequest
from .services import ics, mailer
from .services.seed import SAMPLES

app = FastAPI(title="Nudge · 校园截止管家", version="1.1.1")
STATIC_DIR = BASE_DIR / "app" / "static"

db.init()
# 部署到新机器时，环境变量里的 refresh token 会在启动时落进本机数据库
mailer.ensure_token()
app.include_router(auth_router)
app.include_router(admin_router)


class SettingsUpdate(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    clear_key: bool = False


def _public_settings(user_id: str) -> dict[str, Any]:
    base, model, key = llm.current(user_id)
    return {
        "base_url": base,
        "model": model,
        "has_key": bool(key),
        "key_hint": ("****" + key[-4:]) if len(key) >= 4 else ("****" if key else ""),
        "mode": llm.mode(user_id) or "auto",
        "available": llm.available(user_id),
    }


def _decorate(event: dict[str, Any]) -> dict[str, Any]:
    event["days_left"] = planner.days_left(event)
    event["urgency"] = planner.urgency(event)
    event["checklist"] = planner.build_checklist(event)
    event["reminders"] = planner.build_reminders(event)
    event["done"] = bool(event.get("done_at"))
    return event


def _commit() -> str:
    """线上是哪个 commit，一眼可查（答辩演示用）。"""
    try:
        done = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR.parent,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=10)
        return done.stdout.strip() if done.returncode == 0 else ""
    except Exception:
        return ""


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "llm": llm.available(),
        "mode": llm.mode() or "auto",
        "model": llm.current_model(),
        "llm_error": llm.last_error(),
        # graph / dev / unconfigured：一眼看出验证码是真发信还是开发模式
        "mail": mailer.status()["mode"],
        "commit": _commit(),
        "time": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/settings")
def api_settings(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return _public_settings(user["id"])


@app.post("/api/settings")
def api_save_settings(body: SettingsUpdate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    values: dict[str, str] = {}
    if body.base_url.strip():
        values["base_url"] = body.base_url.strip().rstrip("/")
    if body.model.strip():
        values["model"] = body.model.strip()
    current_base, _, current_key = llm.current(user["id"])
    has_key = bool(current_key) or bool(body.api_key.strip())
    if body.clear_key:
        values["api_key"] = ""
        values["llm_mode"] = "auto"
    elif body.api_key.strip():
        values["api_key"] = body.api_key.strip()
    # 在「模型设置」里点保存 = 当前用户要用模型
    values["llm_mode"] = "model" if has_key and not body.clear_key else "auto"
    if values:
        db.save_user_settings(user["id"], values)
    return _public_settings(user["id"])


@app.get("/api/llm-test")
def api_llm_test(kind: str = Query("chat", pattern="^(chat|models)$"),
                 user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """真发一次最小请求，把状态码与报错原文摊开——排查「为什么没调到模型」。"""
    result = llm.probe(kind=kind, user_id=user["id"])
    result["mode"] = llm.mode(user["id"]) or "auto"
    return result


@app.post("/api/extract")
def api_extract(req: ExtractRequest, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if len(req.text.strip()) < 10:
        raise HTTPException(400, "文本太短，粘贴一段完整通知再来")
    anchor = date.today()
    if req.published_at:
        try:
            anchor = datetime.fromisoformat(req.published_at).date()
        except ValueError:
            pass
    draft = extractor.extract(req.text, anchor=anchor, user_id=user["id"])
    draft.source.type = req.source_type  # type: ignore[assignment]
    draft.source.url = req.url
    draft = verifier.verify(req.text, draft)
    relevance, reasons = matcher.match(draft, user)
    return {
        "draft": draft.model_dump(),
        "relevance": relevance,
        "reasons": reasons,
        "checklist": planner.build_checklist(draft),
        "preview_urgency": planner.urgency({"deadline_end": draft.deadline.end}),
    }


@app.post("/api/events")
def api_create(body: EventCreate, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    draft = body.draft
    relevance, reasons = matcher.match(draft, user)
    event_id, created = db.save_event(draft, user["id"], relevance, reasons)
    return {"id": event_id, "created": created}


@app.get("/api/events")
def api_events(user: dict[str, Any] = Depends(current_user)) -> list[dict[str, Any]]:
    return [_decorate(e) for e in db.list_events(user["id"])]


@app.post("/api/events/{event_id}/done")
def api_done(event_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    db.mark_done(user["id"], event_id)
    return {"ok": True}


@app.post("/api/events/{event_id}/undone")
def api_undone(event_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    db.mark_active(user["id"], event_id)
    return {"ok": True}


@app.delete("/api/events/{event_id}")
def api_delete_event(event_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if not db.delete_event(user["id"], event_id):
        raise HTTPException(404, "事件不存在")
    return {"ok": True}


@app.get("/api/dashboard")
def api_dashboard(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    user_id = user["id"]
    events = [_decorate(e) for e in db.list_events(user_id)]
    active = [e for e in events if not e.get("done_at")]
    upcoming = [e for e in active if (e["days_left"] is None or e["days_left"] >= 0)]
    urgent = [e for e in upcoming if e["days_left"] is not None and 0 <= e["days_left"] <= 7]
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
        "events": events,
        "active_count": len(active),
        "conflicts": conflicts,
        "brief": planner.weekly_brief(active, user),
        "feedback": db.feedback_stats(user_id),
    }


@app.get("/api/weekly")
def api_weekly(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    active = [e for e in db.list_events(user["id"]) if not e.get("done_at")]
    return planner.weekly_brief(active, user)


@app.get("/api/calendar/{token}.ics", response_class=PlainTextResponse)
def api_calendar(token: str) -> PlainTextResponse:
    user = db.get_user_by_token(token)
    if not user:
        raise HTTPException(403, "日历订阅链接无效")
    active = [e for e in db.list_events(user["id"]) if not e.get("done_at")]
    body = ics.build_calendar(active, name="Nudge · " + (user.get("name") or "我的截止"))
    return PlainTextResponse(body, media_type="text/calendar; charset=utf-8",
                             headers={"Content-Disposition": 'inline; filename="nudge.ics"'})


@app.post("/api/feedback")
def api_feedback(event_id: str, kind: str = "useful",
                 user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if kind not in ("useful", "not_relevant", "wrong_deadline"):
        raise HTTPException(400, "未知反馈类型")
    db.add_feedback(user["id"], event_id, kind)
    return {"ok": True}


@app.get("/api/samples")
def api_samples() -> list[dict[str, str]]:
    return SAMPLES


@app.post("/api/seed")
def api_seed(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    added = 0
    for s in SAMPLES:
        draft = extractor.extract(s["text"], user_id=user["id"])
        draft = verifier.verify(s["text"], draft)
        rel, reasons = matcher.match(draft, user)
        _, created = db.save_event(draft, user["id"], rel, reasons)
        added += 1 if created else 0
    return {"ok": True, "added": added, "total": len(SAMPLES)}


# ---- 部署钩子：GitHub Actions 推送后调用，拉代码 + 装依赖 + 重载 ----
DEPLOY_TOKEN = os.getenv("NUDGE_DEPLOY_TOKEN", "").strip()
REPO_DIR = BASE_DIR.parent


@app.post("/api/deploy")
def api_deploy(x_deploy_token: str = Header(""), token: str = Query("")) -> dict[str, Any]:
    """CI 用：万一失败要能在日志里看到原始报错，所以不用 shell，逐条 git 执行。"""
    if not DEPLOY_TOKEN:
        raise HTTPException(404, "deploy disabled")
    if not hmac.compare_digest(x_deploy_token or token, DEPLOY_TOKEN):
        raise HTTPException(403, "bad deploy token")
    if not (REPO_DIR / ".git").exists():
        raise HTTPException(400, "not a git checkout")

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)

    before = git("rev-parse", "--short", "HEAD").stdout.strip()
    for args in (("fetch", "--depth=1", "origin", "main"), ("reset", "--hard", "origin/main")):
        done = git(*args)
        if done.returncode != 0:
            detail = (done.stderr or done.stdout).strip()[-300:]
            raise HTTPException(500, "git " + " ".join(args) + " 失败: " + detail)
    after = git("rev-parse", "--short", "HEAD").stdout.strip()

    # 依赖只在 requirements.txt 真变了才装：PythonAnywhere 免费版 web app 进程拉 PyPI
    # 会偶发 "Network is unreachable"，而每次部署都装一遍纯属浪费时间。
    # NUDGE_DEPLOY_PIP=1 强制装，=0 强制跳过。
    pip_note = "skipped"
    req = REPO_DIR / "pythonanywhere" / "requirements.txt"
    forced = os.getenv("NUDGE_DEPLOY_PIP", "").strip().lower()
    changed = False
    if before and after and before != after:
        diff = git("diff", "--name-only", before, after).stdout
        changed = any(line.strip().endswith("requirements.txt") for line in diff.splitlines())
    want_pip = changed if forced != "1" and forced != "0" else forced == "1"
    if want_pip and req.exists():
        install = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                                 cwd=REPO_DIR, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=300)
        pip_note = "ok" if install.returncode == 0 else (install.stderr or install.stdout).strip()[-200:]

    # 重载：线上启动脚本带 --reload --reload-dir backend，git reset 改了文件后 uvicorn
    # 会自动重启 worker，不需要额外的重启调用。
    # 试过用 PythonAnywhere API 手动 reload，免费账号的 custom-command 应用返回
    # 403 "You do not have permission to perform this action."，所以那条路放弃了。
    return {"ok": True, "before": before, "after": after, "pip": pip_note,
            "reload": "uvicorn-reload"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app")
def app_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
