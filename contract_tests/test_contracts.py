"""后端无关契约测试（规格书第七节）。

四条断言在 `deepseek_sim_qwen38` 与 `ollama_qwen38` 下都必须通过。
跑法：
    python -m pytest contract_tests -q
"""

from __future__ import annotations

import pytest

from pipeline.errors import ContextOverflowError
from pipeline.executor import RetryPolicy, run_task
from pipeline.errors import BackendTimeoutError
from pipeline.models import EffortLevel, FinishReason, TaskContext, TaskStatus

from .conftest import PROFILES, build_backend, noop_sleep
from .helpers import make_raw_response

# --------------------------------------------------------------------------- 1


def test_budget_clamp_79k_ok_81k_rejected(profile_name, tokenizer, budget):
    """79K 输入成功；81K 被**客户端**拒绝，且不得发出任何请求。

    这是仿真有效性的核心：DeepSeek 真实窗口远大于此，绝不能因为
    自己吃得下就吞掉超限任务。
    """
    calls: list = []

    def factory(backend, spec):
        calls.append(spec)
        return make_raw_response(
            backend.profile, text="ok", finish_reason="stop", prompt_tokens=1000, completion_tokens=64
        )

    backend = build_backend(profile_name, factory, tokenizer, budget)

    ok_text = tokenizer.materialize(budget.input_budget - 2000)
    ok_task = TaskContext(task_id="ok-79k", user=ok_text, max_output_tokens=1024)
    result = backend.complete(ok_task)
    assert result.finish_reason is FinishReason.STOP
    assert len(calls) == 1, "79K 任务应当真正发出一次请求"

    over_text = tokenizer.materialize(budget.input_budget + 1000)
    over_task = TaskContext(task_id="over-81k", user=over_text, max_output_tokens=1024)
    with pytest.raises(ContextOverflowError) as exc_info:
        backend.complete(over_task)

    assert exc_info.value.tokens > budget.input_budget
    assert len(calls) == 1, "超限任务不得发出任何请求"


# --------------------------------------------------------------------------- 2


def test_truncation_behaviour_identical(profile_name, tokenizer, budget):
    """max_tokens=2048 时截断行为一致，finish_reason 归一化。"""
    state = {"mode": "truncated"}

    def factory(backend, spec):
        if state["mode"] == "truncated":
            return make_raw_response(
                backend.profile,
                text="x" * 100,
                finish_reason="length",
                prompt_tokens=500,
                completion_tokens=2048,
            )
        return make_raw_response(
            backend.profile,
            text="done",
            finish_reason="stop",
            prompt_tokens=500,
            completion_tokens=120,
        )

    backend = build_backend(profile_name, factory, tokenizer, budget)

    truncated = backend.complete(TaskContext(task_id="t1", user="hi", max_output_tokens=2048))
    assert truncated.finish_reason is FinishReason.LENGTH, "length 必须归一化为 FinishReason.LENGTH"
    assert truncated.truncated is True
    assert "TRUNCATED" in truncated.flags

    state["mode"] = "normal"
    normal = backend.complete(TaskContext(task_id="t2", user="hi", max_output_tokens=2048))
    assert normal.finish_reason is FinishReason.STOP
    assert normal.truncated is False
    assert "TRUNCATED" not in normal.flags


# --------------------------------------------------------------------------- 3


@pytest.mark.parametrize(
    "level,expect_reasoning",
    [(EffortLevel.OFF, False), (EffortLevel.MEDIUM, True)],
)
def test_effort_normalized(profile_name, tokenizer, budget, level, expect_reasoning):
    """effort=off 无 reasoning；effort=medium 有 reasoning，字段归一化。

    响应里是否带推理内容，由**请求体**经画像的 reasoning_toggle 判定，
    因此这段断言对两种后端同样成立。
    """
    captured: list = []

    def factory(backend, spec):
        captured.append(spec)
        wants_reasoning = backend.profile.reasoning_enabled(spec.payload)
        return make_raw_response(
            backend.profile,
            text="answer",
            reasoning="chain-of-thought" if wants_reasoning else None,
            finish_reason="stop",
            prompt_tokens=100,
            completion_tokens=50,
        )

    backend = build_backend(profile_name, factory, tokenizer, budget)
    result = backend.complete(TaskContext(task_id=f"e-{level.value}", user="question", effort=level))

    assert result.effort_applied == level.value, "effort_applied 必须是归一化档位，两后端一致"
    assert (result.reasoning is not None) is expect_reasoning
    if expect_reasoning:
        assert result.reasoning
    assert backend.profile.reasoning_enabled(captured[0].payload) is expect_reasoning


