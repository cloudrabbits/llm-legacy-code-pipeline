"""检查点：append-only JSONL 事件流 + 原子快照。

设计要点（规格书第四节第 3 条）：
    * 事件流 `runtime/state/checkpoint.jsonl` 只追加，是**唯一事实来源**；
      崩溃后从它重放即可恢复，不依赖内存状态。
    * `runtime/state/index.json` 是周期性重建的**快照**，走 tmp + os.replace 原子写，
      供看门狗 / 人工查看当前进度；它永远可以被事件流重放覆盖。
    * 单行 ≤ 512B 时用一次 write() 追加；即便极端情况下最后一行写坏，
      重放时跳过非法行即可，不会污染已提交的事件。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from .errors import PipelineError
from .models import CheckpointEvent, TaskStatus
from .util import atomic_write_json, ensure_dir, utc_now_iso

__all__ = ["TaskState", "RunState", "Checkpoint"]

#: 终态：本次运行中不再重排（失败也只记一次，次日视需要重跑）
TERMINAL_STATUSES = (
    TaskStatus.SUCCEEDED.value,
    TaskStatus.FAILED.value,
    TaskStatus.REJECTED.value,
    TaskStatus.SKIPPED.value,
)


@dataclass
class TaskState:
    """单个任务在检查点里的状态。"""

    task_id: str
    phase: str = ""
    status: str = TaskStatus.PENDING.value
    attempts: int = 0
    flags: list[str] = field(default_factory=list)
    artifact: str | None = None
    error_class: str | None = None
    updated_ts: str = ""

    def terminal(self) -> bool:
        """是否已进入终态（不再被重排）。"""
        return self.status in TERMINAL_STATUSES

    def succeeded(self) -> bool:
        return self.status == TaskStatus.SUCCEEDED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "phase": self.phase,
            "status": self.status,
            "attempts": self.attempts,
            "flags": list(self.flags),
            "artifact": self.artifact,
            "error_class": self.error_class,
            "updated_ts": self.updated_ts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


@dataclass
class RunState:
    """由事件流重放得到的运行态。"""

    seq: int = 0
    started_ts: str = ""
    ended_ts: str = ""
    session_seq: int = 0
    tasks: dict[str, TaskState] = field(default_factory=dict)
    phases: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    malformed_lines: int = 0
    #: 本 runtime 归属的项目规范绝对路径；空串表示旧格式或尚未记录
    project: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "started_ts": self.started_ts,
            "ended_ts": self.ended_ts,
            "session_seq": self.session_seq,
            "tasks": {k: v.to_dict() for k, v in self.tasks.items()},
            "phases": dict(self.phases),
            "counters": dict(self.counters),
            "malformed_lines": self.malformed_lines,
            "project": self.project,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunState":
        state = cls()
        state.seq = int(data.get("seq", 0))
        state.started_ts = data.get("started_ts", "")
        state.ended_ts = data.get("ended_ts", "")
        state.session_seq = int(data.get("session_seq", 0))
        state.phases = dict(data.get("phases") or {})
        state.counters = dict(data.get("counters") or {})
        state.malformed_lines = int(data.get("malformed_lines", 0))
        state.project = data.get("project", "")
        for task_id, raw in (data.get("tasks") or {}).items():
            state.tasks[task_id] = TaskState.from_dict(raw)
        return state

    # -------------------------------------------------------------- 查询

    def phase_failure_rate(self, phase: str) -> float:
        """某阶段的失败率（终态任务中 failed 占比）；无终态任务时为 0.0。"""
        finished = [t for t in self.tasks.values() if t.phase == phase and t.terminal()]
        if not finished:
            return 0.0
        failed = sum(1 for t in finished if t.status == TaskStatus.FAILED.value)
        return failed / len(finished)

    def is_done(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        return bool(task and task.terminal())


class Checkpoint:
    """append-only 事件流 + 原子快照。

    Args:
        path: 事件流路径。
        index_path: 快照路径（None 表示不落快照）。
        snapshot_every: 每追加多少个事件重建一次快照。
    """

    def __init__(
        self,
        path: str = os.path.join("runtime", "state", "checkpoint.jsonl"),
        index_path: str | None = os.path.join("runtime", "state", "index.json"),
        *,
        snapshot_every: int = 20,
    ) -> None:
        self.path = path
        self.index_path = index_path
        self.snapshot_every = max(1, snapshot_every)
        ensure_dir(os.path.dirname(os.path.abspath(path)))
        self.state = self.replay()

    # -------------------------------------------------------------- 重建

    def replay(self) -> RunState:
        """从事件流重放运行态（启动时的唯一依据）。"""
        state = RunState()
        if not os.path.exists(self.path):
            return state
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = CheckpointEvent(**json.loads(line))
                except Exception:  # noqa: BLE001 —— 半行写入也要可恢复
                    state.malformed_lines += 1
                    continue
                state.seq = max(state.seq, event.seq)
                self._apply(state, event)
        return state

    def load_index(self) -> RunState:
        """读取原子快照（比全量重放快，用于看门狗/仪表盘）。"""
        if not self.index_path or not os.path.exists(self.index_path):
            return RunState()
        try:
            with open(self.index_path, "r", encoding="utf-8") as fh:
                return RunState.from_dict(json.load(fh))
        except Exception:  # noqa: BLE001
            return RunState()

    # -------------------------------------------------------------- 写入

    def append(self, event: CheckpointEvent) -> CheckpointEvent:
        """追加一条事件；seq/ts 自动补全。"""
        if not event.seq:
            event = event.model_copy(update={"seq": self.state.seq + 1})
        if not event.ts:
            event = event.model_copy(update={"ts": utc_now_iso()})

        payload = (event.to_jsonl() + "\n").encode("utf-8")
        with open(self.path, "ab") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())

        self.state.seq = event.seq
        self._apply(self.state, event)

        if event.seq % self.snapshot_every == 0:
            self.snapshot()
        return event

    def snapshot(self) -> None:
        """原子落盘快照（tmp + os.replace）。"""
        if not self.index_path:
            return
        atomic_write_json(self.index_path, self.state.to_dict())

    # -------------------------------------------------------------- 事件语义

    @staticmethod
    def _apply(state: RunState, event: CheckpointEvent) -> None:
        """把一条事件折叠进运行态。"""
        state.counters[event.event] = state.counters.get(event.event, 0) + 1

        if event.event == "RUN_START":
            state.started_ts = event.ts
            if event.project:
                state.project = event.project
        elif event.event == "RUN_END":
            state.ended_ts = event.ts
        elif event.event in ("PHASE_ENTER", "PHASE_EXIT"):
            if event.phase:
                state.phases[event.phase] = event.event
        elif event.event == "SESSION_ROTATED":
            state.session_seq = event.session_seq or state.session_seq + 1

        if not event.task_id:
            return

        task = state.tasks.get(event.task_id)
        if task is None:
            task = TaskState(task_id=event.task_id)
            state.tasks[event.task_id] = task
        if event.phase:
            task.phase = event.phase
        if event.attempt:
            task.attempts = max(task.attempts, event.attempt)
        if event.artifact:
            task.artifact = event.artifact
        if event.flags:
            for flag in event.flags:
                if flag not in task.flags:
                    task.flags.append(flag)
        if event.error_class:
            task.error_class = event.error_class

        status_by_event = {
            "TASK_STARTED": TaskStatus.RUNNING.value,
            "TASK_RETRY": TaskStatus.RUNNING.value,
            "TASK_SUCCEEDED": TaskStatus.SUCCEEDED.value,
            "TASK_FAILED": TaskStatus.FAILED.value,
            "TASK_REJECTED": TaskStatus.REJECTED.value,
            "TASK_SKIPPED": TaskStatus.SKIPPED.value,
        }
        new_status = status_by_event.get(event.event)
        if new_status:
            task.status = new_status
        if event.ts:
            task.updated_ts = event.ts

    def close(self, *, status: str = "ok") -> None:
        """收尾：写 RUN_END 并强制落一次快照。"""
        self.append(CheckpointEvent(event="RUN_END", status=status))
        self.snapshot()

    def __enter__(self) -> "Checkpoint":
        return self

    def __exit__(self, *exc) -> None:
        if any(exc):
            self.snapshot()
        else:
            self.close()

    # -------------------------------------------------------------- 辅助

    def pending(self, task_ids: list[str]) -> list[str]:
        """从候选任务里挑出尚未进入终态的（断点续跑的关键）。"""
        return [t for t in task_ids if not self.state.is_done(t)]

    def resumable(self) -> list[str]:
        """上次运行处于 RUNNING 的任务：崩溃点在途，本次重排。"""
        return [t.task_id for t in self.state.tasks.values() if t.status == TaskStatus.RUNNING.value]


def event_from_outcome(
    task_id: str,
    phase: str,
    attempt: int,
    outcome: Any,
    artifact: str | None = None,
    *,
    route: str | None = None,
    error_max_len: int | None = None,
) -> CheckpointEvent:
    """把 `executor.TaskOutcome` 转成检查点事件。

    Args:
        route: 显式指定路由。编排器包的是「整个阶段」，其 `outcome.result` 是
               `StageResult` 而非 `Result`，取不到 route，必须由调用方显式传入；
               契约测试路径（包的是单次后端调用）可以用 `outcome.result` to自动取值。
        error_max_len: 错误信息的最大字符数。编排器写入事件流时会截断，
               避免后端把整段报错回显撑爆单行事件（JSONL 一行一个事件）。
    """
    if outcome.status is TaskStatus.SUCCEEDED:
        name = "TASK_SUCCEEDED"
    elif outcome.status is TaskStatus.REJECTED:
        name = "TASK_REJECTED"
    elif outcome.status is TaskStatus.SKIPPED:
        name = "TASK_SKIPPED"
    else:
        name = "TASK_FAILED"
    tokens = {}
    usage = getattr(outcome.result, "usage", None)
    if usage is not None:
        tokens = {"prompt": usage.prompt_tokens, "completion": usage.completion_tokens}
    error = outcome.error or ""
    if error_max_len is not None:
        error = error[:error_max_len]
    error = error or None
    return CheckpointEvent(
        event=name,
        task_id=task_id,
        phase=phase,
        attempt=attempt,
        route=route or getattr(outcome.result, "route", "local"),
        status=outcome.status.value,
        error_class=outcome.error_class,
        error=error,
        tokens=tokens,
        flags=list(outcome.flags),
        artifact=artifact,
    )
