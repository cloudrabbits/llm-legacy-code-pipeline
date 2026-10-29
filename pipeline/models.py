"""核心数据模型。

分三类：
    1. 传输层无关的类型（EffortLevel / FinishReason / Budget / Result / TaskContext）
    2. 任务定义（pydantic：TaskDef / Acceptance）——`tasks/*.json` 的校验目标
    3. 检查点事件（pydantic：CheckpointEvent）——append-only JSONL 的行格式
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "EffortLevel",
    "FinishReason",
    "TaskStatus",
    "Phase",
    "Budget",
    "TokenEstimate",
    "Usage",
    "Result",
    "TaskContext",
    "Acceptance",
    "TaskDef",
    "CheckpointEvent",
]


class EffortLevel(str, Enum):
    """推理档位。后端无关的四档，由画像映射到各自的参数形态。"""

    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    XHIGH = "xhigh"


class FinishReason(str, Enum):
    """归一化后的结束原因。DeepSeek 与 Ollama 的原始取值差异到此为止。"""

    STOP = "stop"
    LENGTH = "length"
    ERROR = "error"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"   # 客户端预算钳制拒绝（CONTEXT_OVERFLOW）
    SKIPPED = "skipped"     # 软阻塞 / 依赖未满足


Phase = Literal["P0", "P1", "P2", "P3", "P4", "P5"]


class Budget(BaseModel):
    """上下文预算。

    规格书硬性要求：窗口强制钳制到 92160，输入预算 80000，输出上限 8192。
    这三个值**不随后端变化**——即使 DeepSeek 真实窗口远大于此，仿真阶段也必须钳制。
    """

    model_config = ConfigDict(extra="forbid")

    context_window: int = 92160
    input_budget: int = 80000
    max_output_tokens: int = 8192
    #: 为 system prompt + 摘要 + 消息封装预留的开销（估算时叠加到 prompt 上）
    envelope_overhead: int = 512

    @field_validator("input_budget")
    @classmethod
    def _budget_lt_window(cls, v: int, info: Any) -> int:
        return v


@dataclass(frozen=True)
class TokenEstimate:
    """token 估算结果。

    Attributes:
        tokens: 最终用于预算判定的 token 数（已含安全系数）。
        raw_tokens: 未乘安全系数的原始估算。
        method: `bpe`（Qwen BPE 精确）或 `heuristic`（纯标准库兜底）。
        safety_factor: 实际施加的安全系数。
        chars: 参与估算的字符数。
    """

    tokens: int
    raw_tokens: int
    method: str
    safety_factor: float
    chars: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "raw_tokens": self.raw_tokens,
            "method": self.method,
            "safety_factor": self.safety_factor,
            "chars": self.chars,
        }


@dataclass(frozen=True)
class Usage:
    """归一化后的用量。Ollama 的 `prompt_eval_count` 与 DeepSeek 的
    `usage.prompt_tokens` 在此统一。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


#: 结果标记位。写入 checkpoint.flags，用于晨报统计。
FLAG_TRUNCATED = "TRUNCATED"
FLAG_SUSPECT = "SUSPECT"
FLAG_CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
FLAG_DEGRADED = "DEGRADED"


@dataclass
class Result:
    """后端无关的统一结果。编排器只消费这个类型。"""

    task_id: str
    backend_name: str
    effort_applied: str
    text: str
    #: 归一化后的推理内容；`effort=off` 或未产出时为 None
    reasoning: str | None
    finish_reason: FinishReason
    usage: Usage
    truncated: bool
    flags: list[str] = field(default_factory=list)
    #: 估算值 vs 后端上报值的相对偏差；不可比时为 None
    prompt_deviation: float | None = None
    latency_ms: int = 0
    #: prefill（prompt 评估）耗时，毫秒；后端未返回分项耗时为 None
    prefill_ms: float | None = None
    #: decode（生成）耗时，毫秒；后端未返回分项耗时为 None
    decode_ms: float | None = None
    attempt: int = 1
    route: str = "local"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_tokens(self) -> int:
        return self.usage.prompt_tokens

    @property
    def completion_tokens(self) -> int:
        return self.usage.completion_tokens

    @property
    def prefill_tps(self) -> float | None:
        """prefill 速度（tokens/s）；缺耗时或 0 耗时返回 None。"""
        if self.prefill_ms and self.prefill_ms > 0 and self.usage.prompt_tokens:
            return self.usage.prompt_tokens / (self.prefill_ms / 1000.0)
        return None

    @property
    def decode_tps(self) -> float | None:
        """decode 速度（tokens/s）；缺耗时或 0 耗时返回 None。"""
        if self.decode_ms and self.decode_ms > 0 and self.usage.completion_tokens:
            return self.usage.completion_tokens / (self.decode_ms / 1000.0)
        return None

    @property
    def total_tps(self) -> float | None:
        """端到端平均速度（tokens/s），用总延迟兜底。"""
        if self.latency_ms and self.latency_ms > 0:
            total = self.usage.prompt_tokens + self.usage.completion_tokens
            if total:
                return total / (self.latency_ms / 1000.0)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "backend_name": self.backend_name,
            "effort_applied": self.effort_applied,
            "text": self.text,
            "reasoning": self.reasoning,
            "finish_reason": self.finish_reason.value,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "truncated": self.truncated,
            "flags": list(self.flags),
            "prompt_deviation": self.prompt_deviation,
            "latency_ms": self.latency_ms,
            "prefill_ms": self.prefill_ms,
            "decode_ms": self.decode_ms,
            "prefill_tps": self.prefill_tps,
            "decode_tps": self.decode_tps,
            "attempt": self.attempt,
            "route": self.route,
        }


