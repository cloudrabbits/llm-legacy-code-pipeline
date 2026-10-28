#!/usr/bin/env python3
"""把模型输出中的事实条目（`- 文件:行号 | 结论`）批量 upsert 进 fact 表（幂等）。"""
import argparse
import json
import os
import sqlite3
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--night", type=int, default=0)
    a = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from extract import FACT_RE  # 复用同一正则

    with open(a.raw, encoding="utf-8", errors="replace") as f:
        txt = f.read()

    rows = []
    for line in txt.splitlines():
        m = FACT_RE.match(line.strip())
        if m:
            f_, ln, claim = m.group(1), m.group(2), m.group(3).strip()
            rows.append((f"{f_}:{ln}:{a.task}", claim[:300], f"{f_}:{ln}", a.task, a.night))

    if not rows:
        print(json.dumps({"imported": 0}))
        return
    c = sqlite3.connect(a.db, timeout=30)
    c.executemany(
        """INSERT INTO fact (pk,claim,evidence,task_id,night_id,confidence,created_at)
           VALUES (?,?,?,?,?,'normal',?)
           ON CONFLICT(pk) DO UPDATE SET claim=excluded.claim, evidence=excluded.evidence,
             task_id=excluded.task_id, night_id=excluded.night_id""",
        [r + (int(time.time()),) for r in rows],
    )
    c.commit()
    print(json.dumps({"imported": len(rows)}))


if __name__ == "__main__":
    main()
