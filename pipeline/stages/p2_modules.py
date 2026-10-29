"""P2 模块边界推断：脚本给路由与分层，LLM 只做归并。"""

from __future__ import annotations

import json

from ..acceptance import require
from ..models import TaskDef
from .common import Block, StageContext, StageResult, _call, _p1_rows, _script_module_summary


def stage_modules(ctx: StageContext, task: TaskDef) -> StageResult:
    """产出 `p2/modules.json`。"""
    facts = ctx.facts_or_load()
    webxml = facts["project"].get("webxml") or {}

    rows = _p1_rows(ctx)
    p1_text = "\n".join(
        f"{r.get('file')} | layer={r.get('layer')} | module={r.get('module')}"
        + (f" | risk={r.get('risk')}" if r.get("risk") else "")
        for r in rows
    )
    blocks = [
        Block(name="脚本模块切分（请沿用这些 domain 名）", text=json.dumps(
            _script_module_summary(facts, compact=True), ensure_ascii=False, indent=1)),
        Block(name="P1 分层标签", text=p1_text or "（无 P1 产物）"),
        Block(name="web.xml 路由", text=json.dumps(
            {
                "servlets": webxml.get("servlets"),
                "servlet_mappings": webxml.get("servlet_mappings"),
                "filters": webxml.get("filters"),
                "welcome_files": webxml.get("welcome_files"),
            },
            ensure_ascii=False,
            indent=1,
        )),
        Block(name="Servlet 分派分支", text=json.dumps(facts.get("routes") or {}, ensure_ascii=False, indent=1)[:15000]),
    ]

    result = _call(ctx, task, kind="modules", blocks=blocks)
    parsed = require(result.text, task.acceptance, task_id=task.task_id)
    artifact = ctx.artifacts.write_json("p2/modules.json", parsed)
    return StageResult(text=result.text, artifact=artifact, extra={"p1_rows": len(rows)}, result=result)
