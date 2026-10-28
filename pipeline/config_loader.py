"""配置外置加载：YAML -> pydantic。

约定：
    * 路径与密钥一律不放代码里；字符串中的 `${VAR}` 由环境变量或
      `config/secrets.local.yaml`（已 gitignore）插值填充。
    * profile 可以按名字（`deepseek_sim_qwen38`）或绝对路径指定。
"""

from __future__ import annotations

import os
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .errors import ConfigError
from .models import Budget
from .util import get_path

__all__ = [
    "AuthConfig",
    "EffortToggle",
    "EffortMap",
    "RequestMap",
    "ResponseMap",
    "ProfileConfig",
    "load_yaml",
    "load_profile",
    "load_budget",
    "resolve_profile_path",
    "build_headers",
]

DEFAULT_PROFILE_DIR = os.path.join("config", "profiles")
DEFAULT_SECRETS_PATH = os.path.join("config", "secrets.local.yaml")


class AuthConfig(BaseModel):
    """鉴权方式。密钥本身永不进代码，只在这里声明去哪儿取。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["bearer", "none"] = "bearer"
    token_env: str | None = None
    token_file: str | None = None
    token_key: str | None = None
    header_name: str = "Authorization"
    header_prefix: str = "Bearer"


class EffortToggle(BaseModel):
    """推理开关在请求体中的落位与「开启值」。

    有了它，契约测试可以用**同一段后端无关的代码**判断某个请求是否开启了推理，
    从而断言 `effort=off` 时后端确实没被要求思考。
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    enabled_value: Any = True


class EffortMap(BaseModel):
    """推理档位映射表（配置化，不写死）。

    mode=enum：`payload` 以 effort 档位为键，值是「点号路径 -> 值」的字典，
               值为 `null` 表示该字段不发送。
               例（DeepSeek OpenAI 格式）：
                   off:    {thinking.type: disabled}
                   medium: {thinking.type: enabled, reasoning_effort: high}

    mode=bool：先由 `level_to_bool` 把档位压成布尔双态，再取 `payload["true"/"false"]`。
               用于内网若为初版 Qwen3-27B（只支持 think 开/关）的场景。
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["enum", "bool"] = "enum"
    payload: dict[str, dict[str, Any]] = Field(default_factory=dict)
    level_to_bool: dict[str, bool] = Field(default_factory=dict)
    reasoning_toggle: EffortToggle | None = None


class RequestMap(BaseModel):
    """请求字段的落位路径（点号路径）。

    把「报文形状」也做成配置后，两种后端可以共用同一个 profile 类，
    编排器与适配器里彻底不需要出现任何后端判别分支。
    值为 null 表示该字段不发送（如 DeepSeek 无 num_ctx 概念，由客户端钳制代替）。
    """

    model_config = ConfigDict(extra="forbid")

    messages: str = "messages"
    max_output_tokens: str | None = "max_tokens"
    num_ctx: str | None = None


class ResponseMap(BaseModel):
    """原始响应 -> 归一化字段的取值路径（点号路径）。"""

    model_config = ConfigDict(extra="forbid")

    text: str
    reasoning: str | None = None
    finish_reason: str
    prompt_tokens: str
    completion_tokens: str
    #: 响应完整性标志位路径（Ollama 的 `done`）；为 null 表示不校验
    done_flag: str | None = None
    #: 后端上报的 prompt token 是否与 Qwen 估算可比。
    #: DeepSeek 用自有 tokenizer 计数，与 Qwen 估算不可比 -> false（不误报 SUSPECT）
    prompt_comparable: bool = True
    #: 原始 finish_reason -> 归一化值的别名表
    finish_reason_aliases: dict[str, str] = Field(
        default_factory=lambda: {"stop": "stop", "length": "length", "eos": "stop", "model_length": "length"}
    )


class ProfileConfig(BaseModel):
    """一个后端画像的完整声明。所有后端差异都收敛到这里。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    transport: str
    endpoint: str
    model: str
    auth: AuthConfig = Field(default_factory=AuthConfig)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    effort: EffortMap = Field(default_factory=EffortMap)
    request_map: RequestMap = Field(default_factory=RequestMap)
    response: ResponseMap
    #: 每次请求都要带的默认字段（如 stream=false）
    request_defaults: dict[str, Any] = Field(default_factory=dict)
    #: 后端专属 options（Ollama 的 num_ctx/num_predict 等）
    options: dict[str, Any] = Field(default_factory=dict)
    #: 覆盖全局预算（一般为空；非空仅用于临时调参）
    clamp: dict[str, int] = Field(default_factory=dict)
    notes: str = ""


