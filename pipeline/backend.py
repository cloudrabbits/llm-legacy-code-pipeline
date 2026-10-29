"""后端薄适配器。

统一接口：

    backend.complete(task: TaskContext) -> Result

执行顺序固定，且与后端无关：
    1. Qwen tokenizer 估算 prompt（含消息封装开销）
    2. 与输入预算比对，超限直接抛 ContextOverflowError —— **不发出任何请求**
    3. 画像装配请求 -> 传输
    4. 画像归一化响应
    5. 截断校验（TRUNCATED）与用量偏差校验（SUSPECT）
"""

from __future__ import annotations

import os
from typing import Mapping

from .config_loader import load_budget, load_profile
from .errors import ContextOverflowError
from .models import (
    FLAG_SUSPECT,
    FLAG_TRUNCATED,
    Budget,
    EffortLevel,
    FinishReason,
    Result,
    TaskContext,
    TokenEstimate,
)
from .profiles import build_profile
from .profiles.base import BackendProfile, JsonChatProfile
from .tokenizer import Tokenizer
from .transports import Transport, get_transport

__all__ = ["Backend"]

DEFAULT_BUDGET_PATH = os.path.join("config", "budget.yaml")


class Backend:
    """后端无关的调用入口。编排器只持有这一个对象。"""

    def __init__(
        self,
        profile: BackendProfile,
        budget: Budget | None = None,
        tokenizer: Tokenizer | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.profile = profile
        self.budget = self._resolve_budget(budget, profile)
        self.tokenizer = tokenizer or Tokenizer()
        self.transport = transport

    # ------------------------------------------------------------------ 构造

    @staticmethod
    def _resolve_budget(budget: Budget | None, profile: BackendProfile) -> Budget:
        """预算以全局 `config/budget.yaml` 为准，画像可用 `clamp` 覆盖单字段。"""
        base = budget or Budget()
        clamp = getattr(profile.cfg, "clamp", None) or {}
        if clamp:
            base = base.model_copy(update={k: int(v) for k, v in clamp.items() if hasattr(base, k)})
        return base

    @classmethod
    def from_profile(
        cls,
        profile_name: str,
        *,
        budget_path: str = DEFAULT_BUDGET_PATH,
        tokenizer: Tokenizer | None = None,
        transport: Transport | None = None,
        secrets_path: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "Backend":
        """按画像名构造（生产路径）。"""
        profile = build_profile(profile_name, secrets_path=secrets_path, env=env)
        budget = load_budget(budget_path) if os.path.exists(budget_path) else Budget()
        if transport is None:
            transport = get_transport(profile.cfg.transport)
        return cls(profile, budget, tokenizer, transport)

    @classmethod
    def for_testing(
        cls,
        profile_name: str,
        *,
        responder,
        tokenizer: Tokenizer | None = None,
        budget: Budget | None = None,
        secrets_path: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "Backend":
        """构造带桩传输的后端（契约测试路径）。不发网络请求。"""
        profile = build_profile(profile_name, secrets_path=secrets_path, env=env, with_auth=False)
        transport = get_transport("stub", responder=responder)
        return cls(profile, budget or Budget(), tokenizer, transport)

    # ------------------------------------------------------------------ 估算

    def estimate(self, task: TaskContext) -> TokenEstimate:
        """正文 prompt 的 token 估算（不含消息封装开销）。

        封装开销只在**预算判定**时叠加（见 `budget_tokens`），不参与
        与后端上报用量的偏差比对——否则小任务会被 512 的常量开销淹没。
        """
        return self.tokenizer.estimate(task.prompt_text())

    def budget_tokens(self, task: TaskContext) -> int:
        """参与预算判定的 token 数：正文估算 + 消息封装开销。"""
        return self.estimate(task).tokens + self.budget.envelope_overhead

    # ------------------------------------------------------------------ 调用

    def complete(self, task: TaskContext) -> Result:
        """执行一次调用。

        Raises:
            ContextOverflowError: 估算超出输入预算（请求不会发出）。
            BackendTimeoutError: 超时。
            BackendError: HTTP / 结构异常。
        """
        estimate = self.estimate(task)
        budget_tokens = self.budget_tokens(task)
        if budget_tokens > self.budget.input_budget:
            raise ContextOverflowError(budget_tokens, self.budget.input_budget, task.task_id)

        spec = self.profile.build_request(task)
        response = self.transport.send(spec)  # type: ignore[union-attr]
        normalized = self.profile.normalize(response.raw, task)

        flags: list[str] = []
        truncated = (
            normalized.finish_reason is FinishReason.LENGTH
            or normalized.usage.completion_tokens >= max(1, task.max_output_tokens) - 1
        )
        if truncated:
            flags.append(FLAG_TRUNCATED)

        expected = task.expected_prompt_tokens or estimate.tokens  # 正文估算，不含封装开销
        deviation: float | None = None
        if normalized.usage.prompt_tokens and expected:
            deviation = abs(normalized.usage.prompt_tokens - expected) / expected
            # 仅在后端计数与 Qwen 估算可比时才升级为 SUSPECT（DeepSeek 不可比）
            if self.profile.prompt_comparable and deviation > 0.05:
                flags.append(FLAG_SUSPECT)

        return Result(
            task_id=task.task_id,
            backend_name=self.profile.name,
            effort_applied=self.profile.effort_label(task.effort),
            text=normalized.text,
            reasoning=normalized.reasoning,
            finish_reason=normalized.finish_reason,
            usage=normalized.usage,
            truncated=truncated,
            flags=flags,
            prompt_deviation=deviation,
            latency_ms=response.latency_ms,
            prefill_ms=normalized.prefill_ms,
            decode_ms=normalized.decode_ms,
            attempt=1,
            route=task.route,
            raw=response.raw,
        )
