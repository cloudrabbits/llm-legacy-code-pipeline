"""会话状态机：轮换触发条件与摘要落盘。"""

from __future__ import annotations

import pytest

from pipeline.artifacts import SummaryStore
from pipeline.checkpoint import Checkpoint
from pipeline.errors import ValidationError
from pipeline.session import SessionManager, SessionPolicy
from pipeline.tokenizer import Tokenizer

HEURISTIC = Tokenizer(prefer="heuristic")


def build(tmp_path, **policy_kw) -> SessionManager:
    ckpt = Checkpoint(path=str(tmp_path / "ck.jsonl"), index_path=str(tmp_path / "index.json"))
    summaries = SummaryStore(root=str(tmp_path / "summaries"), max_tokens=200, tokenizer=HEURISTIC)
    return SessionManager(SessionPolicy(**policy_kw), checkpoint=ckpt, summaries=summaries)


def test_rotate_on_max_turns(tmp_path):
    sm = build(tmp_path, max_turns=3)
    for _ in range(3):
        assert sm.needs_rotation() is None
        sm.record_turn(100)
    assert sm.needs_rotation() == "max_turns"


def test_rotate_on_cumulative_prompt_budget(tmp_path):
    sm = build(tmp_path, max_cumulative_prompt_tokens=1000)
    sm.record_turn(600)
    assert sm.needs_rotation(next_prompt_tokens=300) is None
    assert sm.needs_rotation(next_prompt_tokens=500) == "prompt_budget"


def test_rotate_on_module_switch(tmp_path):
    sm = build(tmp_path)
    sm.ensure(module="users")
    assert sm.needs_rotation(module="orders") == "module_switch"
    assert sm.needs_rotation(module="users") is None


def test_rotate_on_quality_drop(tmp_path):
    sm = build(tmp_path)
    sm.record_turn(10, accepted=False)
    assert sm.needs_rotation() is None, "单次验收失败不必换会话"
    sm.record_turn(10, accepted=False)
    assert sm.needs_rotation() == "quality_drop"


def test_rotate_writes_summary_and_event(tmp_path):
    sm = build(tmp_path, max_turns=1)
    sm.record_turn(100)
    session = sm.rotate("max_turns", module="orders", summary_text="本轮结论：users 模块 3 个 Servlet。")

    assert session.seq == 2
    assert session.module == "orders"
    assert (tmp_path / "summaries" / "session-0001.md").exists()
    assert sm.checkpoint.state.session_seq == 2
    events = [e for e in sm.checkpoint.state.counters if e == "SESSION_ROTATED"]
    assert events


def test_summary_too_long_rejected(tmp_path):
    sm = build(tmp_path)
    with pytest.raises(ValidationError):
        sm.rotate("module_switch", summary_text="很长的摘要" * 500)


def test_ensure_binds_module_without_rotation(tmp_path):
    sm = build(tmp_path)
    session = sm.ensure(module="users")
    assert session.seq == 1
    assert session.module == "users"


def test_session_state_serializable(tmp_path):
    sm = build(tmp_path)
    sm.record_turn(42)
    data = sm.current_session.to_dict()
    assert data["turns"] == 1
    assert data["cumulative_prompt_tokens"] == 42