@dataclass
class TaskContext:
    """一次后端调用所需的全部输入。由 `context.py`（M2）装配，此处只定义形状。"""

    task_id: str
    phase: Phase = "P1"
    system: str = ""
    user: str = ""
    effort: EffortLevel = EffortLevel.MEDIUM
    max_output_tokens: int = 8192
    timeout_sec: float = 900.0
    #: 逐请求显式传入，不依赖后端全局默认（规格书第五节）
    num_ctx: int = 92160
    route: str = "local"
    #: planner 预估的 prompt token 数；用于与实际用量比对标记 SUSPECT
    expected_prompt_tokens: int | None = None
    #: 透传给画像的额外字段（如 Ollama 的 options 覆盖）
    extra: dict[str, Any] = field(default_factory=dict)

    def prompt_text(self) -> str:
        """参与 token 估算的完整文本。"""
        return f"{self.system}\n{self.user}" if self.system else self.user


class Acceptance(BaseModel):
    """任务验收标准，必须可自动校验。

    Attributes:
        schema_ref: `schemas/*.json` 中的 JSON Schema，产出为 JSON 时校验。
        min_chars: 产出文本最小长度。
        required_keys: 产出 JSON 必须包含的顶层键。
        regex_must: 必须命中的正则列表。
        llm_free: True 表示该阶段不调用 LLM，纯脚本产出（如 P0）。
    """

    model_config = ConfigDict(extra="forbid")

    schema_ref: str | None = None
    min_chars: int = 0
    required_keys: list[str] = Field(default_factory=list)
    regex_must: list[str] = Field(default_factory=list)
    llm_free: bool = False


class TaskDef(BaseModel):
    """任务定义（`tasks/*.json` 的单条记录）。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    phase: Phase
    kind: str
    route: Literal["local", "cloud"] = "local"
    input_files: list[str] = Field(default_factory=list)
    #: 上游产物 / 摘要引用，跨会话不靠对话历史，靠这些落盘产物传递
    input_refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    effort: EffortLevel = EffortLevel.MEDIUM
    max_output_tokens: int = 8192
    max_retries: int = 3
    timeout_sec: int = 900
    acceptance: Acceptance = Field(default_factory=Acceptance)
    payload: dict[str, Any] = Field(default_factory=dict)
    #: 计划期预估 token 数；执行期以实测覆盖
    est_tokens: int | None = None

    @field_validator("task_id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("task_id 不能为空")
        return v


class CheckpointEvent(BaseModel):
    """append-only JSONL 的一行。

    用 append-only 保证崩溃可回放；同时由 `checkpoint.py`（M2）周期性把
    重放结果原子写入 `runtime/state/index.json`（tmp + os.replace）。
    """

    model_config = ConfigDict(extra="forbid")

    seq: int = 0
    ts: str = ""
    event: str
    task_id: str | None = None
    phase: str | None = None
    attempt: int = 0
    route: str = "local"
    status: str | None = None
    #: 该次运行归属的项目规范绝对路径；用于跨项目 runtime 复用时拒绝误续跑
    project: str | None = None
    error_class: str | None = None
    error: str | None = None
    tokens: dict[str, int] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    artifact: str | None = None
    duration_ms: int = 0
    session_seq: int | None = None
    gpu_mb: int | None = None

    def to_jsonl(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, separators=(",", ":"))
