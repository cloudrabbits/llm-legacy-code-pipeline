"""后端画像基类与请求/响应规格。

所有后端差异（端点、报文形状、effort 参数形态、响应字段落位）都在
`ProfileConfig` 里声明，本文件只提供**通用**的装配与归一化逻辑。
因此编排器与 `backend.py` 里不需要、也不允许出现任何后端判别分支。
"""

from __future__ import annotations

import abc
import copy
from dataclasses import dataclass, field
from typing import Any, Mapping

from ..config_loader import ProfileConfig
from ..errors import BackendError
from ..models import EffortLevel, FinishReason, TaskContext, Usage
from ..util import get_path, set_path, unset_path

__all__ = ["RequestSpec", "Normalized", "BackendProfile", "JsonChatProfile"]


@dataclass
class RequestSpec:
    """一次 HTTP 调用的完整规格。transport 只认这个类型。"""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    timeout_sec: float = 900.0
    #: 供日志/断言使用；不含密钥
    backend_name: str = ""


@dataclass
class Normalized:
    """归一化后的响应。DeepSeek 与 Ollama 在此收敛为同一形状。"""

    text: str
    reasoning: str | None
    finish_reason: FinishReason
    usage: Usage


class BackendProfile(abc.ABC):
    """画像协议：把 TaskContext 变成 RequestSpec，把原始响应变成 Normalized。"""

    #: 画像名（写入日志与 checkpoint）
    name: str = ""

    def __init__(self, cfg: ProfileConfig, headers: Mapping[str, str] | None = None) -> None:
        self.cfg = cfg
        self.name = cfg.name
        self.headers = dict(headers or {})

    # ------------------------------------------------------------------ effort

    @property
    def prompt_comparable(self) -> bool:
        """后端上报的 prompt token 数是否可与 Qwen 估算直接比对。"""
        return self.cfg.response.prompt_comparable

    def map_effort(self, level: EffortLevel) -> dict[str, Any]:
        """把后端无关的档位映射成「点号路径 -> 值」。

        mode=enum：直接取 `payload[level]`。
        mode=bool：先由 `level_to_bool` 压成布尔双态，再取 `payload["true"/"false"]`
                  （内网若为初版 Qwen3-27B 时启用）。
        """
        em = self.cfg.effort
        if em.mode == "bool":
            flag = em.level_to_bool.get(level.value, True)
            return dict(em.payload.get("true" if flag else "false", {}))
        return dict(em.payload.get(level.value, {}))

    def effort_label(self, level: EffortLevel) -> str:
        """归一化档位字符串，写入 Result.effort_applied（两后端必须一致）。"""
        return level.value

    def reasoning_enabled(self, payload: dict[str, Any]) -> bool:
        """判断请求体是否要求了推理。供契约测试做后端无关的断言。"""
        toggle = self.cfg.effort.reasoning_toggle
        if toggle is None:
            return True
        return get_path(payload, toggle.path) == toggle.enabled_value

    def apply_effort(self, payload: dict[str, Any], level: EffortLevel) -> None:
        """把映射结果写进请求体；值为 null 的路径表示删除该字段。"""
        for path, value in self.map_effort(level).items():
            if value is None:
                unset_path(payload, path)
            else:
                set_path(payload, path, value)

    # ------------------------------------------------------------------ 请求

    @abc.abstractmethod
    def build_request(self, ctx: TaskContext) -> RequestSpec:
        """装配请求。子类只需处理报文形状差异。"""

    # ------------------------------------------------------------------ 响应

    @abc.abstractmethod
    def normalize(self, raw: dict[str, Any], ctx: TaskContext | None = None) -> Normalized:
        """把原始响应归一化。"""


class JsonChatProfile(BackendProfile):
    """JSON-over-HTTP 聊天接口的通用画像。

    DeepSeek 的 `/chat/completions` 与 Ollama 的 `/api/chat` 都落在这一形状上，
    差异全部由 `ProfileConfig.request_map` / `response` 的**路径声明**吸收。
    """

    def build_request(self, ctx: TaskContext) -> RequestSpec:
        cfg = self.cfg
        payload: dict[str, Any] = copy.deepcopy(cfg.request_defaults)

        # 后端专属 options 基线（Ollama 的 keep_alive 等）；num_ctx 之后逐请求覆盖
        for key, value in cfg.options.items():
            set_path(payload, f"options.{key}", value)

        payload["model"] = cfg.model

        messages: list[dict[str, str]] = []
        if ctx.system:
            messages.append({"role": "system", "content": ctx.system})
        messages.append({"role": "user", "content": ctx.user})
        set_path(payload, cfg.request_map.messages, messages)

        if cfg.request_map.max_output_tokens:
            set_path(payload, cfg.request_map.max_output_tokens, ctx.max_output_tokens)
        # 规格书第五节：num_ctx 逐请求显式传入，不依赖后端全局默认
        if cfg.request_map.num_ctx:
            set_path(payload, cfg.request_map.num_ctx, ctx.num_ctx)

        self.apply_effort(payload, ctx.effort)

        # 调用方覆盖项最后生效
        for path, value in (ctx.extra or {}).items():
            if value is None:
                unset_path(payload, path)
            else:
                set_path(payload, path, value)

        return RequestSpec(
            url=cfg.endpoint,
            headers=dict(self.headers),
            payload=payload,
            timeout_sec=ctx.timeout_sec,
            backend_name=self.name,
        )

    def normalize(self, raw: dict[str, Any], ctx: TaskContext | None = None) -> Normalized:
        r = self.cfg.response

        done_flag = r.done_flag
        if done_flag and get_path(raw, done_flag) is not True:
            raise BackendError("响应不完整：done 标志未置位", retryable=True, raw=raw)

        text = get_path(raw, r.text) or ""
        reasoning = get_path(raw, r.reasoning) if r.reasoning else None
        reasoning = reasoning or None  # 空串一律归一化为 None

        raw_finish = get_path(raw, r.finish_reason)
        mapped = r.finish_reason_aliases.get(str(raw_finish).lower(), "error") if raw_finish else "error"
        try:
            finish = FinishReason(mapped)
        except ValueError:
            finish = FinishReason.ERROR

        prompt_tokens = int(get_path(raw, r.prompt_tokens) or 0)
        completion_tokens = int(get_path(raw, r.completion_tokens) or 0)

        return Normalized(
            text=str(text),
            reasoning=reasoning,
            finish_reason=finish,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
        )
