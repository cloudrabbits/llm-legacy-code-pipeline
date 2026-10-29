"""P5 晨报汇总：纯脚本聚合，保证最后一步不依赖后端。"""

from __future__ import annotations

from ..models import TaskDef
from .common import StageContext, StageResult


def stage_report(ctx: StageContext, task: TaskDef) -> StageResult:
    """产出 `p5/nightly_report.md` 与 `p5/nightly_report.json`。"""
    stats = ctx.artifacts.read_json("p0/inventory.json") if ctx.artifacts.exists("p0/inventory.json") else {}
    modules = ctx.artifacts.read_json("p2/modules.json") if ctx.artifacts.exists("p2/modules.json") else {}
    module_names = [m.get("name") for m in (modules.get("modules") or [])] if isinstance(modules, dict) else []

    risks: list[dict] = []
    for name in ctx.artifacts.list_phase("p4"):
        if name.startswith("risks-") and name.endswith(".json"):
            data = ctx.artifacts.read_json(f"p4/{name}")
            risks.extend(data.get("risks") or [])

    violations = (
        ctx.artifacts.read_json("p3/violations.json") if ctx.artifacts.exists("p3/violations.json") else {}
    )

    summary = {
        "project": stats.get("project"),
        "file_count": stats.get("file_count"),
        "java_count": stats.get("java_count"),
        "jsp_count": stats.get("jsp_count"),
        "modules": module_names,
        "risk_count": len(risks),
        "risks": risks,
        "dependency_violations": violations.get("count", 0),
        "artifacts": {phase: ctx.artifacts.list_phase(phase) for phase in ("p0", "p1", "p2", "p3", "p4")},
    }

    lines = [
        "# 夜间分析报告",
        "",
        f"- 项目：**{summary['project']}**（{summary['file_count']} 个文本文件，"
        f"Java {summary['java_count']} / JSP {summary['jsp_count']}）",
        f"- 识别模块：{', '.join([m for m in module_names if m]) or '无'}",
        f"- 依赖违规：{summary['dependency_violations']} 条",
        f"- 风险条目：{summary['risk_count']}",
        "",
        "## 风险清单",
        "",
    ]
    for risk in risks[:60]:
        level = (risk or {}).get("level", "未分级")
        desc = (risk or {}).get("desc", "")
        evidence = (risk or {}).get("evidence", "")
        lines.append(f"- **[{level}]** {desc}" + (f"（证据：{evidence}）" if evidence else ""))
    if not risks:
        lines.append("- 未检出风险条目（或 P4 未执行）")

    lines += ["", "## 产物索引", ""]
    for phase, items in summary["artifacts"].items():
        lines.append(f"- `{phase}`：{', '.join(items) if items else '无'}")

    md = "\n".join(lines) + "\n"
    ctx.artifacts.write_md("p5/nightly_report", md)
    artifact = ctx.artifacts.write_json("p5/nightly_report.json", summary)
    return StageResult(text=md, artifact=artifact, extra={"risk_count": len(risks)})
