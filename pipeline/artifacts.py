"""阶段产物与跨会话摘要的落盘。

统一走 tmp + `os.replace` 原子写：读者（晨报生成、人工查看、下游阶段）
永远不会读到一个写了一半的 JSON。

跨会话**不靠对话历史**，靠这里的产物 + `runtime/summaries/*.md` 传递。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

from .errors import ValidationError
from .util import atomic_write_json, atomic_write_text, ensure_dir

__all__ = ["ArtifactStore", "SummaryStore"]

DEFAULT_ARTIFACT_ROOT = os.path.join("runtime", "artifacts")
DEFAULT_SUMMARY_ROOT = os.path.join("runtime", "summaries")


@dataclass
class ArtifactStore:
    """阶段产物仓库：`runtime/artifacts/<phase>/<name>`。"""

    root: str = DEFAULT_ARTIFACT_ROOT

    def __post_init__(self) -> None:
        ensure_dir(self.root)

    def path(self, rel: str) -> str:
        """相对路径 -> 绝对路径；拒绝逃出仓库根的写法。"""
        full = os.path.normpath(os.path.join(self.root, rel))
        if not full.startswith(os.path.normpath(self.root)):
            raise ValidationError(f"产物路径越界: {rel}")
        return full

    def write_text(self, rel: str, text: str) -> str:
        full = self.path(rel)
        atomic_write_text(full, text)
        return full

    def write_json(self, rel: str, obj: Any) -> str:
        full = self.path(rel)
        atomic_write_json(full, obj)
        return full

    def write_jsonl(self, rel: str, rows: Iterable[Any]) -> str:
        """整文件原子替换（批级产物通常一次写完，不做流式追加）。"""
        lines = [json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows]
        return self.write_text(rel, "".join(line + "\n" for line in lines))

    def write_md(self, rel: str, text: str) -> str:
        if not rel.endswith(".md"):
            rel += ".md"
        return self.write_text(rel, text)

    def read_json(self, rel: str) -> Any:
        with open(self.path(rel), "r", encoding="utf-8") as fh:
            return json.load(fh)

    def read_text(self, rel: str) -> str:
        with open(self.path(rel), "r", encoding="utf-8") as fh:
            return fh.read()

    def exists(self, rel: str) -> bool:
        return os.path.exists(self.path(rel))

    def list_phase(self, phase: str) -> list[str]:
        """列出某阶段目录下的产物文件名。"""
        directory = os.path.join(self.root, phase.lower())
        if not os.path.isdir(directory):
            return []
        return sorted(os.listdir(directory))


@dataclass
class SummaryStore:
    """跨会话压缩摘要仓库：`runtime/summaries/*.md`。

    摘要必须 ≤ `max_tokens`（默认 4000），否则跨会话传递会挤爆预算——
    这里在落盘时就用 Qwen tokenizer 卡住。
    """

    root: str = DEFAULT_SUMMARY_ROOT
    max_tokens: int = 4000
    tokenizer: Any = None  # pipeline.tokenizer.Tokenizer；None 时跳过容量校验

    def __post_init__(self) -> None:
        ensure_dir(self.root)

    def write(self, name: str, text: str) -> str:
        """写入摘要；超长直接拒绝，避免把问题推迟到下一轮会话才暴露。"""
        if self.tokenizer is not None:
            estimate = self.tokenizer.estimate(text)
            if estimate.tokens > self.max_tokens:
                raise ValidationError(
                    f"摘要 {name} 超长：{estimate.tokens} tokens > 上限 {self.max_tokens}",
                    rule="max_summary_tokens",
                )
        if not name.endswith(".md"):
            name += ".md"
        full = os.path.join(self.root, name)
        atomic_write_text(full, text)
        return full

    def session_name(self, session_seq: int, module: str | None = None) -> str:
        """会话摘要的稳定命名：`session-0003-<module>.md`。"""
        suffix = f"-{module}" if module else ""
        return f"session-{session_seq:04d}{suffix}.md"

    def recent(self, limit: int = 5) -> list[str]:
        """最近的摘要文件名（按名字排序即近似按时间排序）。"""
        if not os.path.isdir(self.root):
            return []
        return sorted(f for f in os.listdir(self.root) if f.endswith(".md"))[-limit:]

    def load_recent_texts(self, limit: int = 2) -> list[str]:
        """读取最近若干摘要正文，供下一轮会话装配上下文。"""
        texts = []
        for name in self.recent(limit):
            with open(os.path.join(self.root, name), "r", encoding="utf-8") as fh:
                texts.append(fh.read())
        return texts
