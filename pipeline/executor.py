"""单任务执行：重试、指数退避、降级路由。

对外的两种形态：
    run_task(backend, task)          —— 直接调后端（契约测试用）
    run_with_retry(fn, task_id=...)  —— 包裹任意可调用（编排器用它包住整个阶段）

两者共用同一套退避与降级语义，避免「重试逻辑」在两处走偏。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from .errors import BackendError, BackendTimeoutError, ContextOverflowError, PipelineError
from .models import FLAG_CONTEXT_OVERFLOW, FLAG_DEGRADED, Result, TaskContext, TaskStatus

__all__ = ["RetryPolicy", "TaskOutcome", "FailureTracker", "run_task", "run_with_retry"]


@dataclass
class RetryPolicy:
    """重试与降级策略。

    degrade_action:
        mark_failed —— 直接标记失败（仿真阶段默认，见规格书第三节第 4 条）
        route_cloud —— 本地连续失败达到阈值后转云端
    """

    max_retries: int = 3
    base_delay_sec: float = 30.0
    max_delay_sec: float = 600.0
    jitter_ratio: float = 0.0
    degrade_after_local_failures: int = 3
    degrade_action: str = "mark_failed"

    @classmethod
    def from_config(cls, cfg: Any) -> "RetryPolicy":
        """从 `PipelineConfig` 构造。"""
        run = getattr(cfg, "run", None)
        if run is None:
            return cls()
        return cls(
            max_retries=getattr(run, "max_retries", 3),
            base_delay_sec=getattr(run, "base_backoff_sec", 30.0),
            max_delay_sec=getattr(run, "max_backoff_sec", 600.0),
            degrade_action=getattr(run, "degrade_action", "mark_failed"),
            degrade_after_local_failures=getattr(run, "local_failures_before_degrade", 3),
        )


@dataclass
class TaskOutcome:
    """一次任务执行的最终结论（写入 checkpoint 的素材）。"""

    task_id: str
    status: TaskStatus
    result: Result | None = None
    attempts: int = 0
    error_class: str | None = None
    error: str | None = None
    flags: list[str] = field(default_factory=list)
    degraded: bool = False
    sleeps: list[float] = field(default_factory=list)

    def to_event(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "attempts": self.attempts,
            "error_class": self.error_class,
            "error": self.error,
            "flags": list(self.flags),
            "degraded": self.degraded,
            "tokens": (
                {
                    "prompt": self.result.usage.prompt_tokens,
                    "completion": self.result.usage.completion_tokens,
                }
                if self.result
                else {}
            ),
        }


class FailureTracker:
    """连续本地失败计数，达到阈值触发降级（规格书：本地连续失败 3 次降级到云端）。"""

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self.consecutive_local_failures = 0

    def record(self, route: str, ok: bool) -> None:
        if ok:
            self.consecutive_local_failures = 0
            return
        if route == "local":
            self.consecutive_local_failures += 1
        # 云端失败不计入本地降级链

    def should_degrade(self) -> bool:
        return self.consecutive_local_failures >= self.threshold


def _stamp(result: Any, attempts: int, route: str) -> None:
    """给 Result 打上尝试次数与路由（非 Result 类型则跳过）。"""
    if result is None:
        return
    try:
        result.attempt = attempts
        result.route = route
    except AttributeError:  # pragma: no cover —— 阶段结果不是 Result
        pass


def run_with_retry(
    fn: Callable[[], Any],
    *,
    task_id: str,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    cloud_fn: Callable[[], Any] | None = None,
    tracker: FailureTracker | None = None,
    route: str = "local",
    logger: Any = None,
) -> TaskOutcome:
    """重试执行 `fn`，必要时降级到 `cloud_fn`。

    Args:
        fn: 单次尝试（抛 PipelineError 家族表示失败）。
        task_id: 任务标识。
        policy: 重试策略。
        sleep: 注入休眠函数（测试传 `lambda s: None` 以获得确定性行为）。
        rng: 抖动随机源；`jitter_ratio=0` 时不需要。
        cloud_fn: 降级目标；仅在策略允许且本地连续失败达阈值时调用。
        tracker: 连续失败计数器。
        route: 本次尝试的路由。

    Returns:
        TaskOutcome：状态为 succeeded / rejected / failed 之一。
    """
    policy = policy or RetryPolicy()
    rng = rng or random.Random(20261028)
    tracker = tracker or FailureTracker(policy.degrade_after_local_failures)

    attempts = 0
    last_exc: PipelineError | None = None
    sleeps: list[float] = []

    while True:
        attempts += 1
        try:
            result = fn()
            tracker.record(route, ok=True)
            _stamp(result, attempts, route)
            return TaskOutcome(
                task_id=task_id,
                status=TaskStatus.SUCCEEDED,
                result=result if isinstance(result, Result) else None,
                attempts=attempts,
                flags=list(getattr(result, "flags", []) or []) + ([FLAG_DEGRADED] if route != "local" else []),
                degraded=route != "local",
                sleeps=list(sleeps),
            )
        except ContextOverflowError as exc:
            # 客户端拒绝：不重试、不换后端，交给 planner 细分后重排
            tracker.record(route, ok=False)
            return TaskOutcome(
                task_id=task_id,
                status=TaskStatus.REJECTED,
                attempts=attempts,
                error_class=exc.code,
                error=exc.message,
                flags=[FLAG_CONTEXT_OVERFLOW],
                sleeps=list(sleeps),
            )
        except (BackendTimeoutError, BackendError) as exc:
            last_exc = exc
            if not getattr(exc, "retryable", True) or attempts > policy.max_retries:
                break
            delay = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** (attempts - 1)))
            if policy.jitter_ratio:
                delay *= 1.0 + rng.uniform(-policy.jitter_ratio, policy.jitter_ratio)
            sleeps.append(delay)
            if logger:
                logger.warning("任务 %s 第 %d 次失败（%s），%.1fs 后重试", task_id, attempts, exc.code, delay)
            sleep(delay)
            continue
        except PipelineError as exc:
            # ValidationError 等：语义性失败，重试没有意义
            last_exc = exc
            break

    tracker.record(route, ok=False)
    outcome = TaskOutcome(
        task_id=task_id,
        status=TaskStatus.FAILED,
        attempts=attempts,
        error_class=last_exc.code if last_exc else "UnknownError",
        error=last_exc.message if last_exc else "",
        sleeps=list(sleeps),
    )

    can_degrade = (
        policy.degrade_action == "route_cloud"
        and cloud_fn is not None
        and route == "local"
        and tracker.should_degrade()
    )
    if can_degrade:
        attempts += 1
        try:
            result = cloud_fn()
            tracker.record("cloud", ok=True)
            _stamp(result, attempts, "cloud")
            return TaskOutcome(
                task_id=task_id,
                status=TaskStatus.SUCCEEDED,
                result=result if isinstance(result, Result) else None,
                attempts=attempts,
                flags=list(getattr(result, "flags", []) or []) + [FLAG_DEGRADED],
                degraded=True,
                sleeps=list(sleeps),
            )
        except PipelineError as exc:
            outcome.error_class = exc.code
            outcome.error = exc.message
            outcome.attempts = attempts

    return outcome


def run_task(
    backend,
    task: TaskContext,
    policy: RetryPolicy | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    cloud_backend=None,
    tracker: FailureTracker | None = None,
) -> TaskOutcome:
    """直接调后端的便捷入口（契约测试与简单场景用）。"""
    state = {"route": task.route}

    def attempt() -> Result:
        return backend.complete(replace(task, route=state["route"]))

    def degrade() -> Result:
        state["route"] = "cloud"
        return cloud_backend.complete(replace(task, route="cloud"))

    return run_with_retry(
        attempt,
        task_id=task.task_id,
        policy=policy,
        sleep=sleep,
        rng=rng,
        cloud_fn=degrade if cloud_backend is not None else None,
        tracker=tracker,
        route=task.route,
    )
