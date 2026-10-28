"""本地 Ollama 验证画像。

目标：本机 Ollama + qwen3.6-35B-A3B（Qwen3 MoE，原生上下文 262144）。

与外网画像的差异**只存在于 config/profiles/ollama_qwen36_a3b.yaml**：
    * endpoint  -> http://127.0.0.1:11434/api/chat
    * request_map.num_ctx                -> options.num_ctx（逐请求显式下发）
    * request_map.max_output_tokens      -> options.num_predict
    * effort payload                     -> think 布尔 + reasoning_effort
    * response                           -> message.content / message.thinking / done_reason
                                            prompt_eval_count / eval_count / done

报文形状由 cfg.transport=ollama_native 驱动，与画像名无关；
Python 代码零改动，切换后端 = `--profile ollama_qwen36_a3b`。
"""

from __future__ import annotations

from typing import Mapping

from ..config_loader import ProfileConfig, build_headers, load_profile
from .base import JsonChatProfile

__all__ = ["CONFIG_FILE", "build"]

CONFIG_FILE = "config/profiles/ollama_qwen36_a3b.yaml"


def build(
    *,
    secrets_path: str | None = None,
    env: Mapping[str, str] | None = None,
    cfg: ProfileConfig | None = None,
    headers: Mapping[str, str] | None = None,
    with_auth: bool = True,
) -> JsonChatProfile:
    """构造本地 Ollama 验证画像。参数含义同 ollama_qwen38.build。"""
    if cfg is None:
        cfg = load_profile(CONFIG_FILE, secrets_path=secrets_path, env=env)
    if headers is None:
        headers = build_headers(cfg, secrets_path=secrets_path, env=env) if with_auth else {}
    return JsonChatProfile(cfg, headers)
