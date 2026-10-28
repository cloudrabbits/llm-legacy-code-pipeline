"""契约测试的通用辅助。

关键点：这里没有任何后端专属代码。原始响应是**按画像声明的取值路径**
反向拼出来的，所以同一段代码能为两种后端构造出各自形态的响应。
"""

from __future__ import annotations

from typing import Any

from pipeline.profiles.base import BackendProfile
from pipeline.util import set_path

__all__ = ["make_raw_response"]


def make_raw_response(
    profile: BackendProfile,
    *,
    text: str = "",
    reasoning: str | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    done: bool = True,
) -> dict[str, Any]:
    """按画像的 response 路径声明拼出一份原始响应。"""
    r = profile.cfg.response
    raw: dict[str, Any] = {}

    set_path(raw, r.text, text)
    if r.reasoning and reasoning:
        set_path(raw, r.reasoning, reasoning)
    if finish_reason is not None:
        set_path(raw, r.finish_reason, finish_reason)
    set_path(raw, r.prompt_tokens, prompt_tokens)
    set_path(raw, r.completion_tokens, completion_tokens)
    if r.done_flag:
        set_path(raw, r.done_flag, done)
    return raw
