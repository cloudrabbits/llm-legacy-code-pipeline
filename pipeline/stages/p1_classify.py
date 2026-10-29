"""P1 文件分类打标：LLM 打标，脚本校验覆盖面。"""

from __future__ import annotations

from ..acceptance import require
from ..models import TaskDef
from ..scan import source_blocks
from .common import StageContext, StageResult, _call, _rows_from_output


def stage_classify(ctx: StageContext, task: TaskDef) -> StageResult:
    """产出 `p1/<task_id>.jsonl`（layer / module / risk）。

    模型未覆盖的文件由脚本补一行「layer=other, module=unknown」，
    保证覆盖面完整——不靠模型自觉。
    """
    facts = ctx.facts_or_load()
    blocks = source_blocks(facts, task.input_files, project_root=ctx.project_root)
    if not blocks:
        return StageResult(text="", artifact=None, extra={"empty": True})

    result = _call(ctx, task, kind="classify", blocks=blocks)
    parsed = require(result.text, task.acceptance, task_id=task.task_id)
    rows = _rows_from_output(parsed)

    covered = {r.get("file") for r in rows}
    for block in blocks:
        if block.name not in covered:
            rows.append({"file": block.name, "layer": "other", "module": "unknown", "risk": "模型未覆盖"})

    artifact = ctx.artifacts.write_jsonl(f"p1/{task.task_id}.jsonl", rows)
    return StageResult(text=result.text, artifact=artifact, extra={"rows": len(rows)}, result=result)
