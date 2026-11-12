"""生成标准 .ics 日历：用户订阅一次，之后所有截止自动出现在手机日历里。

这是"真的有用"的分水岭——不用每天打开我们的 App。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _fold(line: str) -> str:
    # RFC5545：单行不超过 75 字节，中文按字节折行
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 73:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_calendar(events: list[dict[str, Any]], name: str = "Nudge 截止日历") -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Nudge//Campus Deadline//CN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(name), "X-WR-TIMEZONE:Asia/Shanghai",
    ]
    for e in events:
        end_raw = e.get("deadline_end")
        if not end_raw:
            continue
        end = datetime.fromisoformat(end_raw)
        start = end - timedelta(minutes=30)
        fmt = "%Y%m%dT%H%M%S"
        lines += [
            "BEGIN:VEVENT",
            "UID:" + e["id"] + "@nudge.study",
            "DTSTAMP:" + datetime.now().strftime(fmt),
            "DTSTART;TZID=Asia/Shanghai:" + start.strftime(fmt),
            "DTEND;TZID=Asia/Shanghai:" + end.strftime(fmt),
            "SUMMARY:" + _escape("⏰ " + (e.get("title") or "截止")),
            "DESCRIPTION:" + _escape((e.get("deadline_raw") or "") + " | Nudge 自动生成"),
            "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY",
            "DESCRIPTION:" + _escape("明天截止：" + (e.get("title") or "")), "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"
