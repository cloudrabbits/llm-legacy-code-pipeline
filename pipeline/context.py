"""上下文装配与预算内装箱。

职责：把「系统提示 + 跨会话摘要 + 若干输入块」拼成一个 TaskContext，
并保证它在**客户端**就不超过输入预算。超限直接抛 ContextOverflowError，
由 planner 细分后重排——绝不把超限请求发给后端。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from .errors import ContextOverflowError
from .models import Budget, EffortLevel, TaskContext, Phase

__all__ = ["Block", "render_blocks", "pack_blocks", "split_oversized", "plan_batches", "build_task_context"]


@dataclass
class Block:
    """一个带名字的输入块（通常是一个文件或一段摘录）。"""

    name: str
    text: str

    def rendered(self) -> str:
        return f"===== {self.name} =====\n{self.text}"


def render_blocks(blocks: Sequence[Block]) -> str:
    """把若干块渲染成一段带分隔头的文本。"""
    return "\n\n".join(b.rendered() for b in blocks)


def _estimate(tokenizer, text: str) -> int:
    return tokenizer.estimate(text).tokens


def split_oversized(block: Block, tokenizer, limit: int) -> list[Block]:
    """把单块超限的输入按行切成若干子块，尽量填满但不超过 limit。"""
    parts: list[Block] = []
    buffer: list[str] = []
    current = _estimate(tokenizer, block.rendered())
    # 子块的头部（===== name#partN =====）也占 token，装箱时必须算进去
    header_cost = _estimate(tokenizer, Block(name=f"{block.name}#part999", text="").rendered())

    def flush(idx: int) -> None:
        if buffer:
            parts.append(Block(name=f"{block.name}#part{idx}", text="\n".join(buffer)))

    idx = 1
    for line in block.text.splitlines():
        candidate = buffer + [line]
        estimate = _estimate(tokenizer, Block(name=block.name, text="\n".join(candidate)).rendered()) + header_cost
        if estimate > limit and buffer:
            flush(idx)
            idx += 1
            buffer = [line]
        else:
            buffer = candidate
    flush(idx)
    if not parts:  # 单行就超限：按字符硬切，保证一定能推进
        chars_per_token = max(1.0, len(block.text) / max(1, current))
        size = int(limit * chars_per_token * 0.9)
        size = max(1, size)
        chunks = math.ceil(len(block.text) / size)
        parts = [
            Block(name=f"{block.name}#slice{i + 1}", text=block.text[i * size : (i + 1) * size])
            for i in range(chunks)
        ]
    return parts


def pack_blocks(
    blocks: Sequence[Block],
    tokenizer,
    limit: int,
) -> tuple[list[list[Block]], list[Block]]:
    """贪心装箱。

    Returns:
        (chunks, oversized)：chunks 是若干「估算 ≤ limit」的块组；
        oversized 是单块就超限、需要 `split_oversized` 进一步切分的块。
    """
    chunks: list[list[Block]] = []
    oversized: list[Block] = []
    current: list[Block] = []
    current_tokens = 0

    for block in blocks:
        cost = _estimate(tokenizer, block.rendered())
        if cost > limit:
            oversized.append(block)
            continue
        if current and current_tokens + cost > limit:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(block)
        current_tokens += cost

    if current:
        chunks.append(current)
    return chunks, oversized


def plan_batches(
    file_texts: Mapping[str, str],
    tokenizer,
    limit: int,
) -> tuple[list[list[str]], list[str]]:
    """把「文件名 -> 正文」切成若干批，每批估算不超过 limit。

    Returns:
        (batches, needs_split)：batches 是文件名分组；
        needs_split 是单文件就超限、需要在文件内再切的文件名。
    """
    blocks = [Block(name=name, text=text) for name, text in file_texts.items()]
    chunks, oversized = pack_blocks(blocks, tokenizer, limit)
    batches = [[b.name for b in chunk] for chunk in chunks]
    return batches, [b.name for b in oversized]


def build_task_context(
    *,
    task_id: str,
    phase: Phase = "P1",
    system: str = "",
    blocks: Sequence[Block] = (),
    summaries: Sequence[str] = (),
    tokenizer,
    budget: Budget | None = None,
    effort: EffortLevel = EffortLevel.MEDIUM,
    max_output_tokens: int | None = None,
    timeout_sec: float = 900.0,
    route: str = "local",
    extra: Mapping[str, object] | None = None,
) -> TaskContext:
    """装配 TaskContext，并在客户端做预算钳制。

    Raises:
        ContextOverflowError: 装配结果超出输入预算（请求不会发出）。
    """
    budget = budget or Budget()
    if max_output_tokens is None:
        max_output_tokens = budget.max_output_tokens

    all_blocks: list[Block] = []
    for i, summary in enumerate(summaries):
        all_blocks.append(Block(name=f"上游摘要#{i + 1}", text=summary))
    all_blocks.extend(blocks)

    user = render_blocks(all_blocks)
    ctx = TaskContext(
        task_id=task_id,
        phase=phase,
        system=system,
        user=user,
        effort=effort,
        max_output_tokens=max_output_tokens,
        timeout_sec=timeout_sec,
        num_ctx=budget.context_window,
        route=route,
        extra=dict(extra or {}),
    )

    content_tokens = _estimate(tokenizer, ctx.prompt_text())
    ctx.expected_prompt_tokens = content_tokens
    budget_tokens = content_tokens + budget.envelope_overhead
    if budget_tokens > budget.input_budget:
        raise ContextOverflowError(budget_tokens, budget.input_budget, task_id)
    return ctx
