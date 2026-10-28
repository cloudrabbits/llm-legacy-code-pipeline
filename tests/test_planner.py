"""任务计划：加载校验、排序、软阻塞门禁。"""

from __future__ import annotations

import json

import pytest

from pipeline.checkpoint import Checkpoint, RunState
from pipeline.errors import ValidationError
from pipeline.models import TaskStatus
from pipeline.planner import (
    PipelineConfig,
    check_gate,
    load_pipeline_config,
    load_tasks,
    order_tasks,
    pending_tasks,
)


def write_task(tmp_path, name: str, obj) -> None:
    (tmp_path / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def minimal(task_id: str, phase: str = "P1", **kw) -> dict:
    base = {"task_id": task_id, "phase": phase, "kind": "classify"}
    base.update(kw)
    return base


def test_load_pipeline_config_defaults():
    cfg = load_pipeline_config("config/pipeline.yaml")
    assert isinstance(cfg, PipelineConfig)
    assert cfg.session.max_turns == 6
    assert cfg.session.max_cumulative_prompt_tokens == 70000
    assert cfg.resources.gpu_sample_every_tasks == 10
    assert cfg.logging.retention_days == 14
    assert cfg.gates["P3"].skip_if_failure_rate_above == 0.20


def test_load_tasks_single_object_and_array(tmp_path):
    write_task(tmp_path, "a.json", minimal("t1"))
    write_task(tmp_path, "b.json", [minimal("t2"), minimal("t3", "P2")])
    tasks = load_tasks(str(tmp_path))
    assert [t.task_id for t in tasks] == ["t1", "t2", "t3"]
    assert tasks[2].phase == "P2"


def test_load_tasks_rejects_duplicate_id(tmp_path):
    write_task(tmp_path, "a.json", minimal("dup"))
    write_task(tmp_path, "b.json", minimal("dup"))
    with pytest.raises(ValidationError):
        load_tasks(str(tmp_path))


def test_load_tasks_rejects_dangling_dependency(tmp_path):
    write_task(tmp_path, "a.json", minimal("t1", depends_on=["nope"]))
    with pytest.raises(ValidationError):
        load_tasks(str(tmp_path))


def test_load_tasks_rejects_bad_field(tmp_path):
    write_task(tmp_path, "a.json", {"task_id": "x", "phase": "P9", "kind": "k"})
    with pytest.raises(ValidationError):
        load_tasks(str(tmp_path))


def test_order_tasks_respects_phase_then_dependency(tmp_path):
    write_task(tmp_path, "t.json", [minimal("late", "P3"), minimal("early", "P0"), minimal("mid", "P2")])
    ordered = order_tasks(load_tasks(str(tmp_path)))
    assert [t.task_id for t in ordered] == ["early", "mid", "late"]


def test_order_tasks_dependency_overrides_alphabetical(tmp_path):
    write_task(
        tmp_path,
        "t.json",
        [minimal("zzz"), minimal("aaa", depends_on=["zzz"])],
    )
    ordered = order_tasks(load_tasks(str(tmp_path)))
    assert [t.task_id for t in ordered] == ["zzz", "aaa"]


def test_order_tasks_detects_cycle(tmp_path):
    write_task(
        tmp_path,
        "t.json",
        [minimal("a", depends_on=["b"]), minimal("b", depends_on=["a"])],
    )
    with pytest.raises(ValidationError):
        order_tasks(load_tasks(str(tmp_path)))


def test_pending_tasks_skips_terminal():
    from pipeline.checkpoint import TaskState
    from pipeline.models import TaskDef

    tasks = [
        TaskDef(task_id="done", phase="P1", kind="k"),
        TaskDef(task_id="failed", phase="P1", kind="k"),
        TaskDef(task_id="todo", phase="P1", kind="k"),
    ]
    state = RunState()
    state.tasks["done"] = TaskState(task_id="done", status=TaskStatus.SUCCEEDED.value)
    state.tasks["failed"] = TaskState(task_id="failed", status=TaskStatus.FAILED.value)
    assert [t.task_id for t in pending_tasks(tasks, state)] == ["todo"]


def test_check_gate_skips_when_failure_rate_above_threshold(tmp_path):
    from pipeline.models import CheckpointEvent

    cfg = load_pipeline_config("config/pipeline.yaml")
    ckpt = Checkpoint(path=str(tmp_path / "ck.jsonl"), index_path=str(tmp_path / "index.json"))
    # P2 两件全败 -> 100% > 20%
    ckpt.append(CheckpointEvent(event="TASK_FAILED", task_id="a", phase="P2"))
    ckpt.append(CheckpointEvent(event="TASK_FAILED", task_id="b", phase="P2"))

    skip, reason = check_gate("P3", ckpt.state, cfg)
    assert skip is True
    assert "P2" in reason


def test_check_gate_passes_when_failure_rate_low(tmp_path):
    from pipeline.models import CheckpointEvent

    cfg = load_pipeline_config("config/pipeline.yaml")
    ckpt = Checkpoint(path=str(tmp_path / "ck.jsonl"), index_path=str(tmp_path / "index.json"))
    for i in range(10):
        ckpt.append(CheckpointEvent(event="TASK_SUCCEEDED", task_id=f"s{i}", phase="P2"))
    ckpt.append(CheckpointEvent(event="TASK_FAILED", task_id="f1", phase="P2"))
    assert check_gate("P3", ckpt.state, cfg) == (False, None)
    assert check_gate("P4", ckpt.state, cfg) == (False, None)
