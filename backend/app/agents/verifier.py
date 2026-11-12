"""Verifier Agent：逐字段回原文核对，决定"能不能直接信"。

这一步是反幻觉的关键：模型说有截止时间，就必须能在原文里指出那句话。
"""
from __future__ import annotations

from ..models import EventDraft

WEIGHTS = {
    "title": 0.12, "category": 0.08, "deadline": 0.34,
    "audience": 0.10, "materials": 0.22, "submission": 0.14,
}
REVIEW_THRESHOLD = 0.7


def _norm(s: str) -> str:
    return "".join(s.split())


def verify(text: str, draft: EventDraft) -> EventDraft:
    conf = dict(draft.confidence or {})
    norm_text = _norm(text)
    needs: list[str] = []
    warnings: list[str] = []

    for field, quote in list(draft.evidence.items()):
        if not quote:
            draft.evidence.pop(field, None)
            continue
        if _norm(quote)[:30] not in norm_text:
            # 证据找不到 → 该字段不可信
            conf[field] = min(conf.get(field, 0.5), 0.3)
            warnings.append(f"字段 {field} 的证据无法在原文中定位，已降级为待确认")
            draft.evidence.pop(field, None)

    if not draft.deadline.end:
        conf["deadline"] = min(conf.get("deadline", 0.2), 0.25)
        warnings.append("没有识别到截止时间，请手工确认")
    elif draft.deadline.confidence < 0.9:
        warnings.append("截止时间是相对时间/缺具体时刻，建议核对原始通知")

    if not draft.materials:
        if any(k in text for k in ("材料", "盖章", "盖章", "证明")):
            conf["materials"] = min(conf.get("materials", 0.3), 0.4)
            warnings.append("通知提到材料要求，但未能拆成清单")
        else:
            conf["materials"] = 0.2

    if not draft.title:
        conf["title"] = 0.3
        warnings.append("标题可能是首行截断，请确认")

    for field, w in WEIGHTS.items():
        if conf.get(field, 0.0) < REVIEW_THRESHOLD:
            needs.append(field)

    draft.confidence = {k: round(float(v), 2) for k, v in conf.items()}
    draft.overall_confidence = round(sum(conf.get(k, 0) * w for k, w in WEIGHTS.items()), 2)
    draft.needs_review = needs
    draft.warnings = warnings
    return draft