# --------------------------------------------------------------------------- 4


def test_timeout_retry_exhausted_semantics(profile_name, tokenizer, budget):
    """极短 timeout 触发重试，耗尽后失败语义一致。"""

    def factory(backend, spec):  # noqa: ARG001
        raise BackendTimeoutError("stub timeout", timeout_sec=0.05)

    backend = build_backend(profile_name, factory, tokenizer, budget)
    policy = RetryPolicy(max_retries=2, base_delay_sec=1.0, max_delay_sec=8.0, jitter_ratio=0.0)

    outcome = run_task(
        backend,
        TaskContext(task_id="timeout", user="q", timeout_sec=0.05),
        policy,
        sleep=noop_sleep,
    )

    assert outcome.status is TaskStatus.FAILED
    assert outcome.error_class == "TimeoutError"
    assert outcome.attempts == 3
    assert outcome.sleeps == [1.0, 2.0], "指数退避时序必须单调且确定"


# --------------------------------------------------------------------------- 附
# 迁移一致性的直接证据：同一逻辑输入在两个后端下产生逐字段相同的归一化结果。


def test_normalized_result_identical_across_profiles(tokenizer, budget):
    """两种画像对同一逻辑输入产出完全一致的归一化结果（backend_name 除外）。

    用量按估算值回填，避免触发 SUSPECT——SUSPECT 的可比性差异由下一个测试单独界定。
    """
    snapshots = {}
    for name in PROFILES:
        task = TaskContext(task_id="same", phase="P2", user="同一份输入", effort=EffortLevel.MEDIUM)

        def factory(backend, spec, task=task):
            wants = backend.profile.reasoning_enabled(spec.payload)
            return make_raw_response(
                backend.profile,
                text="统一答案",
                reasoning="推理链" if wants else None,
                finish_reason="stop",
                prompt_tokens=backend.estimate(task).tokens,
                completion_tokens=88,
            )

        backend = build_backend(name, factory, tokenizer, budget)
        payload = backend.complete(task).to_dict()
        payload.pop("backend_name")
        snapshots[name] = payload

    left, right = snapshots[PROFILES[0]], snapshots[PROFILES[1]]
    assert left == right, f"两后端归一化结果不一致：\n{left}\n{right}"


def test_suspect_flag_follows_tokenizer_comparability(tokenizer, budget):
    """SUSPECT 只在后端计数与 Qwen 估算可比时才标记。

    Ollama 的 prompt_eval_count 就是 Qwen 自己的计数 -> 可比；
    DeepSeek 用自有 tokenizer -> 系统性偏差，标记即等于误报，因此不标。
    这是**唯一**被允许的画像间行为差异，且必须显式记录在案。
    """

    def factory(backend, spec):  # noqa: ARG001
        return make_raw_response(
            backend.profile, text="x", finish_reason="stop", prompt_tokens=999_999, completion_tokens=10
        )

    flags_by = {}
    for name in PROFILES:
        backend = build_backend(name, factory, tokenizer, budget)
        flags_by[name] = backend.complete(TaskContext(task_id="s", user="q")).flags

    assert "SUSPECT" in flags_by["ollama_qwen38"]
    assert "SUSPECT" not in flags_by["deepseek_sim_qwen38"]


def test_num_ctx_sent_per_request_when_declared(tokenizer, budget):
    """num_ctx 必须逐请求显式下发（画像声明了该落位时），不依赖后端全局默认。"""
    from pipeline.util import get_path

    for name in PROFILES:
        captured: list = []

        def factory(backend, spec):
            captured.append(spec)
            return make_raw_response(
                backend.profile, text="ok", finish_reason="stop", prompt_tokens=10, completion_tokens=5
            )

        backend = build_backend(name, factory, tokenizer, budget)
        backend.complete(TaskContext(task_id="ctx", user="x", num_ctx=92160))
        spec = captured[0]
        declared = backend.profile.cfg.request_map.num_ctx
        if declared:
            assert get_path(spec.payload, declared) == 92160, f"{name} 未逐请求下发 num_ctx"
        assert spec.payload["model"] == backend.profile.cfg.model
