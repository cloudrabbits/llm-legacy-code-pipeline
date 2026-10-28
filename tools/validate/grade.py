#!/usr/bin/env python3
"""金标准评分：分层准确率 / 引用真实率 / 陷阱拒答率。

用法：
  python3 grade.py --questions <corpus>/questions.json --answers results/armA --out results/armA.score.json
判定：
  L1/L2/L3：期望字符串（或其关键片段）出现在回答中即判对
  L4：期望"不存在"；命中否定词判对，出现伪造行号判错
"""
import argparse
import json
import os
import re

NEG = ("不存在", "未找到", "没有", "无此方法", "无法确认", "未确认", "未见", "不包含")
CITE = re.compile(r"([A-Za-z0-9_./\\-]+\.(?:java|jsp|sql|xml)):(\d+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True)
    ap.add_argument("--answers", required=True)
    ap.add_argument("--corpus", default="", help="语料根目录，用于校验引用行号是否真实")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    qs = json.load(open(a.questions, encoding="utf-8"))
    stat = {}
    cite_total = cite_ok = 0
    rows = []
    for q in qs:
        p = os.path.join(a.answers, f"{q['id']}.md")
        ans = ""
        if os.path.exists(p):
            ans = open(p, encoding="utf-8", errors="replace").read()
        hit = False
        if q["tier"] == "L4":
            hit = any(w in ans for w in NEG) and not re.search(r":(\d+)", ans)
        else:
            exp = str(q["expected"])
            hit = exp.lower() in ans.lower() or (
                isinstance(q["expected"], str) and q["expected"] in ans)
        s = stat.setdefault(q["tier"], {"n": 0, "hit": 0})
        s["n"] += 1
        s["hit"] += 1 if hit else 0

        for m in CITE.finditer(ans):
            cite_total += 1
            fp = m.group(1)
            if a.corpus:
                real = os.path.join(a.corpus, fp)
                if os.path.exists(real):
                    nl = sum(1 for _ in open(real, encoding="utf-8", errors="replace"))
                    if int(m.group(2)) <= max(1, nl):
                        cite_ok += 1
            else:
                cite_ok += 1  # 无语料时只统计格式合规
        rows.append({"id": q["id"], "tier": q["tier"], "hit": hit, "answered": bool(ans.strip())})

    out = {
        "accuracy": {k: round(v["hit"] / max(1, v["n"]), 3) for k, v in sorted(stat.items())},
        "counts": {k: v for k, v in sorted(stat.items())},
        "citation_valid_rate": round(cite_ok / max(1, cite_total), 3) if cite_total else None,
        "citations": cite_total,
        "rows": rows,
    }
    txt = json.dumps(out, ensure_ascii=False, indent=2)
    print(txt)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)


if __name__ == "__main__":
    main()
