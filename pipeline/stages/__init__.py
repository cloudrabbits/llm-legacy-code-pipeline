"""P0–P5 阶段处理器。

按阶段拆成 `p0_baseline` … `p5_report` 六个模块；跨阶段共用的
装配 / 读取 / 视图 helper 在 `common.py`，各阶段模块只依赖它，
彼此之间不横向 import。

对外接口保持与拆分前完全一致：

    from pipeline.stages import StageContext, StageResult, HANDLERS, run_stage, digest

编排器只按 `task.kind` 调 `run_stage`。
"""

from __future__ import annotations

from typing import Callable

from ..errors import ValidationError
from ..models import TaskDef
from .common import (
    DIGEST_CHARS,
    LAYER_BY_PATH,
    LAYER_VALUES,
    SYSTEM_PROMPTS,
    Block,
    StageContext,
    StageResult,
    digest,
)
from .p0_baseline import stage_baseline
from .p1_classify import stage_classify
from .p2_modules import stage_modules
from .p3_deps import stage_deps
from .p4_architecture import stage_architecture
from .p5_report import stage_report

__all__ = [
    "Block",
    "StageContext",
    "StageResult",
    "HANDLERS",
    "run_stage",
    "digest",
    "LAYER_VALUES",
    "LAYER_BY_PATH",
    "DIGEST_CHARS",
    "SYSTEM_PROMPTS",
]

#: `task.kind` -> 阶段处理器
HANDLERS: dict[str, Callable[[StageContext, TaskDef], StageResult]] = {
    "baseline": stage_baseline,
    "classify": stage_classify,
    "modules": stage_modules,
    "deps": stage_deps,
    "architecture": stage_architecture,
    "report": stage_report,
}


def run_stage(ctx: StageContext, task: TaskDef) -> StageResult:
    """按 `task.kind` 分发到阶段处理器。未知 kind 直接抛 ValidationError。"""
    handler = HANDLERS.get(task.kind)
    if handler is None:
        raise ValidationError(f"未注册的阶段类型: {task.kind}（可用: {sorted(HANDLERS)}）", task_id=task.task_id)
    return handler(ctx, task)
