"""检查点：崩溃续跑、原子快照、幂等。"""

from __future__ import annotations

import json
import os

import pytest

from pipeline.checkpoint import Checkpoint, RunState, event_from_outcome
from pipeline.models import CheckpointEvent, TaskStatus


def make_ckpt(tmp_path, **kw) -> Checkpoint:
    return Checkpoint(
        path=str(tmp_path / "checkpoint.jsonl"),
        index_path=str(tmp_path / "index.json"),
        **kw,
    )


def test_append_assigns_seq_and_timestamp(tmp_path):
    ckpt = make_ckpt(tmp_path)
    event = ckpt.append(CheckpointEvent(event="RUN_START"))
    assert event.seq == 1
    assert event.ts
    assert ckpt.state.seq == 1


def test_replay_restores_state_after_crash(tmp_path):
    """模拟崩溃：写一半 -> 用同一个文件重新打开 -> 状态完整恢复。"""
    ckpt = make_ckpt(tmp_path, snapshot_every=1)
    ckpt.append(CheckpointEvent(event="TASK_STARTED", task_id="P1-a", phase="P1"))
    ckpt.append(CheckpointEvent(event="TASK_SUCCEEDED", task_id="P1-a", phase="P1", attempt=1))
    ckpt.append(CheckpointEvent(event="TASK_STARTED", task_id="P1-b", phase="P1"))
    ckpt.append(CheckpointEvent(event="TASK_FAILED", task_id="P1-c", phase="P1", error_class="TimeoutError"))
    ckpt.append(CheckpointEvent(event="SESSION_ROTATED", session_seq=4))

    revived = make_ckpt(tmp_path)  # 等价于进程重启
    assert revived.state.seq == 5
    assert revived.state.tasks["P1-a"].status == TaskStatus.SUCCEEDED.value
    assert revived.state.tasks["P1-b"].status == TaskStatus.RUNNING.value
    assert revived.state.tasks["P1-c"].error_class == "TimeoutError"
    assert revived.state.session_seq == 4


def test_pending_and_resumable(tmp_path):
    ckpt = make_ckpt(tmp_path)
    for tid, ev in [
        ("a", "TASK_SUCCEEDED"),
        ("b", "TASK_FAILED"),
        ("c", "TASK_STARTED"),
        ("d", "TASK_REJECTED"),
    ]:
        ckpt.append(CheckpointEvent(event=ev, task_id=tid, phase="P1"))

    assert ckpt.pending(["a", "b", "c", "d", "e"]) == ["c", "e"]
    assert ckpt.resumable() == ["c"]


def test_rejected_task_is_terminal_and_flagged(tmp_path):
    ckpt = make_ckpt(tmp_path)
    ckpt.append(
        CheckpointEvent(event="TASK_REJECTED", task_id="big", flags=["CONTEXT_OVERFLOW"], error_class="ContextOverflowError")
    )
    task = ckpt.state.tasks["big"]
    assert task.terminal()
    assert "CONTEXT_OVERFLOW" in task.flags
    assert ckpt.pending(["big"]) == []


def test_snapshot_is_atomic_and_no_tmp_left(tmp_path):
    ckpt = make_ckpt(tmp_path, snapshot_every=1)
    ckpt.append(CheckpointEvent(event="RUN_START"))
    assert os.path.exists(tmp_path / "index.json")
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".tmp-")]
    assert not leftovers, "原子写不得留下临时文件"

    with open(tmp_path / "index.json", "r", encoding="utf-8") as fh:
        index = json.load(fh)
    assert index["seq"] == 1
    assert RunState.from_dict(index).seq == 1


def test_malformed_line_is_skipped_not_fatal(tmp_path):
    ckpt = make_ckpt(tmp_path)
    with open(ckpt.path, "a", encoding="utf-8") as fh:
        fh.write('{"event":"TASK_SUCCEEDED","task_id":"ok"}\n')
        fh.write('{"event":"TASK_SUCCEEDED","task_id":"broken"\n')  # 半行
    revived = make_ckpt(tmp_path)
    assert revived.state.malformed_lines == 1
    assert "ok" in revived.state.tasks
    assert "broken" not in revived.state.tasks


def test_phase_failure_rate(tmp_path):
    ckpt = make_ckpt(tmp_path)
    ckpt.append(CheckpointEvent(event="TASK_SUCCEEDED", task_id="a", phase="P2"))
    ckpt.append(CheckpointEvent(event="TASK_FAILED", task_id="b", phase="P2"))
    assert ckpt.state.phase_failure_rate("P2") == 0.5
    assert ckpt.state.phase_failure_rate("P3") == 0.0


def test_event_from_outcome_maps_status():
    class Outcome:
        def __init__(self, status, result=None, error_class=None, error=None, flags=None):
            self.status = status
            self.result = result
            self.error_class = error_class
            self.error = error
            self.flags = flags or []

    assert event_from_outcome("x", "P1", 1, Outcome(TaskStatus.SUCCEEDED)).event == "TASK_SUCCEEDED"
    assert event_from_outcome("x", "P1", 1, Outcome(TaskStatus.REJECTED)).event == "TASK_REJECTED"
    assert event_from_outcome("x", "P1", 1, Outcome(TaskStatus.FAILED)).event == "TASK_FAILED"


def test_context_manager_writes_run_end(tmp_path):
    with make_ckpt(tmp_path, snapshot_every=1000) as ckpt:
        ckpt.append(CheckpointEvent(event="RUN_START"))
    revived = make_ckpt(tmp_path)
    assert revived.state.ended_ts
    assert revived.state.counters.get("RUN_END") == 1


def test_load_index_missing_file_returns_empty(tmp_path):
    ckpt = make_ckpt(tmp_path)
    assert ckpt.load_index().seq == 0
