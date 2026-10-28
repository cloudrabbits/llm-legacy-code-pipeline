"""夜间无人值守主循环。

    python orchestrator.py --project D:\\IdeaProjects\\supermarketmanager --profile deepseek_sim_qwen38
    python orchestrator.py --project <path> --profile <name> --dry-run      # 只跑纯脚本阶段
    python orchestrator.py --project <path> --profile <name> --max-tasks 5  # 冒烟

行为约定（规格书第五节第 4 条）：
    * 到点后**停止取新任务**，但已在途的任务跑完；
    * 每完成一个任务写一次检查点（append-only JSONL），崩溃后按 task_id 续跑；
    * 心跳每 30s 一次，10 分钟无心跳由 `tools/watchdog.ps1` 重启本进程。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

# 允许直接 `python orchestrator.py` 运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.artifacts import ArtifactStore, SummaryStore  # noqa: E402
from pipeline.backend import Backend, DEFAULT_BUDGET_PATH  # noqa: E402
from pipeline.checkpoint import Checkpoint  # noqa: E402
from pipeline.config_loader import load_budget  # noqa: E402
from pipeline.errors import ContextOverflowError, PipelineError  # noqa: E402
from pipeline.executor import FailureTracker, RetryPolicy, run_with_retry  # noqa: E402
from pipeline.logging_setup import prune_old_logs, setup_logging  # noqa: E402
from pipeline.models import CheckpointEvent  # noqa: E402
from pipeline.monitor import Monitor  # noqa: E402
from pipeline.planner import PipelineConfig, check_gate, load_pipeline_config, load_tasks, order_tasks  # noqa: E402
from pipeline.session import SessionManager, SessionPolicy  # noqa: E402
from pipeline.stages import StageContext, run_stage  # noqa: E402
from pipeline.tokenizer import Tokenizer  # noqa: E402

EXIT_OK = 0
EXIT_PARTIAL = 2   # 时间窗耗尽，属于正常收尾
EXIT_FAILED = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="夜间无人值守分析编排器")
    ap.add_argument("--project", required=True, help="被分析项目根目录")
    ap.add_argument("--profile", default="deepseek_sim_qwen38", help="后端画像名（切换后端只改这里）")
    ap.add_argument("--config", default=os.path.join("config", "pipeline.yaml"))
    ap.add_argument("--budget", default=DEFAULT_BUDGET_PATH)
    ap.add_argument("--tasks", default=None, help="任务目录，默认取配置里的 paths.tasks")
    ap.add_argument("--runtime", default=None, help="运行时根目录前缀（state/artifacts/summaries 会挂在其下）")
    ap.add_argument("--duration-hours", type=float, default=None, help="覆盖配置里的最大时长")
    ap.add_argument("--max-tasks", type=int, default=None, help="最多执行多少个任务（冒烟用）")
    ap.add_argument("--dry-run", action="store_true", help="只执行纯脚本阶段，跳过一切 LLM 调用")
    ap.add_argument("--log-level", default=None)
    ap.add_argument("--verbose", action="store_true", help="控制台也输出 INFO 级日志（手动值守时用）")
    return ap.parse_args(argv)


def _under(root: str | None, path: str) -> str:
    """把配置里的相对路径挂到运行时根目录下。

    `--runtime` 是**运行根目录覆盖**：`runtime/state` -> `<root>/state`，
    `logs` -> `<root>/logs`。不给 `--runtime` 时原样使用配置路径。
    """
    if not root:
        return path
    return os.path.join(root, os.path.basename(os.path.normpath(path)))


def run(args: argparse.Namespace) -> int:
    cfg: PipelineConfig = load_pipeline_config(args.config)
    logger = setup_logging(
        _under(args.runtime, cfg.logging.dir),
        retention_days=cfg.logging.retention_days,
        level=args.log_level or cfg.logging.level,
        console_level="INFO" if args.verbose else "WARNING",
    )
    prune_old_logs(_under(args.runtime, cfg.logging.dir), cfg.logging.retention_days)

    # ---------------------------------------------------------------- 基础设施
    state_dir = _under(args.runtime, cfg.paths.state)
    checkpoint = Checkpoint(
        path=os.path.join(state_dir, "checkpoint.jsonl"),
        index_path=os.path.join(state_dir, "index.json"),
    )
    artifacts = ArtifactStore(root=_under(args.runtime, cfg.paths.artifacts))
    tokenizer = Tokenizer()
    summaries = SummaryStore(
        root=_under(args.runtime, cfg.paths.summaries),
        max_tokens=cfg.session.max_summary_tokens,
        tokenizer=tokenizer,
    )
    sessions = SessionManager(
        SessionPolicy(
            max_turns=cfg.session.max_turns,
            max_cumulative_prompt_tokens=cfg.session.max_cumulative_prompt_tokens,
            max_summary_tokens=cfg.session.max_summary_tokens,
        ),
        checkpoint=checkpoint,
        summaries=summaries,
        start_seq=checkpoint.state.session_seq + 1,
        logger=logger,
    )
    monitor = Monitor(
        heartbeat_path=os.path.join(state_dir, "heartbeat.json"),
        gpu_log_path=os.path.join(_under(args.runtime, cfg.logging.dir), "gpu.jsonl"),
        heartbeat_interval_sec=cfg.resources.heartbeat_interval_sec,
        gpu_sample_every_tasks=cfg.resources.gpu_sample_every_tasks,
        logger=logger,
    )

    budget = load_budget(args.budget) if os.path.exists(args.budget) else None
    backend = None if args.dry_run else Backend.from_profile(args.profile, budget_path=args.budget)
    if backend is not None and budget is None:
        budget = backend.budget

    ctx = StageContext(
        cfg=cfg,
        project_root=args.project,
        artifacts=artifacts,
        summaries=summaries,
        tokenizer=tokenizer,
        budget=budget or load_budget(args.budget),
        backend=backend,
        sessions=sessions,
        monitor=monitor,
        logger=logger,
        dry_run=args.dry_run,
    )

    # ---------------------------------------------------------------- 计划
    tasks_dir = args.tasks or cfg.paths.tasks
    tasks = order_tasks(load_tasks(tasks_dir))
    if not tasks:
        logger.error("没有加载到任何任务：%s（先用 tools/plan_tasks.py 生成）", tasks_dir)
        checkpoint.close(status="no_tasks")
        return EXIT_FAILED

    queue = [t for t in tasks if not checkpoint.state.is_done(t.task_id)]
    logger.info(
        "启动：项目=%s 画像=%s 任务总数=%d 待执行=%d 断点续跑=%s",
        args.project,
        args.profile,
        len(tasks),
        len(queue),
        "是" if checkpoint.state.seq else "否",
    )
    checkpoint.append(CheckpointEvent(event="RUN_START", status=args.profile))

    deadline = _deadline(cfg, args)
    policy = RetryPolicy.from_config(cfg)
    tracker = FailureTracker(policy.degrade_after_local_failures)

    executed = 0
    stopped_by_deadline = False
    current_phase = None

    for task in queue:
        if args.max_tasks is not None and executed >= args.max_tasks:
            logger.warning("达到 --max-tasks=%d，停止取新任务", args.max_tasks)
            break
        if deadline is not None and datetime.now() >= deadline:
            stopped_by_deadline = True
            logger.warning("到达时间窗终点 %s，停止取新任务（在途任务会跑完）", deadline.isoformat(timespec="seconds"))
            break

        if task.phase != current_phase:
            current_phase = task.phase
            checkpoint.append(CheckpointEvent(event="PHASE_ENTER", phase=task.phase))

        skip, reason = check_gate(task.phase, checkpoint.state, cfg)
        if skip:
            logger.warning("阶段软阻塞：%s", reason)
            checkpoint.append(CheckpointEvent(event="TASK_SKIPPED", task_id=task.task_id, phase=task.phase, status=reason))
            continue

        if args.dry_run and not task.acceptance.llm_free:
            logger.info("dry-run：跳过需要 LLM 的任务 %s", task.task_id)
            checkpoint.append(CheckpointEvent(event="TASK_SKIPPED", task_id=task.task_id, phase=task.phase, status="dry_run"))
            continue

        # depends_on 表示「顺序」而非「必须成功」：上游失败只降级告警，不静默吞掉下游
        failed_deps = [
            dep
            for dep in task.depends_on
            if (checkpoint.state.tasks.get(dep) is not None)
            and checkpoint.state.tasks[dep].status in ("failed", "rejected")
        ]
        if failed_deps:
            logger.warning("任务 %s 的上游 %s 未成功，仍按顺序执行（下游可能不完整）", task.task_id, failed_deps)

        executed += 1
        monitor.beat(force=True, task=task.task_id)
        checkpoint.append(CheckpointEvent(event="TASK_STARTED", task_id=task.task_id, phase=task.phase))
        holder: dict = {"artifact": None, "module": None}

        def attempt(task=task, holder=holder):
            result = run_stage(ctx, task)
            holder["artifact"] = result.artifact
            holder["module"] = result.module
            return result

        outcome = run_with_retry(
            attempt,
            task_id=task.task_id,
            policy=policy,
            route=task.route,
            tracker=tracker,
            logger=logger,
        )
        outcome.flags = list(outcome.flags)
        checkpoint.append(
            CheckpointEvent(
                event=_event_name(outcome),
                task_id=task.task_id,
                phase=task.phase,
                attempt=outcome.attempts,
                route=task.route,
                status=outcome.status.value,
                error_class=outcome.error_class,
                error=(outcome.error or "")[:500] or None,
                flags=outcome.flags,
                artifact=holder["artifact"],
            )
        )
        monitor.on_task_finished()
        monitor.beat()

        if outcome.status.value == "failed":
            logger.error("任务 %s 失败：%s %s", task.task_id, outcome.error_class, outcome.error)
        if outcome.error_class == ContextOverflowError.code:
            logger.error("任务 %s 被客户端预算拒绝，需调小切分粒度后重排", task.task_id)

    # ---------------------------------------------------------------- 收尾
    # 无论是否跑完，都尽力产出晨报（P5 是纯脚本，不会因后端抖动失败）
    report_task = next((t for t in tasks if t.kind == "report"), None)
    if report_task is not None and not checkpoint.state.is_done(report_task.task_id):
        try:
            result = run_stage(ctx, report_task)
            checkpoint.append(
                CheckpointEvent(
                    event="TASK_SUCCEEDED",
                    task_id=report_task.task_id,
                    phase=report_task.phase,
                    status="succeeded",
                    artifact=result.artifact,
                )
            )
            logger.info("晨报已生成：%s", result.artifact)
        except PipelineError as exc:
            logger.error("晨报生成失败：%s", exc)

    monitor.beat(force=True, phase="done")
    checkpoint.close(status="deadline" if stopped_by_deadline else "completed")
    logger.info(
        "结束：执行 %d 个任务，状态=%s，检查点 seq=%d",
        executed,
        "时间窗耗尽" if stopped_by_deadline else "正常",
        checkpoint.state.seq,
    )
    return EXIT_PARTIAL if stopped_by_deadline else EXIT_OK


def _event_name(outcome) -> str:
    return {
        "succeeded": "TASK_SUCCEEDED",
        "rejected": "TASK_REJECTED",
        "skipped": "TASK_SKIPPED",
    }.get(outcome.status.value, "TASK_FAILED")


def _deadline(cfg: PipelineConfig, args: argparse.Namespace) -> datetime | None:
    """计算停止取新任务的时刻。"""
    if args.duration_hours:
        return datetime.now() + timedelta(hours=args.duration_hours)
    hours = cfg.run.window.max_duration_hours
    if hours and hours > 0:
        return datetime.now() + timedelta(hours=hours)
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except PipelineError as exc:
        print(f"[orchestrator] 流水线错误：{exc.code}: {exc}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
