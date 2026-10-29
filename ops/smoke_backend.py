"""后端冒烟自检：用极小请求验证画像真的能跑通。

    python ops/smoke_backend.py --profile deepseek_sim_qwen38
    python ops/smoke_backend.py --profile ollama_qwen38 --effort off

会分别以指定档位发一个最小请求，打印归一化结果与标记位。
用于：① 上线前确认参数名没写错；② 内网切换后确认服务可达。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# 允许以 `python ops/smoke_backend.py` 直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.backend import Backend  # noqa: E402
from pipeline.models import EffortLevel, TaskContext  # noqa: E402

PROMPT = (
    "下面是一个遗留 JSP 项目的文件片段，请只用一行回答：这个类的分层是"
    "(jsp/servlet/biz/dao/entity/util) 中的哪一个？\n\n"
    "public class UsersDao { public List<User> findAll() { ... } }"
)


def run(profile_name: str, effort: str, max_tokens: int, timeout: float) -> int:
    backend = Backend.from_profile(profile_name)
    task = TaskContext(
        task_id=f"smoke-{profile_name}-{effort}",
        phase="P1",
        user=PROMPT,
        effort=EffortLevel(effort),
        max_output_tokens=max_tokens,
        timeout_sec=timeout,
    )
    estimate = backend.estimate(task)
    print(f"[smoke] profile={backend.profile.name} model={backend.profile.cfg.model}")
    print(
        f"[smoke] effort={effort} 正文估算={estimate.tokens} 计入封装={backend.budget_tokens(task)} "
        f"(method={estimate.method}, budget={backend.budget.input_budget})"
    )
    try:
        result = backend.complete(task)
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    print(f"[smoke] reasoning={'有' if result.reasoning else '无'}  flags={result.flags}")
    speed = []
    if result.prefill_tps is not None:
        speed.append(f"prefill={result.prefill_tps:.1f} t/s")
    if result.decode_tps is not None:
        speed.append(f"decode={result.decode_tps:.1f} t/s")
    if result.total_tps is not None:
        speed.append(f"total={result.total_tps:.1f} t/s")
    if speed:
        print(f"[smoke] speed: {' | '.join(speed)}")
    else:
        print(f"[smoke] speed: 后端未返回分项耗时（latency={result.latency_ms}ms），无法拆分 prefill/decode")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="后端冒烟自检")
    ap.add_argument("--profile", default="deepseek_sim_qwen38")
    ap.add_argument("--effort", default="off", choices=[e.value for e in EffortLevel])
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args(argv)
    return run(args.profile, args.effort, args.max_tokens, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
