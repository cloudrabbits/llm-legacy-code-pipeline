"""任务计划：加载、校验、排序、软阻塞门禁。

任务定义用 pydantic 校验（`tasks/*.json`），顺序由「阶段顺序 + depends_on
拓扑」共同决定；阶段之间支持软阻塞（如 P2 失败率 > 20% 则跳过 P3）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import ConfigError, ValidationError
from .models import TaskDef

__all__ = [
    "PHASE_ORDER",
    "WindowConfig",
    "RunConfig",
    "SessionConfig",
    "ResourceConfig",
    "LoggingConfig",
    "PathConfig",
    "GateConfig",
    "PipelineConfig",
    "load_pipeline_config",
    "load_tasks",
    "order_tasks",
    "pending_tasks",
    "check_gate",
]

PHASE_ORDER = ["P0", "P1", "P2", "P3", "P4", "P5"]


# --------------------------------------------------------------------------- 配置


class WindowConfig(BaseModel):
    """单次运行的时间上限。

    启动时刻与周期由计划任务（Windows）或 systemd timer（Linux）控制；
    编排器只消费 `max_duration_hours`（见 `orchestrator._deadline`）。
    """

    model_config = ConfigDict(extra="forbid")

    max_duration_hours: float = 8.0


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: WindowConfig = Field(default_factory=WindowConfig)
    degrade_action: Literal["mark_failed", "route_cloud"] = "mark_failed"
    local_failures_before_degrade: int = 3
    max_retries: int = 3
    base_backoff_sec: float = 30.0
    max_backoff_sec: float = 600.0


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_turns: int = 6
    max_cumulative_prompt_tokens: int = 70000
    max_summary_tokens: int = 4000


class ResourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gpu_sample_every_tasks: int = 10
    heartbeat_interval_sec: float = 30.0
    # 守护脚本的判定阈值见 ops/watchdog.ps1 (-ThresholdSeconds) 与
    # ops/deploy/linux/watchdog.sh (WATCHDOG_THRESHOLD_SEC)：跨语言读数无法与
    # Python 配置共享，因此不在本文件声明，避免「改了这里却不生效」。


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dir: str = "logs"
    retention_days: int = 14
    level: str = "INFO"


class PathConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = os.path.join("runtime", "state")
    artifacts: str = os.path.join("runtime", "artifacts")
    summaries: str = os.path.join("runtime", "summaries")
    tasks: str = "tasks"


class GateConfig(BaseModel):
    """阶段级软阻塞：观察某阶段的失败率，超阈值则跳过本阶段。"""

    model_config = ConfigDict(extra="forbid")

    watch_phase: str
    skip_if_failure_rate_above: float = 0.20


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: RunConfig = Field(default_factory=RunConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    paths: PathConfig = Field(default_factory=PathConfig)
    gates: dict[str, GateConfig] = Field(default_factory=dict)


def load_pipeline_config(path: str = os.path.join("config", "pipeline.yaml")) -> PipelineConfig:
    """加载并校验流水线配置。"""
    from .config_loader import load_yaml

    try:
        return PipelineConfig(**load_yaml(path))
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"流水线配置校验失败: {path}: {exc}") from exc


# --------------------------------------------------------------------------- 任务


def load_tasks(tasks_dir: str | None = None) -> list[TaskDef]:
    """加载 `tasks/*.json`。

    每个文件可以是单个任务对象，也可以是任务数组。
    校验失败（缺字段 / 类型错 / task_id 重复 / depends_on 悬空）一律抛 ValidationError。
    """
    tasks_dir = tasks_dir or "tasks"
    if not os.path.isdir(tasks_dir):
        return []

    tasks: list[TaskDef] = []
    for name in sorted(os.listdir(tasks_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(tasks_dir, name)
        with open(path, "r", encoding="utf-8") as fh:
            try:
                data: Any = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"任务文件不是合法 JSON: {path}: {exc}") from exc
        records = data if isinstance(data, list) else [data]
        for record in records:
            try:
                tasks.append(TaskDef(**record))
            except Exception as exc:  # noqa: BLE001
                raise ValidationError(f"任务定义校验失败: {path}: {exc}") from exc

    _validate_graph(tasks)
    return tasks


def _validate_graph(tasks: list[TaskDef]) -> None:
    """task_id 唯一 + depends_on 不悬空。"""
    seen: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            raise ValidationError(f"task_id 重复: {task.task_id}")
        seen.add(task.task_id)
    for task in tasks:
        for dep in task.depends_on:
            if dep not in seen:
                raise ValidationError(f"任务 {task.task_id} 依赖了不存在的任务: {dep}")


def order_tasks(tasks: Iterable[TaskDef]) -> list[TaskDef]:
    """按「阶段顺序 + depends_on 拓扑」排序（Kahn，同层按阶段与 task_id 稳定排序）。"""
    tasks = list(tasks)
    by_id = {t.task_id: t for t in tasks}

    def sort_key(task: TaskDef) -> tuple[int, str]:
        phase_idx = PHASE_ORDER.index(task.phase) if task.phase in PHASE_ORDER else len(PHASE_ORDER)
        return (phase_idx, task.task_id)

    indegree = {t.task_id: len([d for d in t.depends_on if d in by_id]) for t in tasks}
    dependents: dict[str, list[str]] = {t.task_id: [] for t in tasks}
    for task in tasks:
        for dep in task.depends_on:
            if dep in by_id:
                dependents[dep].append(task.task_id)

    ready = sorted([t.task_id for t in tasks if indegree[t.task_id] == 0], key=lambda i: sort_key(by_id[i]))
    ordered: list[TaskDef] = []
    while ready:
        task_id = ready.pop(0)
        ordered.append(by_id[task_id])
        for child in sorted(dependents[task_id], key=lambda i: sort_key(by_id[i])):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
        ready.sort(key=lambda i: sort_key(by_id[i]))

    if len(ordered) != len(tasks):
        missing = [t.task_id for t in tasks if t.task_id not in {o.task_id for o in ordered}]
        raise ValidationError(f"任务依赖存在环: {missing}")
    return ordered


def pending_tasks(tasks: Iterable[TaskDef], state: Any) -> list[TaskDef]:
    """过滤掉已进入终态的任务（断点续跑的核心）。"""
    return [t for t in tasks if not state.is_done(t.task_id)]


def check_gate(phase: str, state: Any, cfg: PipelineConfig) -> tuple[bool, str | None]:
    """判断某阶段是否应被软阻塞跳过。

    Returns:
        (skip, reason)；skip=True 时 reason 说明原因。
    """
    gate = cfg.gates.get(phase)
    if gate is None:
        return False, None
    rate = state.phase_failure_rate(gate.watch_phase)
    if rate > gate.skip_if_failure_rate_above:
        return True, (
            f"{gate.watch_phase} 失败率 {rate:.0%} 超过阈值 "
            f"{gate.skip_if_failure_rate_above:.0%}，跳过 {phase}"
        )
    return False, None
