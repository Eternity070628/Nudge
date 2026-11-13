"""Extractor Agent：把一段通知文本变成结构化事件。

两种模式：
  1) 配了华为云 MaaS Key —— 让模型输出严格 JSON，规则负责兜底与证据校验；
  2) 没配 Key —— 纯规则抽取（正则 + 词表），离线可跑，保证演示不会翻车。

设计原则：抽不出来宁可留空 + needs_review，也不许猜。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from ..models import Audience, Deadline, EventDraft, Material, Source, Submission
from . import llm

CATEGORY_WORDS: dict[str, list[str]] = {
    "competition": ["大赛", "竞赛", "比赛", "挑战赛", "创新创业", "赛道"],
    "scholarship": ["奖学金", "助学金", "评优", "评奖", "荣誉称号"],
    "lecture": ["讲座", "报告会", "沙龙", "分享会", "论坛", "宣讲"],
    "exam": ["考试", "补考", "缓考", "四六级", "机考", "笔试"],
    "affairs": ["办理", "盖章", "材料提交", "学籍", "证明", "报销", "注册", "选课",
                "转专业", "缴费", "参保", "评教", "证明"],
    "activity": ["志愿服务", "献血", "公益活动", "社会实践"],
}

IMPORTANCE_WORDS = ["学分", "保研", "推免", "评优", "奖学金", "国家级", "一等奖", "必须", "强制"]

# 通知里常用「本部/西土城」指海淀校区，「昌平」指沙河校区。只在原文明确出现时判定。
CAMPUS_ALIASES: dict[str, list[str]] = {
    "haidian": ["海淀", "本部", "西土城"],
    "shahe": ["沙河", "昌平"],
    "hainan": ["海南"],
}
CAMPUS_LABELS = {"haidian": "海淀校区", "shahe": "沙河校区", "hainan": "海南校区", "unknown": "未识别"}

SENT_SPLIT = re.compile(r"[。；;！!？?\n]+")

DATE_TOKEN = r"(?:(?:\d{4}年)?\d{1,2}月\d{1,2}日(?:\s*\d{1,2}[:：]\d{2})?|\d{4}-\d{1,2}-\d{1,2}(?:[ T]\d{1,2}:\d{2})?)"
REL_TOKEN = r"(?:今天|明天|后天|本周[一二三四五六日天]|下周[一二三四五六日天]|本月\d{1,2}日|月底)"

DEADLINE_PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(?:截止时间|截止日期|报名截止|提交截止|申报截止|截至|截止)[^。；;\n]{0,12}?(" + DATE_TOKEN + r")"), 0.95),
    (re.compile(r"(?:报名|申请|提交|申报|投稿|评选|活动)(?:时间|日期|阶段)?[:：]?\s*(" + DATE_TOKEN
                + r")\s*(?:至|到|—|－|-|~|～|起至)\s*(" + DATE_TOKEN + r")"), 0.93),
    (re.compile(r"即日起至\s*(" + DATE_TOKEN + r")"), 0.9),
    (re.compile(r"(" + DATE_TOKEN + r")\s*(?:前|之前|截止|以前)"), 0.9),
    (re.compile(r"(?:请于|须于|务必于)\s*(" + DATE_TOKEN + r")"), 0.88),
    (re.compile(r"(?:截止|截至)[^。；;\n]{0,8}?(" + REL_TOKEN + r")"), 0.7),
    (re.compile(r"(?:活动时间|讲座时间|举办时间|会议时间|时间)[:：]\s*(" + DATE_TOKEN + r")"), 0.72),
    (re.compile(r"\b(\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2})\b"), 0.9),
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


def _evidence(text: str, needle: str) -> str:
    """返回包含 needle 的整句，作为"可点回原文"的证据。"""
    if not needle:
        return ""
    for s in _sentences(text):
        if needle in s:
            return s[:160]
    return needle[:160]


def _parse_date_token(tok: str, anchor: date) -> datetime | None:
    tok = tok.replace("：", ":").strip()
    m = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日\s*(?:(\d{1,2}):(\d{2}))?", tok)
    if m:
        year = int(m.group(1)) if m.group(1) else anchor.year
        month, day = int(m.group(2)), int(m.group(3))
        hour = int(m.group(4)) if m.group(4) else 23
        minute = int(m.group(5)) if m.group(5) else 59
        rollover = False
        if hour >= 24:          # 通知里常写"24:00"，实际是次日零点
            hour, rollover = 0, True
        try:
            dt = datetime(year, month, day, hour, minute)
            if rollover:
                dt = dt + timedelta(days=1)
        except ValueError:
            return None
        # 11 月看到"1 月 5 日"，通常是明年
        if not m.group(1) and dt.date() < anchor - timedelta(days=60):
            try:
                dt = dt.replace(year=year + 1)
            except ValueError:
                return None
        return dt
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", tok)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            int(m.group(4) or 23), int(m.group(5) or 59))
        except ValueError:
            return None
    return _parse_relative(tok, anchor)


def _parse_relative(tok: str, anchor: date) -> datetime | None:
    base = datetime(anchor.year, anchor.month, anchor.day, 23, 59)
    if "今天" in tok:
        return base
    if "明天" in tok:
        return base + timedelta(days=1)
    if "后天" in tok:
        return base + timedelta(days=2)
    if "月底" in tok:
        nxt = (base.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    m = re.search(r"本月(\d{1,2})日", tok)
    if m:
        try:
            return base.replace(day=int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"(本|下)周([一二三四五六日天])", tok)
    if m:
        idx = "一二三四五六日".find(m.group(2))
        if idx < 0:
            idx = 6
        monday = anchor - timedelta(days=anchor.weekday())
        shift = 7 if m.group(1) == "下" else 0
        return datetime.combine(monday + timedelta(days=idx + shift), datetime.min.time()).replace(hour=23, minute=59)
    return None


def _find_deadline(text: str, anchor: date) -> tuple[Deadline, str]:
    best: tuple[float, str, datetime] | None = None
    for pattern, conf in DEADLINE_PATTERNS:
        for m in pattern.finditer(text):
            tok = m.group(m.lastindex or 1)   # 区间"报名时间：A 至 B"取后者作为截止
            dt = _parse_date_token(tok, anchor)
            if not dt:
                continue
            if best is None or conf > best[0]:
                best = (conf, tok, dt)
        if best and best[0] >= 0.9:
            break
    if not best:
        return Deadline(), ""
    conf, tok, dt = best
    if not re.search(r"\d{1,2}[:：]\d{2}", tok):
        conf -= 0.08
    d = Deadline(start=dt.replace(hour=0, minute=0).isoformat(),
                 end=dt.isoformat(), raw=tok, confidence=round(conf, 2))
    return d, _evidence(text, tok)


def campus_label(value: str | None) -> str:
    return CAMPUS_LABELS.get(value or "", CAMPUS_LABELS["unknown"])


def _detect_campus(text: str) -> str:
    """按别称出现次数投票；原文没写校区就返回 unknown，绝不按常识猜。"""
    hits = {key: sum(text.count(alias) for alias in aliases) for key, aliases in CAMPUS_ALIASES.items()}
    best = max(hits, key=lambda key: hits[key])
    return best if hits[best] else "unknown"


def _find_title(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""
    first = lines[0]
    first = re.sub(r"^[【\[](.+?)[】\]]\s*", r"\1｜", first).strip()
    first = re.sub(r"(?:的)?(?:通知|公告|公示)$", "", first).strip()
    if len(first) > 46:
        first = first[:44] + "…"
    return first


def _find_category(text: str) -> tuple[str, float]:
    scores = {k: sum(text.count(w) for w in words) for k, words in CATEGORY_WORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "other", 0.45
    return best, 0.85


COLLEGE_STOP = ("跨", "各", "加盖", "登录", "请", "需", "至", "交", "的", "和", "与", "及",
                "或", "在", "将", "于", "示范性", "教务", "所在", "本", "该", "凡", "由")


def _clean_colleges(text: str) -> list[str]:
    out: list[str] = []
    for c in re.findall(r"[\u4e00-\u9fa5]{2,10}(?:学院|系)", text):
        if any(w in c for w in COLLEGE_STOP):
            continue
        if c not in out:
            out.append(c)
    return out[:3]


def _find_audience(text: str) -> tuple[Audience, str]:
    """只在"对象/面向"句子里找范围，避免把'跨学院''请登录教务系统'当成院系。"""
    raw = ""
    for s in _sentences(text):
        if any(w in s for w in ("对象", "面向", "申请资格", "申报条件", "参赛资格")):
            raw = s[:140]
            break
    scope_text = raw if raw else text
    grades = sorted(set(re.findall(r"20\d{2}级|大[一二三四]|研[一二三]", scope_text)))
    colleges = _clean_colleges(scope_text)
    return Audience(grades=grades[:4], majors=[], colleges=colleges, raw=raw), raw


MATERIAL_KEYS = ("提交材料", "材料清单", "需提交", "需提供", "申报材料", "报名材料",
                 "包括以下", "准备以下", "材料包括", "需准备")
ITEM_LINE = re.compile(r"(?:^|\n)\s*(?:[一二三四五六七八九十]+[、.]|\d+[、.）)]|[（(]\d+[)）]|[①②③④⑤⑥⑦⑧⑨⑩])\s*([^\n；;。]{2,40})")


def _find_materials(text: str) -> tuple[list[Material], str]:
    for key in MATERIAL_KEYS:
        pos = text.find(key)
        if pos < 0:
            continue
        window = text[pos: pos + 600]
        items = [m.group(1).strip(" ：:，,") for m in ITEM_LINE.finditer(window)]
        skip = ("提交方式", "提交时间", "提交地点", "报名方式", "联系方式", "注意", "说明",
                "要求", "地点", "时间", "截止", "联系人", "邮件主题", "备注", "其他",
                "发送至", "同时将", "请将", "电子版", "纸质")
        items = [i for i in items if 2 <= len(i) <= 40 and not i.startswith(skip)][:8]
        if items:
            return [Material(name=i) for i in items], _evidence(text, key)
        # 无编号时，取关键词后一小段
        tail = re.split(r"[。\n]", window[len(key):])[0].strip(" ：:，,")
        if 2 <= len(tail) <= 80:
            return [Material(name=tail)], _evidence(text, key)
    return [], ""


def _find_submission(text: str) -> tuple[Submission, str]:
    em = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    url = re.search(r"https?://[^\s，。；;）)]+", text)
    sub = Submission()
    for s in _sentences(text):
        if any(w in s for w in ("提交至", "交至", "送至", "地点", "现场", "线下",
                                "携带", "窗口", "当面", "到行政楼", "到学院楼", "一站式")):
            sub.channel = "offline"
            sub.location = s[:100]
            break
    if em:
        sub.channel, sub.email = "email", em.group(0)
    if url:
        sub.url = url.group(0)
        if not em and sub.channel != "offline":
            sub.channel = "web"
    if sub.channel == "unknown" and any(w in text for w in
                                       ("在线提交", "系统提交", "网上报名", "系统填报", "登录", "线上")):
        sub.channel = "web"
    ev = _evidence(text, em.group(0)) if em else (_evidence(text, url.group(0)) if url else "")
    return sub, ev


def _importance(text: str, category: str) -> int:
    score = 2
    if category in ("competition", "scholarship", "exam"):
        score += 1
    score += sum(1 for w in IMPORTANCE_WORDS if w in text)
    return max(1, min(5, score))


def rule_extract(text: str, anchor: date) -> tuple[EventDraft, dict[str, float]]:
    deadline, ev_deadline = _find_deadline(text, anchor)
    category, c_conf = _find_category(text)
    audience, ev_aud = _find_audience(text)
    materials, ev_mat = _find_materials(text)
    submission, ev_sub = _find_submission(text)
    title = _find_title(text)

    conf = {
        "title": 0.9 if len(title) >= 6 else 0.55,
        "category": c_conf,
        "deadline": deadline.confidence,
        "audience": 0.8 if (audience.grades or audience.colleges or audience.raw) else 0.4,
        "materials": 0.85 if materials else (0.3 if any(k in text for k in MATERIAL_KEYS) else 0.2),
        "submission": 0.88 if submission.channel != "unknown" else 0.35,
    }
    draft = EventDraft(
        title=title,
        category=category,  # type: ignore[arg-type]
        deadline=deadline,
        audience=audience,
        materials=materials,
        submission=submission,
        evidence={k: v for k, v in {
            "deadline": ev_deadline, "audience": ev_aud,
            "materials": ev_mat, "submission": ev_sub,
        }.items() if v},
        importance=_importance(text, category),
        confidence=conf,
    )
    return draft, conf


LLM_SYSTEM = """你是校园通知结构化助手。只输出 JSON，不要解释。
字段：title, category(competition|scholarship|lecture|affairs|exam|other),
deadline.{raw,end}, audience.{raw,grades,colleges}, materials[{name}],
submission.{channel(web|email|offline|unknown),url,email,location}, evidence{字段名:原文片段}。
规则：所有日期转 ISO8601（Asia/Shanghai）；evidence 必须是原文逐字片段；不确定就留空，禁止编造。"""


def llm_extract(text: str, anchor: date, user_id: str | None = None) -> EventDraft | None:
    out = llm.chat(LLM_SYSTEM, text[:6000], user_id=user_id)
    if not out:
        return None
    try:
        start, end = out.find("{"), out.rfind("}")
        data = json.loads(out[start:end + 1])
    except Exception:
        return None

    draft = EventDraft()
    draft.title = str(data.get("title", ""))[:80]
    cat = str(data.get("category", "other"))
    draft.category = cat if cat in CATEGORY_WORDS or cat == "other" else "other"  # type: ignore
    dl = data.get("deadline") or {}
    raw = str(dl.get("raw", ""))
    try:
        dt = datetime.fromisoformat(str(dl.get("end")).replace("Z", "+00:00").replace("+08:00", ""))
        draft.deadline = Deadline(start=dt.replace(hour=0, minute=0).isoformat(), end=dt.isoformat(), raw=raw or str(dl.get("end")))
    except Exception:
        d, ev = _find_deadline(text, anchor)
        draft.deadline = d
    au = data.get("audience") or {}
    draft.audience = Audience(grades=[str(x) for x in au.get("grades", [])][:4],
                              colleges=[str(x) for x in au.get("colleges", [])][:3],
                              raw=str(au.get("raw", ""))[:120])
    draft.materials = [Material(name=str(m.get("name", ""))[:40])
                       for m in (data.get("materials") or []) if str(m.get("name", "")).strip()][:8]
    sb = data.get("submission") or {}
    ch = str(sb.get("channel", "unknown"))
    draft.submission = Submission(channel=ch if ch in ("web", "email", "offline") else "unknown",  # type: ignore
                                  url=str(sb.get("url", ""))[:200], email=str(sb.get("email", ""))[:80],
                                  location=str(sb.get("location", ""))[:100])
    ev = {str(k): str(v)[:160] for k, v in (data.get("evidence") or {}).items()}
    draft.evidence = ev
    return draft


def extract(text: str, anchor: date | None = None, user_id: str | None = None,
            default_campus: str | None = None) -> EventDraft:
    text = text.strip()
    anchor = anchor or date.today()
    draft, conf = rule_extract(text, anchor)
    draft.source = Source(type="text")

    if llm.available(user_id):
        llm_draft = llm_extract(text, anchor, user_id)
        if llm_draft:
            # 只接受能在原文里找到证据的字段，防止幻觉
            if llm_draft.title:
                draft.title = llm_draft.title
            if llm_draft.deadline.end:
                draft.deadline = llm_draft.deadline
            if llm_draft.materials:
                draft.materials = llm_draft.materials
            if llm_draft.submission.channel != "unknown":
                draft.submission = llm_draft.submission
            if llm_draft.audience.raw or llm_draft.audience.grades:
                draft.audience = llm_draft.audience
            draft.evidence.update({k: v for k, v in llm_draft.evidence.items() if v and v[:8] in text})

    # 截止校验同时看校区：通知写了就以通知为准，没写才用用户默认校区。
    explicit_campus = _detect_campus(text)
    if explicit_campus != "unknown":
        draft.campus = explicit_campus  # type: ignore[assignment]
        if default_campus and default_campus != explicit_campus:
            note = (f"通知写的是{campus_label(explicit_campus)}，"
                    f"与你设置的默认校区（{campus_label(default_campus)}）不同，请确认")
            if note not in draft.warnings:
                draft.warnings.append(note)
            if "campus" not in draft.needs_review:
                draft.needs_review.append("campus")
    elif default_campus:
        draft.campus = default_campus  # type: ignore[assignment]

    for field in ("deadline", "materials", "audience", "submission"):
        key = "deadline" if field == "deadline" else field
        draft.confidence[key] = draft.confidence.get(key, 0.5)
    return draft
