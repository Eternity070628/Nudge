"""Planner Agent：把事件变成"什么时候做什么"。

刻意不用大模型：这个 Agent 是状态机 + 规则。日期算术、去重、排序、冲突检测
必须是确定性的，否则用户没法信任日历。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..config import LOAD_WARN_THRESHOLD, REMIND_DAYS
from ..models import EventDraft

CATEGORY_LABEL = {
    "competition": "竞赛", "scholarship": "奖学金", "lecture": "讲座",
    "exam": "考试", "affairs": "办事", "other": "其他",
}


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def days_left(event: dict[str, Any], now: datetime | None = None) -> int | None:
    end = parse_dt(event.get("deadline_end"))
    if not end:
        return None
    now = now or datetime.now()
    return (end.date() - now.date()).days


def urgency(event: dict[str, Any]) -> str:
    d = days_left(event)
    if d is None:
        return "unknown"
    if d < 0:
        return "overdue"
    if d == 0:
        return "today"
    if d <= 3:
        return "urgent"
    if d <= 7:
        return "soon"
    return "later"


def build_checklist(draft_or_event: Any) -> list[dict[str, Any]]:
    materials = getattr(draft_or_event, "materials", None)
    if materials is None:
        materials = draft_or_event.get("materials") or []
    items = []
    for m in materials:
        name = getattr(m, "name", None) or (m.get("name") if isinstance(m, dict) else str(m))
        items.append({"name": name, "done": False})
    sub = getattr(draft_or_event, "submission", None) or draft_or_event.get("submission") or {}
    channel = getattr(sub, "channel", None) or sub.get("channel")
    if channel == "email":
        items.append({"name": "把材料打包发到指定邮箱", "done": False})
    elif channel == "web":
        items.append({"name": "在系统里完成线上提交", "done": False})
    elif channel == "offline":
        items.append({"name": "打印并盖章，送到指定地点", "done": False})
    return items


def build_reminders(event: dict[str, Any], now: datetime | None = None) -> list[dict[str, Any]]:
    end = parse_dt(event.get("deadline_end"))
    if not end:
        return []
    now = now or datetime.now()
    out = []
    for d in REMIND_DAYS:
        fire = end - timedelta(days=d)
        if fire > now:
            out.append({
                "at": fire.replace(hour=9, minute=0).isoformat(timespec="minutes"),
                "days_before": d,
                "text": f"还有 {d} 天：{event.get('title')}",
            })
    fire = end - timedelta(hours=12)
    if fire > now:
        out.append({"at": fire.isoformat(timespec="minutes"), "days_before": 0,
                    "text": f"明天截止：{event.get('title')}"})
    return out


def detect_conflicts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一天的截止/必须到场 ≥2 个 → 负载过高。"""
    by_day: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        end = parse_dt(e.get("deadline_end"))
        if end:
            by_day.setdefault(end.date().isoformat(), []).append(e)
    out = []
    for day, items in sorted(by_day.items()):
        if len(items) >= LOAD_WARN_THRESHOLD:
            out.append({
                "date": day,
                "count": len(items),
                "titles": [i.get("title") for i in items],
                "advice": f"{day} 有 {len(items)} 件事撞在一起，建议最晚提前 3 天完成 1 件。",
            })
    return out


def weekly_brief(events: list[dict[str, Any]], user: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now()
    week_end = now + timedelta(days=7)
    this_week, later = [], []
    for e in events:
        end = parse_dt(e.get("deadline_end"))
        if not end:
            continue
        (this_week if end <= week_end else later).append(e)
    lines = []
    if this_week:
        lines.append(f"本周你有 {len(this_week)} 个截止，最近的是「{this_week[0]['title']}」（{urgency(this_week[0])}）。")
    else:
        lines.append("本周没有硬性截止，适合推进长期事项。")
    if later:
        lines.append(f"下一周有 {len(later)} 个，其中「{later[0]['title']}」建议本周先准备材料。")
    return {
        "week_start": now.date().isoformat(),
        "count": len(this_week),
        "events": [{"id": e["id"], "title": e["title"], "deadline_end": e["deadline_end"],
                    "urgency": urgency(e)} for e in this_week],
        "brief": " ".join(lines),
        "generated_at": now.isoformat(timespec="seconds"),
    }
