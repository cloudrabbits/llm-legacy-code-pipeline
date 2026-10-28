#!/usr/bin/env python3
"""报告生成：跨夜恢复摘要 / 每夜增量报告 / 最终汇总（纯脚本，不消耗模型）"""
import argparse
import glob
import json
import os
import sqlite3
import subprocess
import sys
import time

PY = os.environ.get("PY", "python3")
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def q(db, sql, args=()):
    c = sqlite3.connect(db, timeout=30)
    c.row_factory = sqlite3.Row
    return [dict(r) for r in c.execute(sql, args).fetchall()]


def dbp(*args):
    return subprocess.run([PY, os.path.join(TOOLS, "lib", "db.py"), "--db", DB] + list(args),
                          capture_output=True, text=True).stdout.strip()


def remaining_nights(db, tps):
    """按未完成分片的平均产出与当晚实测吞吐估算剩余夜数（返回区间）"""
    pend = q(db, "SELECT COUNT(*) n FROM chunk WHERE status IN ('pending','stale','failed')")[0]["n"]
    if pend == 0:
        return 0, 0, 0
    avg = q(db, "SELECT AVG(chars_out) a FROM chunk WHERE status='done' AND chars_out>0")
    avg_chars = (avg[0]["a"] or 4000)
    tokens = pend * (avg_chars / 3.2)
    if not tps or tps <= 0:
        return None, None, pend
    cap = tps * 20000  # 有效秒数 ≈ 8h×0.7
    import math
    n = math.ceil(tokens / cap)
    return n, n + 1, pend


def mode_resume(a):
    """跨夜恢复摘要：只保留机器可消费的要点，控制在 ≤1.5K tokens"""
    tasks = q(a.db, "SELECT * FROM task ORDER BY priority, id")
    chunks = q(a.db, "SELECT * FROM chunk ORDER BY task_id, seq")
    facts = q(a.db, "SELECT COUNT(*) n FROM fact")[0]["n"]
    done = [t for t in tasks if t["status"] == "done"]
    pend = [t for t in tasks if t["status"] in ("pending", "partial", "stale", "failed")]

    oq = []
    for f in sorted(glob.glob(os.path.join(a.work, "handoff", "*", "*.md"))):
        for line in open(f, encoding="utf-8", errors="replace"):
            if line.strip().startswith("- ") and "open_questions" not in line:
                if line.strip().startswith("- summary:"):
                    continue
            if line.strip().startswith("  - "):
                oq.append(line.strip()[4:])

    lines = ["# 跨夜恢复摘要（脚本生成，勿手改）", "",
             f"- 已完成任务：{len(done)} / {len(tasks)}；已入库事实：{facts} 条",
             "- 已完成清单：" + (", ".join(t["id"] for t in done) or "无"),
             "- 待办清单：" + (", ".join(f"{t['id']}({t['status']})" for t in pend) or "无"),
             "", "## 未完成分片"]
    for c in chunks:
        if c["status"] != "done":
            lines.append(f"- {c['id']} [{c['status']}] → {c['output_part']}（输入 {c['input_range']}）")
    lines.append("")
    lines.append("## 未决问题（来自各分片交接卡）")
    lines += [f"- {x}" for x in dict.fromkeys(oq)][:20] or ["- 无"]
    out = os.path.join(a.work, "reports", "resume-brief.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(out)


def mode_night(a):
    runs = q(a.db, "SELECT * FROM run WHERE night_id=?", (a.night,))
    r = runs[0] if runs else {}
    chunks = q(a.db, "SELECT * FROM chunk WHERE night_id=? ORDER BY task_id, seq", (a.night,))
    n, n2, pend = remaining_nights(a.db, r.get("tps") or 0)
    tasks = q(a.db, "SELECT * FROM task ORDER BY priority, id")
    lines = [f"# 第 {a.night} 夜运行报告", "",
             f"- 时间：{time.strftime('%F %T', time.localtime(r.get('start_at', 0)))} → "
             f"{time.strftime('%F %T', time.localtime(r.get('end_at', 0)))}",
             f"- 结束原因：{r.get('stop_reason')}；实测 decode：{r.get('tps')} tok/s",
             f"- 本夜完成分片：{r.get('chunks_done')}；失败：{r.get('chunks_failed')}；结转：{r.get('carry_over')}", "",
             "## 本夜分片明细", "",
             "| 分片 | 状态 | 产出 | 耗时(s) | 输出字符 |", "|---|---|---|---|---|"]
    for c in chunks:
        lines.append(f"| {c['id']} | {c['status']} | {c['output_part']} | {c['seconds']} | {c['chars_out']} |")
    lines += ["", "## 任务进度", "", "| 任务 | 阶段 | 状态 | 产物 |", "|---|---|---|---|"]
    for t in tasks:
        lines.append(f"| {t['id']} | {t['phase']} | {t['status']} | {t['output']} |")
    if pend:
        est = f"{n}~{n2} 夜" if n else "未知（缺 tps）"
        lines += ["", f"## 工期预测", "", f"- 未完成分片：{pend}", f"- 预计还需：**{est}**"]
    out = os.path.join(a.report, f"night-{a.night:02d}.md")
    os.makedirs(a.report, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(out)


def mode_final(a):
    tasks = q(a.db, "SELECT * FROM task ORDER BY priority, id")
    chunks = q(a.db, "SELECT * FROM chunk ORDER BY task_id, seq")
    done_c = [c for c in chunks if c["status"] == "done"]
    cov = int(100 * len(done_c) / max(1, len(chunks)))
    lines = ["# 最终分析报告（跨夜汇总）", "", f"- 分片完成度：**{len(done_c)}/{len(chunks)}（{cov}%）**", "",
             "## 产物索引", "", "| 任务 | 状态 | 产物 |", "|---|---|---|"]
    for t in tasks:
        lines.append(f"| {t['id']} | {t['status']} | `{t['output']}` |")
    lines += ["", "## 未完成项（需人工处理）", ""]
    for c in chunks:
        if c["status"] != "done":
            lines.append(f"- {c['id']} → `{c['output_part']}`（{c['status']}，attempt={c['attempt']}）")
    lines += ["", "## 人工复核清单", "- 核对产物中的 `文件:行号` 证据是否真实",
              "- 对 `patches/*.diff` 逐个 `git apply --check`", "- 处理未决问题（见 resume-brief.md）"]
    out = os.path.join(a.report, "final.md")
    os.makedirs(a.report, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(out)


def main():
    global DB
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["resume", "night", "final"])
    ap.add_argument("--db", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--night", type=int, default=0)
    a = ap.parse_args()
    DB = a.db
    {"resume": mode_resume, "night": mode_night, "final": mode_final}[a.mode](a)


if __name__ == "__main__":
    main()
