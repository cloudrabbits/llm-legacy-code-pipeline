"""生成任务队列 `tasks/*.json`。

按目标项目的真实规模切批：P1 的输入批由 Qwen tokenizer 估算后装箱，
保证每批都不超过输入预算（超预算的任务在客户端会被拒，等于白排一晚）。

    python tools/plan_tasks.py --project D:\\IdeaProjects\\supermarketmanager
    python tools/plan_tasks.py --project <path> --limit-p1 2     # 首夜抽样试点
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.scan import load_project_facts, read_source, rel_list  # noqa: E402
from pipeline.context import plan_batches  # noqa: E402
from pipeline.tokenizer import Tokenizer  # noqa: E402

DEFAULT_BATCH_TOKENS = 30_000
DEFAULT_MAX_CHARS = 20_000


def build(project_root: str, *, batch_tokens: int, limit_p1: int | None, effort: str) -> dict[str, list[dict]]:
    facts = load_project_facts(project_root)
    root = facts["project"]["root"]
    tokenizer = Tokenizer()

    rels = rel_list(facts)
    texts = {rel: read_source(rel, root)[:DEFAULT_MAX_CHARS] for rel in rels}
    batches, needs_split = plan_batches(texts, tokenizer, batch_tokens)
    if limit_p1:
        batches = batches[:limit_p1]

    p0 = {
        "task_id": "P0-baseline",
        "phase": "P0",
        "kind": "baseline",
        "route": "local",
        "effort": "off",
        "acceptance": {"llm_free": True, "min_chars": 50},
    }

    p1 = [
        {
            "task_id": f"P1-batch-{i + 1:03d}",
            "phase": "P1",
            "kind": "classify",
            "route": "local",
            "depends_on": ["P0-baseline"],
            "input_files": batch,
            "effort": effort,
            "max_output_tokens": 8192,
            "max_retries": 3,
            "timeout_sec": 900,
            "acceptance": {
                "min_chars": 20,
                "required_keys": ["items"],
                "regex_must": [r'"layer"\s*:\s*"(jsp|servlet|biz|dao|entity|util|config|sql|other)"'],
            },
        }
        for i, batch in enumerate(batches)
    ]

    p1_ids = [t["task_id"] for t in p1]
    p2 = {
        "task_id": "P2-modules",
        "phase": "P2",
        "kind": "modules",
        "route": "local",
        "depends_on": p1_ids,
        "effort": effort,
        "max_output_tokens": 8192,
        "max_retries": 3,
        "timeout_sec": 900,
        "acceptance": {"min_chars": 20, "required_keys": ["modules"]},
    }
    p3 = {
        "task_id": "P3-deps",
        "phase": "P3",
        "kind": "deps",
        "route": "local",
        "depends_on": ["P2-modules"],
        "effort": effort,
        "max_output_tokens": 8192,
        "max_retries": 3,
        "timeout_sec": 900,
        # 脚本边已由 stage_deps 无条件落盘，LLM 只输出违规清单（短输出，避免 TRUNCATED）
        "acceptance": {"min_chars": 20, "required_keys": ["violations"]},
    }

    # P4 用 "auto"：模块清单在运行时从 P2 产物读取。
    # 计划期还不知道模型会把模块切多细（实测会把登录拆出 Auth），
    # 若在这里写死脚本模块名，P2 多出来的模块就没有摘要。
    p4 = [
        {
            "task_id": "P4-arch",
            "phase": "P4",
            "kind": "architecture",
            "route": "local",
            "depends_on": ["P3-deps"],
            "effort": effort,
            "max_output_tokens": 8192,
            "max_retries": 2,
            "timeout_sec": 1800,
            "payload": {"module": "auto"},
            "acceptance": {"min_chars": 20, "required_keys": ["summary", "risks"]},
        }
    ]
    p4_ids = [t["task_id"] for t in p4]
    p5 = {
        "task_id": "P5-report",
        "phase": "P5",
        "kind": "report",
        "route": "local",
        "depends_on": p4_ids,
        "effort": "off",
        "acceptance": {"llm_free": True, "min_chars": 50},
    }

    if needs_split:
        print(f"[plan] 警告：{len(needs_split)} 个文件单文件就超过批预算，已按文件整体成批，"
              f"运行时若被拒请调小 --batch-tokens：{needs_split[:5]}")

    return {
        "p0_baseline.json": [p0],
        "p1_classify.json": p1,
        "p2_modules.json": [p2],
        "p3_deps.json": [p3],
        "p4_architecture.json": p4,
        "p5_report.json": [p5],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成夜间流水线任务队列")
    ap.add_argument("--project", required=True, help="被分析项目根目录")
    ap.add_argument("--out", default="tasks")
    ap.add_argument("--batch-tokens", type=int, default=DEFAULT_BATCH_TOKENS)
    ap.add_argument("--limit-p1", type=int, default=None, help="只保留前 N 个 P1 批次（首夜抽样试点）")
    ap.add_argument("--effort", default="medium", choices=["off", "low", "medium", "xhigh"])
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    tasks = build(args.project, batch_tokens=args.batch_tokens, limit_p1=args.limit_p1, effort=args.effort)
    total = 0
    for filename, records in tasks.items():
        path = os.path.join(args.out, filename)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        total += len(records)
        print(f"[plan] {path}: {len(records)} 个任务")
    print(f"[plan] 合计 {total} 个任务")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
