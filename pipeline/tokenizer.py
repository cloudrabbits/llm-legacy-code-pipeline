"""Qwen tokenizer 估算。

规格书硬性要求（第三节第 1 条）：
    **Token 估算必须用 Qwen tokenizer**，不能用 DeepSeek tokenizer。
    超过 80K 输入预算的任务在客户端直接拒绝，标记 CONTEXT_OVERFLOW，不得发给 DeepSeek。

两档实现，均为本地、可离线：
    bpe       —— `tokenizers` 库加载本地缓存的 Qwen BPE `tokenizer.json`，精确计数；
                 安全系数 1.0（精确，无需 margin）。
    heuristic —— 纯标准库兜底：代码 3.2 字符/token、中文 1.5 字符/token，×1.18 安全系数。

内网迁移只需把 `models/qwen2_bpe/` 整个目录拷过去即可离线工作。
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from typing import Iterable

from .models import TokenEstimate

__all__ = ["Tokenizer", "CJK_RANGES", "DEFAULT_CACHE_PATH"]


#: Qwen2/Qwen3 共用同一套 BPE 词表（151k），与内网 qwen3.8:27b 一致。
DEFAULT_CACHE_PATH = os.path.join("models", "qwen2_bpe", "tokenizer.json")

#: 常见 CJK / 全角标点区间，用于启发式兜底的字符分类
CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x3400, 0x4DBF),   # CJK 扩展 A
    (0x4E00, 0x9FFF),   # CJK 基本区
    (0xF900, 0xFAFF),   # 兼容表意文字
    (0x3000, 0x303F),   # CJK 标点
    (0xFF00, 0xFFEF),   # 全角字符
)

_UNIT = "public class Sample { private String name; } // 中文注释用于混合编码估算\n"


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in CJK_RANGES)


class Tokenizer:
    """Qwen token 计数器。

    Args:
        cache_path: 本地 BPE `tokenizer.json` 路径；不存在则自动降级为启发式。
        prefer: `"bpe"` 优先精确计数；`"heuristic"` 强制走兜底（内网无法装依赖时用）。
        safety_factor: 启发式模式下的安全系数；BPE 模式强制为 1.0。
        code_chars_per_token: 非 CJK 字符/token。
        cjk_chars_per_token: CJK 字符/token。
    """

    def __init__(
        self,
        cache_path: str = DEFAULT_CACHE_PATH,
        *,
        prefer: str = "bpe",
        safety_factor: float = 1.18,
        code_chars_per_token: float = 3.2,
        cjk_chars_per_token: float = 1.5,
    ) -> None:
        self.cache_path = cache_path
        self.safety_factor = safety_factor
        self.code_chars_per_token = code_chars_per_token
        self.cjk_chars_per_token = cjk_chars_per_token
        self._bpe = None
        self.method = "heuristic"
        if prefer == "bpe":
            self._bpe = self._load_bpe(cache_path)
            if self._bpe is not None:
                self.method = "bpe"
                self.safety_factor = 1.0
        elif prefer != "heuristic":
            raise ValueError(f"未知 tokenizer prefer={prefer!r}")

    # ------------------------------------------------------------------ 加载

    @staticmethod
    @lru_cache(maxsize=4)
    def _load_bpe(cache_path: str):
        """加载本地 BPE 词表；任何失败都返回 None（调用方降级为启发式）。"""
        if not os.path.exists(cache_path):
            return None
        try:
            from tokenizers import Tokenizer as HfTokenizer  # noqa: PLC0415

            return HfTokenizer.from_file(cache_path)
        except Exception:
            return None

    # ------------------------------------------------------------------ 计数

    def count(self, text: str) -> int:
        """原始 token 数（不含安全系数）。"""
        if self._bpe is not None:
            try:
                return len(self._bpe.encode(text, add_special_tokens=False).ids)
            except Exception:
                pass  # 罕见编码异常 -> 走兜底
        cjk = sum(1 for ch in text if _is_cjk(ch))
        other = len(text) - cjk
        return int(math.ceil(cjk / self.cjk_chars_per_token + other / self.code_chars_per_token))

    def estimate(self, text: str) -> TokenEstimate:
        """用于预算判定的估算值（含安全系数）。"""
        raw = self.count(text)
        tokens = int(math.ceil(raw * self.safety_factor))
        return TokenEstimate(
            tokens=tokens,
            raw_tokens=raw,
            method=self.method,
            safety_factor=float(self.safety_factor),
            chars=len(text),
        )

    def estimate_chunks(self, chunks: Iterable[str]) -> TokenEstimate:
        """多段文本合并估算：先合并再算一次，避免逐段取整累加放大误差。"""
        return self.estimate("\n".join(chunks))

    # ------------------------------------------------------------------ 测试辅助

    def materialize(self, target_tokens: int, unit: str = _UNIT) -> str:
        """构造估算值恰好达到 `target_tokens` 的文本，供契约测试构造 79K/81K 语料。

        以「前缀长度」为自变量二分：`estimate(prefix)` 对长度单调不减。
        """
        if target_tokens <= 0:
            return ""
        sample = unit * 64
        ratio = self.estimate(sample).tokens / max(1, len(sample))
        n_chars = max(len(unit), int(target_tokens / ratio) + len(unit))
        base = self._repeat_to(unit, n_chars)
        # 若猜短了就翻倍，直到足够长
        while self.estimate(base).tokens < target_tokens and len(base) < 40_000_000:
            base = base + base
        lo, hi = 0, len(base)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.estimate(base[:mid]).tokens < target_tokens:
                lo = mid + 1
            else:
                hi = mid
        return base[:lo]

    @staticmethod
    def _repeat_to(unit: str, n_chars: int) -> str:
        reps = max(1, n_chars // len(unit) + 1)
        return (unit * reps)[:n_chars]
