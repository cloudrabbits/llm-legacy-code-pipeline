"""P0 基线扫描：纯脚本，零 LLM 调用。"""

from __future__ import annotations

from ..models import TaskDef
from ..scan import component_ledger, platform_deps
from .common import StageContext, StageResult


def stage_baseline(ctx: StageContext, task: TaskDef) -> StageResult:
    """产出 `p0/inventory.json` 与 `p0/baseline.md`。"""
    facts = ctx.facts_or_load()
    project = facts["project"]
    webxml = project.get("webxml") or {}

    ledger = component_ledger(facts)
    plat = platform_deps(facts)
    inventory = {
        "project": project.get("name"),
        "root": project.get("root"),
        "generated_at": project.get("generated_at"),
        "file_count": len(project.get("files") or []),
        "java_count": len(project.get("java") or []),
        "jsp_count": len(project.get("jsp") or []),
        "binary_count": len(project.get("binaries") or []),
        "encoding_histogram": _encoding_histogram(project.get("files") or []),
        "jars": [j.get("name") for j in (project.get("jars") or [])],
        "jndi": project.get("jndi") or [],
        "jdbc_urls": project.get("jdbc_urls") or [],
        "drivers": project.get("drivers") or [],
        "webxml": webxml.get("file"),
        "servlet_count": len(webxml.get("servlets") or []),
        "mapping_count": len(webxml.get("servlet_mappings") or []),
        "sql_tables": sorted({t for s in (project.get("sql") or []) for t in (s.get("tables") or [])}),
        # 组件改造台账：第三方 / 闭源组件 + 容器 / JDK 提供的平台依赖
        "components": [
            {"id": c.get("id"), "name": c.get("name"), "category": c.get("category"),
             "status": c.get("status"), "usage": c.get("usage"),
             "migration_target": c.get("migration_target"), "phase": c.get("phase")}
            for c in ledger
        ],
        "platform_deps": [
            {"id": d.get("id"), "name": d.get("name"), "provided_by": d.get("provided_by"),
             "status": d.get("status"), "version_hint": d.get("version_hint"),
             "migration_target": d.get("migration_target"), "phase": d.get("phase")}
            for d in plat
        ],
    }
    artifact = ctx.artifacts.write_json("p0/inventory.json", inventory)

    lines = [
        f"# P0 基线扫描：{inventory['project']}",
        "",
        f"- 根目录：`{inventory['root']}`",
        f"- 文本文件 {inventory['file_count']} 个（Java {inventory['java_count']} / JSP {inventory['jsp_count']}）",
        f"- 二进制/资源 {inventory['binary_count']} 个",
        f"- 编码分布：{inventory['encoding_histogram']}",
        f"- web.xml：`{inventory['webxml']}`，Servlet {inventory['servlet_count']} 个 / 映射 {inventory['mapping_count']} 条",
        f"- JNDI：{inventory['jndi'] or '无'}",
        f"- 数据库驱动：{inventory['drivers'] or '未检出'}",
        f"- 建表语句中的表：{inventory['sql_tables'] or '无'}",
    ]

    eol = [c["name"] for c in inventory["components"] if c["status"] in ("EOL", "unknown")]
    lines += [
        "",
        "## 组件改造台账",
        "",
        f"- 第三方 / 闭源组件：{len(inventory['components'])} 个"
        + (f"（其中停更或状态未知：{'、'.join(eol)}）" if eol else ""),
    ]
    for c in inventory["components"]:
        lines.append(f"  - `{c['name']}` [{c['status']}] 引用 {c['usage']} 处"
                     f" → {c['migration_target'] or '待定'}（阶段 {c['phase'] or '-'}）")
    if inventory["platform_deps"]:
        lines.append(f"- 平台 / 容器 / JDK 提供的依赖：{len(inventory['platform_deps'])} 个")
        for d in inventory["platform_deps"]:
            lines.append(f"  - `{d['name']}`（{d['provided_by']}"
                         + (f"，版本线索 {d['version_hint']}" if d["version_hint"] else "")
                         + f"）→ {d['migration_target'] or '待定'}")
    else:
        lines.append("- 平台 / 容器 / JDK 提供的依赖：未检出")

    md = "\n".join(lines) + "\n"
    ctx.artifacts.write_md("p0/baseline", md)
    return StageResult(text=md, artifact=artifact)


def _encoding_histogram(files: list[dict]) -> dict[str, int]:
    hist: dict[str, int] = {}
    for f in files:
        enc = f.get("encoding") or "unknown"
        hist[enc] = hist.get(enc, 0) + 1
    return dict(sorted(hist.items(), key=lambda kv: -kv[1]))
