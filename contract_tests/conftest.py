"""契约测试公共 fixture。

同一套断言在**两种画像**下各跑一遍——这是「迁移一致性」的证据：
只要两边都绿，把 `--profile` 从外网切到内网就不应改变编排行为。
"""

from __future__ import annotations

import os
from typing import Any, Callable

import pytest

from pipeline.backend import Backend
from pipeline.config_loader import load_budget
from pipeline.models import Budget
from pipeline.tokenizer import Tokenizer

#: 参与契约校验的画像（名字即 `config/profiles/<name>.yaml`）
PROFILES = ["deepseek_sim_qwen38", "ollama_qwen38"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session", autouse=True)
def _cwd_repo_root():
    """画像/预算配置用相对路径解析，测试统一从仓库根运行。"""
    old = os.getcwd()
    os.chdir(REPO_ROOT)
    yield
    os.chdir(old)


@pytest.fixture(scope="session")
def budget() -> Budget:
    return load_budget(os.path.join("config", "budget.yaml"))


@pytest.fixture(scope="session")
def tokenizer() -> Tokenizer:
    return Tokenizer(os.path.join("models", "qwen2_bpe", "tokenizer.json"))


@pytest.fixture(params=PROFILES)
def profile_name(request) -> str:
    """两种画像参数化——每个测试自动跑两遍。"""
    return request.param


def build_backend(profile_name: str, responder_factory, tokenizer: Tokenizer, budget: Budget) -> Backend:
    """构造带桩传输的后端。

    `responder_factory` 接收 backend 自身，便于按画像的 reasoning_toggle 决定
    是否返回推理内容。
    """
    holder: dict[str, Any] = {}

    def responder(spec):
        return responder_factory(holder["backend"], spec)

    backend = Backend.for_testing(profile_name, responder=responder, tokenizer=tokenizer, budget=budget)
    holder["backend"] = backend
    return backend


def noop_sleep(_: float) -> None:
    """注入用：让退避等待为 0，测试保持确定性。"""
