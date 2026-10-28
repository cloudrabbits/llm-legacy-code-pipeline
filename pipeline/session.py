"""会话状态机。

规格书第五节第 2 条：
    单会话 ≤6 轮；会话累计 prompt_eval_count ≥70K、或切模块、或输出质量下降时
    开新会话；跨会话**不靠对话历史**，靠 `runtime/summaries/*.md`（≤4K token
    压缩摘要）+ 产物落盘传递。

因此本模块只管「什么时候该换会话」与「换的时候把摘要落到哪里」，
不维护任何 messages 历史。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import CheckpointEvent
from .util import utc_now_iso

__all__ = ["SessionPolicy", "Session", "SessionManager", "ROTATE_REASONS"]

#: 轮换原因（写入 checkpoint 的 status 字段）
ROTATE_REASONS = {
    "max_turns": "达到单会话轮次上限",
    "prompt_budget": "累计 prompt token 触顶",
    "module_switch": "切换分析模块",
    "quality_drop": "输出质量下降（验收连续失败）",
}


@dataclass
class SessionPolicy:
    max_turns: int = 6
    max_cumulative_prompt_tokens: int = 70000
    max_summary_tokens: int = 4000


@dataclass
class Session:
    """一个会话的可序列化状态。"""

    seq: int
    module: str | None = None
    turns: int = 0
    cumulative_prompt_tokens: int = 0
    started_ts: str = field(default_factory=utc_now_iso)
    consecutive_accept_failures: int = 0

    def rotate_reason(
        self,
        policy: SessionPolicy,
        *,
        module: str | None = None,
        next_prompt_tokens: int = 0,
    ) -> str | None:
        """判断**在发起下一轮之前**是否需要开新会话。返回原因或 None。

        Args:
            module: 下一个任务所属模块；与当前模块不同即轮换。
            next_prompt_tokens: 下一轮预计消耗的 prompt token。
        """
        if self.consecutive_accept_failures >= 2:
            return "quality_drop"
        if module is not None and self.module is not None and module != self.module:
            return "module_switch"
        if self.turns + 1 > policy.max_turns:
            return "max_turns"
        if self.cumulative_prompt_tokens + next_prompt_tokens >= policy.max_cumulative_prompt_tokens:
            return "prompt_budget"
        return None

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "module": self.module,
            "turns": self.turns,
            "cumulative_prompt_tokens": self.cumulative_prompt_tokens,
            "started_ts": self.started_ts,
            "consecutive_accept_failures": self.consecutive_accept_failures,
        }


class SessionManager:
    """管理会话轮换，并把轮换事件写进检查点、把摘要写进 summaries/。"""

    def __init__(
        self,
        policy: SessionPolicy | None = None,
        *,
        checkpoint=None,
        summaries=None,
        start_seq: int = 1,
        logger=None,
    ) -> None:
        self.policy = policy or SessionPolicy()
        self.checkpoint = checkpoint
        self.summaries = summaries
        self.logger = logger
        self.current_session = Session(seq=start_seq)

    # ------------------------------------------------------------------ 记录

    def record_turn(self, prompt_tokens: int, *, accepted: bool = True) -> None:
        """记录一轮：累计 prompt 用量与验收结果。"""
        self.current_session.turns += 1
        self.current_session.cumulative_prompt_tokens += int(prompt_tokens)
        if accepted:
            self.current_session.consecutive_accept_failures = 0
        else:
            self.current_session.consecutive_accept_failures += 1

    def needs_rotation(self, *, module: str | None = None, next_prompt_tokens: int = 0) -> str | None:
        return self.current_session.rotate_reason(
            self.policy, module=module, next_prompt_tokens=next_prompt_tokens
        )

    # ------------------------------------------------------------------ 轮换

    def rotate(self, reason: str, *, module: str | None = None, summary_text: str | None = None) -> Session:
        """开新会话：先落摘要，再发轮换事件。

        Args:
            reason: `ROTATE_REASONS` 的键。
            module: 新会话所属模块。
            summary_text: 当前会话的压缩摘要；提供则写入 summaries/（≤4K token）。
        """
        old = self.current_session
        summary_path = None
        if summary_text and self.summaries is not None:
            summary_path = self.summaries.write(self.summaries.session_name(old.seq, old.module), summary_text)

        new_seq = old.seq + 1
        if self.checkpoint is not None:
            self.checkpoint.append(
                CheckpointEvent(
                    event="SESSION_ROTATED",
                    status=reason,
                    session_seq=new_seq,
                    artifact=summary_path,
                    tokens={"prompt": old.cumulative_prompt_tokens},
                )
            )
        if self.logger:
            self.logger.info(
                "会话轮换 seq=%d -> %d 原因=%s 累计prompt=%d 摘要=%s",
                old.seq,
                new_seq,
                reason,
                old.cumulative_prompt_tokens,
                summary_path,
            )

        self.current_session = Session(seq=new_seq, module=module)
        return self.current_session

    def ensure(self, *, module: str | None = None, next_prompt_tokens: int = 0, summary_text: str | None = None) -> Session:
        """若需要轮换就轮换；否则把模块绑到当前会话上并返回。"""
        reason = self.needs_rotation(module=module, next_prompt_tokens=next_prompt_tokens)
        if reason:
            return self.rotate(reason, module=module, summary_text=summary_text)
        if self.current_session.module is None and module is not None:
            self.current_session.module = module
        return self.current_session
