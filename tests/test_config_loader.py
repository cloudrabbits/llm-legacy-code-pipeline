"""配置与画像加载单元测试。"""

from __future__ import annotations

import pytest

from pipeline.config_loader import (
    build_headers,
    load_budget,
    load_profile,
    resolve_profile_path,
)
from pipeline.errors import ConfigError
from pipeline.models import EffortLevel
from pipeline.profiles import build_profile
from pipeline.util import get_path

PROFILES = ["deepseek_sim_qwen38", "ollama_qwen38"]


def test_budget_values_match_spec():
    budget = load_budget("config/budget.yaml")
    assert budget.context_window == 92160
    assert budget.input_budget == 80000
    assert budget.max_output_tokens == 8192


def test_resolve_profile_path_by_name():
    for name in PROFILES:
        assert resolve_profile_path(name).endswith(f"{name}.yaml")


def test_resolve_profile_path_unknown():
    with pytest.raises(ConfigError):
        resolve_profile_path("no_such_profile")


@pytest.mark.parametrize("name", PROFILES)
def test_profile_loads(name):
    cfg = load_profile(name)
    assert cfg.name == name
    assert cfg.endpoint
    assert cfg.model
    assert cfg.response.text and cfg.response.finish_reason


def test_deepseek_effort_mapping_matches_official_doc():
    """官方：medium->high；off 不得携带 reasoning_effort（OpenAI 格式不接受 none）。"""
    profile = build_profile("deepseek_sim_qwen38", with_auth=False)
    assert profile.map_effort(EffortLevel.OFF) == {"thinking.type": "disabled", "reasoning_effort": None}
    assert profile.map_effort(EffortLevel.LOW)["reasoning_effort"] == "low"
    assert profile.map_effort(EffortLevel.MEDIUM)["reasoning_effort"] == "high"
    assert profile.map_effort(EffortLevel.XHIGH)["reasoning_effort"] == "max"


def test_off_level_removes_reasoning_effort_field():
    """关闭思考时，请求体里不得残留 reasoning_effort。"""
    from pipeline.models import TaskContext

    profile = build_profile("deepseek_sim_qwen38", with_auth=False)
    spec = profile.build_request(TaskContext(task_id="x", user="q", effort=EffortLevel.OFF))
    assert "reasoning_effort" not in spec.payload
    assert get_path(spec.payload, "thinking.type") == "disabled"


def test_ollama_effort_mapping():
    profile = build_profile("ollama_qwen38", with_auth=False)
    assert profile.map_effort(EffortLevel.OFF) == {"think": False}
    assert profile.map_effort(EffortLevel.MEDIUM) == {"think": True, "reasoning_effort": "medium"}


def test_ollama_sends_num_ctx_per_request():
    from pipeline.models import TaskContext

    profile = build_profile("ollama_qwen38", with_auth=False)
    spec = profile.build_request(TaskContext(task_id="x", user="q", num_ctx=92160, max_output_tokens=4096))
    assert get_path(spec.payload, "options.num_ctx") == 92160
    assert get_path(spec.payload, "options.num_predict") == 4096


def test_prompt_comparability_flag():
    """DeepSeek 计数与 Qwen 估算不可比 -> false；Ollama 同源 -> true。"""
    assert build_profile("deepseek_sim_qwen38", with_auth=False).prompt_comparable is False
    assert build_profile("ollama_qwen38", with_auth=False).prompt_comparable is True


def test_build_headers_uses_secrets_file():
    cfg = load_profile("deepseek_sim_qwen38")
    headers = build_headers(cfg)
    assert headers["Authorization"].startswith("Bearer ")
    assert headers["Content-Type"] == "application/json"


def test_build_headers_missing_secret_raises(tmp_path):
    """密钥三处来源（环境变量 / 密钥文件 / 默认文件）都拿不到时必须快速失败。"""
    from pipeline.config_loader import AuthConfig

    missing = str(tmp_path / "nope.yaml")
    cfg = load_profile("deepseek_sim_qwen38").model_copy(
        update={
            "auth": AuthConfig(
                type="bearer",
                token_env="NO_SUCH_ENV_VAR_XYZ",
                token_file=missing,
                token_key="deepseek.api_key",
            )
        }
    )
    with pytest.raises(ConfigError):
        build_headers(cfg, secrets_path=missing, env={})
