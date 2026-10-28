"""上下文装配与预算内装箱。"""

from __future__ import annotations

import pytest

from pipeline.context import (
    Block,
    build_task_context,
    pack_blocks,
    plan_batches,
    render_blocks,
    split_oversized,
)
from pipeline.errors import ContextOverflowError
from pipeline.models import Budget, EffortLevel
from pipeline.tokenizer import Tokenizer

TOK = Tokenizer(prefer="heuristic")  # 单测不依赖 7MB 词表，快且确定性足够


def test_render_blocks_has_headers():
    text = render_blocks([Block("A.java", "class A {}")])
    assert "===== A.java =====" in text
    assert "class A {}" in text


def test_pack_blocks_respects_limit():
    blocks = [Block(f"f{i}", "x" * 320) for i in range(6)]  # 每块约 100-118 tokens
    chunks, oversized = pack_blocks(blocks, TOK, limit=250)
    assert not oversized
    assert len(chunks) >= 2
    for chunk in chunks:
        assert TOK.estimate(render_blocks(chunk)).tokens <= 250


def test_pack_blocks_reports_oversized():
    blocks = [Block("big", "y" * 100_000), Block("small", "ok")]
    chunks, oversized = pack_blocks(blocks, TOK, limit=500)
    assert [b.name for b in oversized] == ["big"]
    assert [b.name for c in chunks for b in c] == ["small"]


def test_split_oversized_produces_fitting_parts():
    block = Block("Huge.java", "\n".join("public void m%d() {}" % i for i in range(2000)))
    parts = split_oversized(block, TOK, limit=500)
    assert len(parts) > 1
    for part in parts:
        assert TOK.estimate(part.rendered()).tokens <= 500, f"{part.name} 仍超限"


def test_plan_batches_groups_files():
    files = {f"f{i}.java": "z" * 320 for i in range(5)}
    batches, needs_split = plan_batches(files, TOK, limit=400)
    assert not needs_split
    assert sum(len(b) for b in batches) == 5
    assert all(len(b) >= 1 for b in batches)


def test_build_task_context_sets_expected_tokens():
    ctx = build_task_context(
        task_id="t",
        phase="P1",
        system="你是分析助手",
        blocks=[Block("A.java", "class A {}")],
        tokenizer=TOK,
        budget=Budget(),
        effort=EffortLevel.LOW,
    )
    assert ctx.expected_prompt_tokens == TOK.estimate(ctx.prompt_text()).tokens
    assert ctx.num_ctx == 92160
    assert ctx.effort is EffortLevel.LOW
    assert ctx.max_output_tokens == 8192


def test_build_task_context_rejects_overflow():
    with pytest.raises(ContextOverflowError) as exc:
        build_task_context(
            task_id="too-big",
            blocks=[Block("Huge.java", "q" * 400_000)],
            tokenizer=TOK,
            budget=Budget(input_budget=10_000),
        )
    assert exc.value.tokens > 10_000
    assert exc.value.task_id == "too-big"


def test_summaries_are_prepended():
    ctx = build_task_context(
        task_id="t",
        blocks=[Block("A.java", "class A {}")],
        summaries=["上游结论：4 个模块"],
        tokenizer=TOK,
    )
    assert ctx.user.index("上游摘要#1") < ctx.user.index("A.java")
