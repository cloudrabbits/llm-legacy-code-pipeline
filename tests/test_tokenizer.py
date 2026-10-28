"""tokenizer 单元测试。"""

from __future__ import annotations

import os

import pytest

from pipeline.models import TokenEstimate
from pipeline.tokenizer import Tokenizer

CACHE = os.path.join("models", "qwen2_bpe", "tokenizer.json")


@pytest.fixture(scope="module")
def bpe() -> Tokenizer:
    return Tokenizer(CACHE)


@pytest.fixture(scope="module")
def heuristic() -> Tokenizer:
    return Tokenizer(prefer="heuristic")


def test_bpe_preferred_when_cache_exists(bpe):
    assert bpe.method == "bpe"
    assert bpe.safety_factor == 1.0, "精确计数不需要安全系数"


def test_heuristic_fallback_has_safety_margin(heuristic):
    assert heuristic.method == "heuristic"
    assert heuristic.safety_factor > 1.0
    est = heuristic.estimate("a" * 320)
    assert est.tokens > est.raw_tokens


def test_estimate_counts_cjk_denser(heuristic):
    """中文按 1.5 字符/token，比代码 3.2 字符/token 更密。"""
    code = "a" * 320
    cjk = "中" * 320
    assert heuristic.estimate(cjk).tokens > heuristic.estimate(code).tokens


def test_materialize_hits_target(bpe, heuristic):
    for tok in (bpe, heuristic):
        for target in (1_000, 20_000):
            text = tok.materialize(target)
            est = tok.estimate(text)
            assert est.tokens >= target
            assert est.tokens - target < 200, f"{tok.method} 超出目标过多: {est.tokens} vs {target}"


def test_materialize_monotonic_prefix(bpe):
    """估算对前缀长度单调不减——二分构造依赖该性质。"""
    text = bpe.materialize(2_000)
    prev = 0
    for cut in (0, 100, 500, 1_000, len(text)):
        cur = bpe.estimate(text[:cut]).tokens
        assert cur >= prev
        prev = cur


def test_estimate_is_token_estimate_type(bpe):
    est: TokenEstimate = bpe.estimate("public class A {}")
    assert isinstance(est.tokens, int)
    assert est.chars == len("public class A {}")
    assert est.as_dict()["method"] == "bpe"
