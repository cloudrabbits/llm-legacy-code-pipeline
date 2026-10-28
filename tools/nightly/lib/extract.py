#!/usr/bin/env python3
"""从模型原始输出中抽取：① 文档正文 ② 状态 JSON（写交接卡）③ 事实条目（入库）。

模式：
  file    --raw <stdout> --out <目标路径> [--force]  抽取正文并原子写盘（由调用方先落 tmp）
  summary --raw <stdout> --handoff <文件>             抽取 JSON + open_questions 写交接卡
  facts   --raw <stdout> --task T01 --night 3         输出事实条目 JSON 行，供 db.py fact-upsert
"""
import argparse
import json
import os
import re
import subprocess
import sys

FACT_RE = re.compile(r"^-\s+([^\s:|]+\.(?:java|jsp|sql|xml|properties)):(\d+)\s*\|\s*(.+)$")
JSON_RE = re.compile(r"\{[^{}]*\"status\"[^{}]*\}")


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def last_json(txt):
    for c in reversed(JSON_RE.findall(txt)):
        try:
            return json.loads(c)
        except Exception:
            continue
    return None


DIFF_RE = re.compile(r"```diff\n(.*?)\n```", re.S)


def diff_of(txt):
    """取 ```diff 围栏内容（补丁类产物会被模型包在 Markdown 里，必须剥离才可用）"""
    m = DIFF_RE.findall(txt)
    return max(m, key=len).strip() if m else ""


def body_of(txt):
    """优先取 ```markdown 代码块，其次整体（去掉末尾 JSON 行）"""
    m = re.findall(r"```(?:markdown|md)?\n(.*?)```", txt, re.S)
    if m:
        cand = max(m, key=len)
        if len(cand) > 200:
            return cand
    lines = [l for l in txt.splitlines() if not JSON_RE.fullmatch(l.strip())]
    return "\n".join(lines).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["file", "summary", "facts"])
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--handoff", default="")
    ap.add_argument("--task", default="")
    ap.add_argument("--night", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--since", type=float, default=0,
                    help="本次分片开始时间戳；文件 mtime 早于它则视为旧产物，必须覆盖")
    a = ap.parse_args()

    txt = read(a.raw)

    if a.mode == "file":
        # 工具模式：模型已写文件且非空、并且是本次新写的 → 保留；否则覆盖。
        # （实测坑：产物回传到源项目后，下次 rsync 会把上一次的垃圾产物同步回来，
        #   若只判"非空"，会永久保留旧内容，验收永远拿旧文件判定。）
        fresh = False
        if a.out and os.path.exists(a.out) and os.path.getsize(a.out) > 0:
            fresh = os.path.getmtime(a.out) >= (a.since - 2) if a.since else True
        if (not a.force) and fresh:
            print(json.dumps({"written": a.out, "source": "tool"}))
            return
        # .diff/.patch 目标：优先用围栏里的纯 diff，避免 Markdown 前言让 git apply 判为 corrupt
        body = ""
        if a.out.endswith((".diff", ".patch")):
            body = diff_of(txt)
        if not body:
            body = body_of(txt).strip()
        if not body:
            print(json.dumps({"written": None, "error": "empty body"}))
            sys.exit(1)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        tmp = a.out + ".new"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        os.replace(tmp, a.out)
        print(json.dumps({"written": a.out, "source": "stdout", "chars": len(body)}))

    elif a.mode == "summary":
        j = last_json(txt) or {}
        os.makedirs(os.path.dirname(os.path.abspath(a.handoff)) or ".", exist_ok=True)
        with open(a.handoff, "w", encoding="utf-8") as f:
            f.write(f"# 交接卡 {a.task}\n\n")
            f.write(f"- status: {j.get('status', 'unknown')}\n")
            f.write(f"- summary: {j.get('summary', '')}\n")
            f.write(f"- facts: {j.get('facts', 0)}\n")
            f.write("- open_questions:\n")
            for q in j.get("open_questions", []) or []:
                f.write(f"  - {q}\n")
        print(json.dumps({"handoff": a.handoff, "status": j.get("status", "unknown")}))

    else:
        out = []
        for line in txt.splitlines():
            m = FACT_RE.match(line.strip())
            if m:
                f, ln, claim = m.group(1), m.group(2), m.group(3).strip()
                out.append({"pk": f"{f}:{ln}:{a.task}", "claim": claim[:300], "evidence": f"{f}:{ln}"})
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
