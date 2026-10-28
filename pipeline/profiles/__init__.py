"""画像注册表。

键是**报文形状**（transport 名），不是厂商名——这样 `backend.py` 里
既没有厂商分支，也没有厂商字符串。
"""

from __future__ import annotations

from typing import Callable, Mapping

from ..config_loader import ProfileConfig, build_headers
from .base import BackendProfile, JsonChatProfile, Normalized, RequestSpec

__all__ = ["BackendProfile", "JsonChatProfile", "RequestSpec", "Normalized", "build_profile", "PROFILE_MODULES"]

#: 画像名 -> 装配函数（延迟导入，避免加载未使用的画像时触发配置校验）
PROFILE_MODULES: dict[str, str] = {
    "deepseek_sim_qwen38": "pipeline.profiles.deepseek_sim_qwen38",
    "ollama_qwen38": "pipeline.profiles.ollama_qwen38",
    "ollama_qwen36_a3b": "pipeline.profiles.ollama_qwen36_a3b",
}


def build_profile(
    name: str,
    *,
    secrets_path: str | None = None,
    env: Mapping[str, str] | None = None,
    with_auth: bool = True,
) -> BackendProfile:
    """按画像名装配后端画像。未知的画像名抛 ConfigError。"""
    from importlib import import_module

    from ..errors import ConfigError

    module_path = PROFILE_MODULES.get(name)
    if module_path is None:
        raise ConfigError(f"未注册的画像: {name}；可用: {sorted(PROFILE_MODULES)}")
    factory: Callable[..., BackendProfile] = import_module(module_path).build
    return factory(secrets_path=secrets_path, env=env, with_auth=with_auth)


def build_from_config(cfg: ProfileConfig, headers: Mapping[str, str] | None = None) -> BackendProfile:
    """从已加载的配置直接构造（测试 / 内嵌场景）。

    报文形状由 `cfg.transport` 决定，与画像名无关，因此这里没有任何厂商分支。
    """
    return JsonChatProfile(cfg, headers if headers is not None else build_headers(cfg))
