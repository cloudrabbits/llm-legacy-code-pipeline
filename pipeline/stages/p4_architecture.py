"""P4 架构摘要 + 风险。"""

from __future__ import annotations

import json

from ..acceptance import require
from ..errors import ValidationError
from ..models import Result, TaskDef
from .common import Block, StageContext, StageResult, _call, _p1_rows


def stage_architecture(ctx: StageContext, task: TaskDef) -> StageResult:
    """一个任务覆盖全部模块（`payload.module = "auto"`），逐个模块调用并落盘。

    单个模块失败只降级为「需人工复核」，不会让整个 P4 白跑——
    夜间无人值守时，"少一份摘要"远好过"整阶段失败"。
    """
    facts = ctx.facts_or_load()
    targets = _p4_targets(ctx, facts, task)
    if not targets:
        raise ValidationError("P4 没有可分析的模块（P2 未产出且脚本切分为空）", task_id=task.task_id)

    all_risks: list[dict] = []
    done: list[str] = []
    failed: list[str] = []
    last_result: "Result | None" = None

    for module in targets:
        smod = _script_module(facts, module)
        rows = [r for r in _p1_rows(ctx) if str(r.get("module", "")).lower() == module.lower()]
        p1_text = "\n".join(f"{r.get('file')} | layer={r.get('layer')}" for r in rows) or "（无该模块的 P1 标签）"
        blocks = [
            Block(name=f"脚本模块切片 {module}", text=json.dumps(smod, ensure_ascii=False, indent=1) or "{}"),
            Block(name="模块内文件与分层", text=p1_text),
        ]
        try:
            result = _call(ctx, task, kind="architecture", blocks=blocks, module=module)
            last_result = result
            parsed = require(result.text, task.acceptance, task_id=task.task_id)
        except ValidationError as exc:
            failed.append(module)
            ctx.artifacts.write_md(f"p4/{module}", f"# 模块 {module}\n\n> 待人工复核：{exc.message}\n")
            if ctx.logger:
                ctx.logger.warning("模块 %s 摘要失败：%s", module, exc.message)
            continue

        summary = parsed.get("summary", "") if isinstance(parsed, dict) else ""
        risks = parsed.get("risks", []) if isinstance(parsed, dict) else []
        all_risks.extend(risks)
        ctx.artifacts.write_md(f"p4/{module}", f"# 模块 {module}\n\n{summary}\n")
        ctx.artifacts.write_json(f"p4/risks-{module}.json", {"module": module, "risks": risks})
        done.append(module)

    if not done:
        raise ValidationError(f"P4 全部模块摘要失败: {failed}", task_id=task.task_id, rule="acceptance")

    aggregate = {
        "summary": f"已完成 {len(done)}/{len(targets)} 个模块的架构摘要：{', '.join(done)}"
        + (f"；失败需复核：{', '.join(failed)}" if failed else ""),
        "risks": all_risks,
        "modules_done": done,
        "modules_failed": failed,
    }
    artifact = ctx.artifacts.write_json("p4/risks.json", aggregate)
    return StageResult(
        text=aggregate["summary"],
        artifact=artifact,
        extra={"modules": len(done), "risks": len(all_risks), "failed": failed},
        result=last_result,
    )


def _script_module(facts: dict, module: str) -> dict:
    """大小写不敏感地取脚本模块切片（LLM 与脚本命名风格常不一致）。"""
    wanted = module.lower()
    for mod in facts.get("modules") or []:
        if str(mod.get("domain", "")).lower() == wanted:
            return mod
    return {}


def _p4_targets(ctx: StageContext, facts: dict, task: TaskDef) -> list[str]:
    """P4 要对哪些模块做摘要。

    优先用 P2 归并出的模块名（可能比脚本细分，例如把登录拆成 Auth），
    没有 P2 产物时退回脚本模块名。`payload.module` 显式指定时只做那一个。
    """
    explicit = task.payload.get("module")
    if explicit and explicit != "auto":
        return [str(explicit)]

    names: list[str] = []
    if ctx.artifacts.exists("p2/modules.json"):
        data = ctx.artifacts.read_json("p2/modules.json")
        if isinstance(data, dict):
            names = [str(m.get("name")) for m in (data.get("modules") or []) if m.get("name")]
    if not names:
        names = [str(m.get("domain")) for m in (facts.get("modules") or []) if m.get("domain")]
    # 去重（大小写不敏感），保持首次出现顺序
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            unique.append(name)
    return unique
