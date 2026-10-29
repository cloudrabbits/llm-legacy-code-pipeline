"""外网仿真画像（阶段一）。

目标：用 DeepSeek V4.1-Flash 官方 API **仿真**内网 qwen3.8:28b 的能力包络。

主动放弃的能力（否则仿真无效）：
    * 超长窗口 —— 由 config/budget.yaml 钳制到 92160 / 80000，客户端拦下超限任务，
      DeepSeek 不得因为自身更大的窗口而吞下。
    * 自有 tokenizer —— 估算一律用 Qwen BPE（pipeline/tokenizer.py）。
    * 更强的推理档位 —— 档位映射按官方表走，xhigh 不追求超越 Qwen 的表现。

本模块只有配置装配逻辑，没有任何 DeepSeek 专属代码路径：
报文形状由 config/profiles/deepseek_sim_qwen38.yaml 的 request_map / response 声明。
"""

from __future__ import annotations

from typing import Mapping

from ..config_loader import ProfileConfig, build_headers, load_profile
from .base import JsonChatProfile

__all__ = ["CONFIG_FILE", "build"]

CONFIG_FILE = "config/profiles/deepseek_sim_qwen38.yaml"


def build(
    *,
    secrets_path: str | None = None,
    env: Mapping[str, str] | None = None,
    cfg: ProfileConfig | None = None,
    headers: Mapping[str, str] | None = None,
    with_auth: bool = True,
) -> JsonChatProfile:
    """构造外网仿真画像。

    Args:
        secrets_path: 密钥文件路径；None 表示用默认 `config/secrets.local.yaml`。
        env: 环境变量覆盖（测试用）。
        cfg: 已是加载好的配置，传入则不再读盘。
        headers: 直接指定请求头（测试用；会跳过鉴权拼接）。
        with_auth: False 时跳过鉴权（契约测试走 stub transport，不需要真实密钥）。
    """
    if cfg is None:
        cfg = load_profile(CONFIG_FILE, secrets_path=secrets_path, env=env)
    if headers is None:
        headers = build_headers(cfg, secrets_path=secrets_path, env=env) if with_auth else {}
    return JsonChatProfile(cfg, headers)