# --------------------------------------------------------------------------- 加载


def load_yaml(path: str) -> dict[str, Any]:
    """读取 YAML 文件；不存在或结构非法时抛 ConfigError。"""
    if not os.path.exists(path):
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 解析失败: {path}: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是映射: {path}")
    return data


def _flatten_secrets(node: Any, prefix: str = "") -> dict[str, str]:
    """把嵌套的 secrets 结构摊平成 `deepseek.api_key` 形式的键，供 ${} 插值。"""
    out: dict[str, str] = {}
    if isinstance(node, Mapping):
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, Mapping):
                out.update(_flatten_secrets(v, key))
            elif v is not None:
                out[key] = str(v)
    return out


def _interpolate(node: Any, values: Mapping[str, str]) -> Any:
    """递归替换 `${VAR}`；未定义的变量保留原样（便于后续报错定位）。"""
    if isinstance(node, str):
        out = node
        for k, v in values.items():
            out = out.replace("${" + k + "}", v)
        return out
    if isinstance(node, list):
        return [_interpolate(x, values) for x in node]
    if isinstance(node, dict):
        return {k: _interpolate(v, values) for k, v in node.items()}
    return node


def resolve_profile_path(name_or_path: str, profile_dir: str = DEFAULT_PROFILE_DIR) -> str:
    """按名字或直接路径解析画像文件路径。"""
    if os.path.exists(name_or_path):
        return name_or_path
    candidate = os.path.join(profile_dir, f"{name_or_path}.yaml")
    if os.path.exists(candidate):
        return candidate
    raise ConfigError(f"找不到画像: {name_or_path}（也试过 {candidate}）")


def load_profile(
    name_or_path: str,
    *,
    secrets_path: str | None = DEFAULT_SECRETS_PATH,
    env: Mapping[str, str] | None = None,
    profile_dir: str = DEFAULT_PROFILE_DIR,
) -> ProfileConfig:
    """加载并校验画像配置，完成密钥插值。"""
    path = resolve_profile_path(name_or_path, profile_dir)
    raw = load_yaml(path)

    values: dict[str, str] = dict(env if env is not None else os.environ)
    if secrets_path and os.path.exists(secrets_path):
        values.update(_flatten_secrets(load_yaml(secrets_path)))
    raw = _interpolate(raw, values)

    try:
        return ProfileConfig(**raw)
    except Exception as exc:  # pydantic 的 ValidationError，此处统一转成本项目异常
        raise ConfigError(f"画像配置校验失败: {path}: {exc}") from exc


def build_headers(
    cfg: ProfileConfig,
    *,
    secrets_path: str | None = DEFAULT_SECRETS_PATH,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """按 auth 配置拼出请求头；拿不到密钥时抛 ConfigError（快速失败）。"""
    headers = {"Content-Type": "application/json"}
    headers.update(cfg.extra_headers)
    if cfg.auth.type == "none":
        return headers

    token: str | None = None
    if cfg.auth.token_env:
        token = (env if env is not None else os.environ).get(cfg.auth.token_env)
    if token is None and cfg.auth.token_file and cfg.auth.token_key:
        resolved = cfg.auth.token_file
        if not os.path.isabs(resolved) and os.path.exists(os.path.join("config", os.path.basename(resolved))):
            resolved = os.path.join("config", os.path.basename(resolved))
        if os.path.exists(resolved):
            token = get_path(load_yaml(resolved), cfg.auth.token_key)
    if token is None and cfg.auth.token_key:
        token = get_path(load_yaml(secrets_path), cfg.auth.token_key) if (
            secrets_path and os.path.exists(secrets_path)
        ) else None
    if not token:
        raise ConfigError(
            f"画像 {cfg.name} 需要密钥但未取到：env={cfg.auth.token_env} "
            f"file={cfg.auth.token_file} key={cfg.auth.token_key}"
        )
    prefix = cfg.auth.header_prefix
    headers[cfg.auth.header_name] = f"{prefix} {token}".strip()
    return headers


def load_budget(path: str) -> Budget:
    """加载全局预算 `config/budget.yaml`。"""
    try:
        return Budget(**load_yaml(path))
    except Exception as exc:
        raise ConfigError(f"预算配置校验失败: {path}: {exc}") from exc
