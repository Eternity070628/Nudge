# -*- coding: utf-8 -*-
"""Nudge 抽取质量评测：对 eval_set.json 跑完整 extract→verify，输出字段准确率。

用法：python eval/run_eval.py   （在项目根目录执行）
输出：终端表格 + eval/report.md（可直接贴进答辩 PPT）
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents import extractor, verifier  # noqa: E402

CASES = json.loads((ROOT / "eval" / "eval_set.json").read_text(encoding="utf-8"))

CAT_MAP = {"竞赛": "competition", "奖学金": "scholarship", "讲座": "lecture",
           "考试": "exam", "办事": "affairs", "活动": "activity", "其他": "other"}


def parse(dt: str | None):
    return datetime.fromisoformat(dt) if dt else None


def main() -> int:
    rows = []
    exact = near = cat_ok = ch_ok = 0
    for c in CASES:
        exp = c["expect"]
        draft = verifier.verify(c["text"], extractor.extract(c["text"]))
        got = parse(draft.deadline.end)
        want = parse(exp["deadline_end"])
        same = got is not None and want is not None and got == want
        close = (not same) and got is not None and want is not None and abs((got - want).total_seconds()) <= 86400
        c_ok = draft.category == CAT_MAP.get(exp["category"], exp["category"])
        s_ok = draft.submission.channel == exp["channel"]
        exact += same
        near += close
        cat_ok += c_ok
        ch_ok += s_ok
        rows.append((c["id"], c["label"], "✓" if same else ("±" if close else "✗"),
                     exp["deadline_end"], draft.deadline.end or "-", c_ok, s_ok,
                     round(draft.overall_confidence, 2)))

    n = len(CASES)
    lines = ["| # | 用例 | 截止 | 期望 | 抽取 | 类别 | 渠道 | 置信度 |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" %
                     (r[0], r[1], r[2], r[3], r[4], "✓" if r[5] else "✗", "✓" if r[6] else "✗", r[7]))
    summary = [
        "",
        "样本数：%d" % n,
        "截止时间完全正确：%d/%d = %.0f%%" % (exact, n, exact / n * 100),
        "截止时间误差≤1天：%d/%d" % (exact + near, n),
        "类别正确：%d/%d = %.0f%%" % (cat_ok, n, cat_ok / n * 100),
        "提交渠道正确：%d/%d = %.0f%%" % (ch_ok, n, ch_ok / n * 100),
    ]
    out = "\n".join(lines + summary) + "\n"
    print(out)
    (ROOT / "eval" / "report.md").write_text("# Nudge 抽取评测报告\n\n" + out, encoding="utf-8")
    return 0 if exact == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
