"""异常分类。

编排器只依据异常类型决定行为，不关心具体后端：

    ContextOverflowError  -> 不发请求，标记 CONTEXT_OVERFLOW，细分块后重排
    BackendTimeoutError   -> 指数退避重试，耗尽后按路由降级
    BackendError          -> 可重试则退避重试；连续失败触发降级
    ValidationError       -> 验收不通过，重试 1 次后降级为 NEEDS_REVIEW
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "PipelineError",
    "ContextOverflowError",
    "BackendError",
    "BackendTimeoutError",
    "TimeoutError",
    "ValidationError",
    "ConfigError",
]


class PipelineError(Exception):
    """所有流水线异常的基类。"""

    #: 写入 checkpoint 的 error_class 字段，供断点续跑与统计复用
    code: str = "PipelineError"

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_event(self) -> dict[str, Any]:
        """转成可写入 checkpoint.jsonl 的结构（剔除可能很大的 raw 负载）。"""
        detail = {k: v for k, v in self.detail.items() if k != "raw"}
        return {"error_class": self.code, "error": self.message, "detail": detail}


class ContextOverflowError(PipelineError):
    """客户端预算钳制拒绝：估算 token 数超出输入预算，请求不会发给后端。

    Attributes:
        tokens: Qwen tokenizer（或启发式兜底）估算出的 prompt token 数。
        budget: 当前生效的输入预算上限。
        task_id: 触发拒绝的任务标识，便于 planner 细分后重排。
    """

    code = "ContextOverflowError"

    def __init__(self, tokens: int, budget: int, task_id: str | None = None) -> None:
        super().__init__(
            f"prompt 估算 {tokens} tokens 超过输入预算 {budget}"
            + (f"（task_id={task_id}）" if task_id else ""),
            tokens=tokens,
            budget=budget,
            task_id=task_id,
        )
        self.tokens = tokens
        self.budget = budget
        self.task_id = task_id


class BackendError(PipelineError):
    """后端调用失败（HTTP 非 2xx、响应结构异常、连接错误）。"""

    code = "BackendError"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = True,
        raw: Any = None,
        **detail: Any,
    ) -> None:
        super().__init__(message, status_code=status_code, retryable=retryable, **detail)
        self.status_code = status_code
        self.retryable = retryable
        self.raw = raw


class BackendTimeoutError(BackendError):
    """单次请求超时。必然可重试。"""

    code = "TimeoutError"

    def __init__(self, message: str, *, timeout_sec: float | None = None) -> None:
        super().__init__(message, timeout_sec=timeout_sec, retryable=True)
        self.timeout_sec = timeout_sec


#: 规格书要求的分类名 `TimeoutError`；避免与内建同名导致误捕获，用别名导出。
TimeoutError = BackendTimeoutError


class ValidationError(PipelineError):
    """任务定义 / 产物验收不通过（pydantic schema、JSON Schema、正则断言）。"""

    code = "ValidationError"

    def __init__(self, message: str, *, task_id: str | None = None, rule: str | None = None) -> None:
        super().__init__(message, task_id=task_id, rule=rule)
        self.task_id = task_id
        self.rule = rule


class ConfigError(PipelineError):
    """配置加载失败（缺文件、缺密钥、类型错误）。"""

    code = "ConfigError"
