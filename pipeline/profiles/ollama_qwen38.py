"""内网生产画像（阶段二）。

目标：局域网单卡 L20 + Ollama + qwen3.8:27b（family qwen35 / 27.3B / Q4_K_M）。

与外网画像的差异**只存在于 config/profiles/ollama_qwen38.yaml**：
    * endpoint  -> http://127.0.0.1:11434/api/chat
    * request_map.num_ctx                -> options.num_ctx（逐请求显式下发）
    * request_map.max_output_tokens      -> options.num_predict
    * effort payload                     -> think 布尔 + reasoning_effort
    * response                           -> message.content / message.thinking / done_reason
                                            prompt_eval_count / eval_count / done

切换后端 = `--profile ollama_qwen38`，Python 代码零改动。
"""

from __future__ import annotations

from typing import Mapping

from ..config_loader import ProfileConfig, build_headers, load_profile
from .base import JsonChatProfile

__all__ = ["CONFIG_FILE", "build"]

CONFIG_FILE = "config/profiles/ollama_qwen38.yaml"


def build(
    *,
    secrets_path: str | None = None,
    env: Mapping[str, str] | None = None,
    cfg: ProfileConfig | None = None,
    headers: Mapping[str, str] | None = None,
    with_auth: bool = True,
) -> JsonChatProfile:
    """构造内网生产画像。参数含义同 `deepseek_sim_qwen38.build`。"""
    if cfg is None:
        cfg = load_profile(CONFIG_FILE, secrets_path=secrets_path, env=env)
    if headers is None:
        headers = build_headers(cfg, secrets_path=secrets_path, env=env) if with_auth else {}
    return JsonChatProfile(cfg, headers)
