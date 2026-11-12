"""Matcher Agent：这条通知跟我有没有关系？给出 0–1 的相关度和理由。

纯规则 + 词表，可解释、可复现；答辩现场能一句句讲清楚为什么。
"""
from __future__ import annotations

from typing import Any

from ..models import EventDraft

CATEGORY_INTEREST = {
    "competition": "竞赛", "scholarship": "奖学金", "lecture": "讲座",
    "exam": "考试", "affairs": "办事", "other": "",
}


def match(draft: EventDraft, user: dict[str, Any]) -> tuple[float, list[str]]:
    score, reasons = 0.3, []
    interests = user.get("interests") or []
    cat_word = CATEGORY_INTEREST.get(draft.category, "")

    if cat_word and any(cat_word in i or i in cat_word for i in interests):
        score += 0.25
        reasons.append(f"你的兴趣里有「{cat_word}」")

    grades = draft.audience.grades
    if grades:
        if user.get("grade") in grades:
            score += 0.25
            reasons.append(f"面向 {user.get('grade')}，正好覆盖你")
        elif not any(g in ("全体", "全校") for g in grades):
            score -= 0.15
            reasons.append(f"通知面向 {('/'.join(grades))}，与你所在年级不同")
    else:
        reasons.append("通知没有写明年级范围，默认全校可参加")

    colleges = draft.audience.colleges
    if colleges:
        if any(c[:2] in (user.get("major") or "") for c in colleges):
            score += 0.15
            reasons.append(f"面向 {('/'.join(colleges))}")
        else:
            score -= 0.2
            reasons.append(f"仅限 {('/'.join(colleges))}，你不在范围内")

    if draft.importance >= 4:
        score += 0.1
        reasons.append("重要性高（涉及学分/评优/国家级）")

    return round(max(0.0, min(1.0, score)), 2), reasons
