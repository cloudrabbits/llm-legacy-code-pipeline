"""P0–P5 阶段处理器。

分工原则（沿用 `tools/jlp` 的「事实优先」）：
    * P0 / P3 依赖边 / P2 骨架 —— **脚本算**，LLM 不产生事实。
    * P1 打标 / P2 边界归并 / P3 违规核对 / P4 摘要与风险 —— LLM 做归类与叙述，
      产出必须过 `acceptance.py` 的自动校验。
    * P5 晨报 —— 纯脚本聚合，保证夜里最后一步不会因为后端抖动而失败。

教训（首夜实测）：让模型「复述」大表会撑爆 max_tokens 并截断成非法 JSON。
因此凡是脚本已经算出来的事实，一律先落盘，只把**压缩视图**交给模型。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .acceptance import require
from .artifacts import ArtifactStore, SummaryStore
from .context import Block, build_task_context
from .errors import ValidationError
from .models import Budget, EffortLevel, Result, TaskDef
from .scan import load_project_facts, source_blocks, component_ledger, platform_deps

__all__ = ["StageContext", "StageResult", "HANDLERS", "run_stage", "digest", "LAYER_VALUES"]

LAYER_VALUES = "jsp|servlet|biz|dao|entity|util|config|sql|other"

#: 摘要的最大字符数（远低于 4000 token 上限，留足余量）
DIGEST_CHARS = 3000

SYSTEM_PROMPTS: dict[str, str] = {
    "classify": (
        "你是一个遗留 Java Web 项目的静态分析助手。只依据下面给出的源码片段做判断，"
        "不得臆造未出现的事实。为每个文件输出一行 JSON，字段："
        "file(仓库相对路径)、layer(只能是 jsp/servlet/biz/dao/entity/util/config/sql/other)、"
        "module(模块名，无法判断时填 unknown)、risk(风险描述，无则空字符串)。"
        '严格输出 JSON：{"items":[...]}，不要输出任何解释性文字。'
    ),
    "modules": (
        "你是一个遗留 Java Web 项目的架构分析助手。依据下面给出的脚本模块切分、"
        "路由表与文件分层标签，归并出功能模块边界。"
        "**优先沿用脚本给出的 domain 名称**（大小写可统一）；不要发明输入里没有的类名、页面名、表名。"
        "输出必须极简：每个模块只给 4 个字段，不要写 capabilities / evidence / 说明文字，"
        "数组每项最多 8 个元素。"
        '严格输出 JSON：{"modules":[{"name":...,"servlets":[...],"pages":[...],"tables":[...]}]}。'
    ),
    "deps": (
        "你是一个依赖分析助手。脚本已经算好了全部 import 依赖边，下面只给你压缩视图。"
        "请只判断**跨层违规**与**无法解析的外部依赖**，不要复述输入清单。"
        '严格输出 JSON：{"violations":[{"from":...,"to":...,"reason":...}],'
        '"external":[...],"notes":"<=200字"}，不要输出解释性文字。'
    ),
    "architecture": (
        "你是一个架构摘要助手。依据下面的模块切片事实，写一份不超过 800 字的模块摘要，"
        "并列出风险清单。严格输出 JSON："
        '{"summary":"...","risks":[{"level":"高|中|低","desc":"...","evidence":"..."}]}。'
        "每条风险必须带 evidence（文件:行号或类名），不得编造。"
    ),
}

#: 路径片段 -> 分层（脚本侧判定，用于 P3 跨层违规检测）
LAYER_BY_PATH = (
    ("/biz/", "biz"),
    ("/service/", "biz"),
    ("/dao/", "dao"),
    ("/entity/", "entity"),
    ("/model/", "entity"),
    ("/bean/", "entity"),
    ("/servlet/", "servlet"),
    ("/controller/", "servlet"),
    ("/action/", "servlet"),
    ("/util/", "util"),
    ("/common/", "util"),
)


def digest(text: str, *, task_id: str = "") -> str:
    """机械压缩摘要：确定性、零额外调用，供跨会话传递。"""
    head = f"# 会话摘要 {task_id}\n\n" if task_id else "# 会话摘要\n\n"
    return head + text.strip()[:DIGEST_CHARS]


@dataclass
class StageContext:
    """阶段处理器共享的运行时依赖。"""

    cfg: Any
    project_root: str
    artifacts: ArtifactStore
    summaries: SummaryStore
    tokenizer: Any
    budget: Budget
    backend: Any
    sessions: Any
    monitor: Any = None
    logger: Any = None
    dry_run: bool = False
    facts: dict | None = None
    last_digest: str | None = None

    def facts_or_load(self) -> dict:
        if self.facts is None:
            self.facts = load_project_facts(self.project_root)
        return self.facts


@dataclass
class StageResult:
    text: str
    artifact: str | None = None
    module: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    #: 本阶段最后一次后端调用结果（携带 prefill/decode 速度等）。
    #: 纯脚本阶段（P0/P5）为 None；编排器据此输出分项速度与剩余时间预测。
    result: "Result | None" = None


# --------------------------------------------------------------------------- 通用调用


def _call(
    ctx: StageContext,
    task: TaskDef,
    *,
    kind: str,
    blocks: Sequence[Block],
    summaries: Sequence[str] = (),
    module: str | None = None,
) -> Result:
    """装配上下文 -> 会话轮换判定 -> 调用后端 -> 记录用量。"""
    system = SYSTEM_PROMPTS.get(kind, "")
    tc = build_task_context(
        task_id=task.task_id,
        phase=task.phase,
        system=system,
        blocks=list(blocks),
        summaries=list(summaries),
        tokenizer=ctx.tokenizer,
        budget=ctx.budget,
        effort=task.effort,
        max_output_tokens=task.max_output_tokens,
        timeout_sec=task.timeout_sec,
        route=task.route,
        extra=task.payload,
    )
    ctx.sessions.ensure(
        module=module,
        next_prompt_tokens=tc.expected_prompt_tokens or 0,
        summary_text=ctx.last_digest,
    )
    result = ctx.backend.complete(tc)
    ctx.sessions.record_turn(result.prompt_tokens, accepted=True)
    ctx.last_digest = digest(result.text, task_id=task.task_id)
    if result.truncated and ctx.logger:
        # 规格书第三节第 3 条：截断即提示切分粒度需要调整
        ctx.logger.warning(
            "任务 %s 输出触及 max_output_tokens=%d（TRUNCATED），该任务的切分粒度需调整",
            task.task_id,
            task.max_output_tokens,
        )
    if ctx.logger:
        ctx.logger.info(
            "任务 %s(%s) 完成 tokens=%d/%d flags=%s",
            task.task_id,
            kind,
            result.prompt_tokens,
            result.completion_tokens,
            result.flags,
        )
    return result


def _rows_from_output(parsed: Any) -> list[dict]:
    if isinstance(parsed, list):
        return [r for r in parsed if isinstance(r, dict)]
    if isinstance(parsed, dict):
        for key in ("items", "rows", "files", "edges", "modules", "violations"):
            value = parsed.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _layer_of(rel: str) -> str:
    lowered = rel.replace("\\", "/").lower()
    if lowered.endswith(".jsp") or lowered.endswith(".html"):
        return "jsp"
    for token, layer in LAYER_BY_PATH:
        if token in lowered:
            return layer
    return "other"


# --------------------------------------------------------------------------- P0


def stage_baseline(ctx: StageContext, task: TaskDef) -> StageResult:
    """P0 基线扫描：纯脚本，零 LLM 调用。"""
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


# --------------------------------------------------------------------------- P1


def stage_classify(ctx: StageContext, task: TaskDef) -> StageResult:
    """P1 文件分类打标：LLM 打标，脚本校验覆盖面。"""
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


def _p1_rows(ctx: StageContext) -> list[dict]:
    rows: list[dict] = []
    for name in ctx.artifacts.list_phase("p1"):
        if not name.endswith(".jsonl"):
            continue
        for line in ctx.artifacts.read_text(f"p1/{name}").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


# --------------------------------------------------------------------------- P2


def _script_module_summary(facts: dict, *, compact: bool = False) -> list[dict]:
    """脚本切分出的模块骨架。

    Args:
        compact: True 时只给名字/类/表/页面，用于把 prompt 压到最小，
                 避免模型被冗长骨架带偏而写出超长输出（首夜实测教训）。
    """
    out = []
    for mod in facts.get("modules") or []:
        item = {
            "domain": mod.get("domain"),
            "servlet": mod.get("servlet"),
            "biz": mod.get("biz"),
            "dao": mod.get("dao"),
            "entity": mod.get("entity"),
            "tables": mod.get("tables"),
            "pages": (mod.get("pages") or [])[:30],
        }
        if compact:
            item = {
                "domain": mod.get("domain"),
                "servlet": [s.rsplit(".", 1)[-1] for s in (mod.get("servlet") or [])],
                "tables": mod.get("tables"),
                "pages": [p.rsplit("/", 1)[-1] for p in (mod.get("pages") or [])[:8]],
            }
        out.append(item)
    return out


def stage_modules(ctx: StageContext, task: TaskDef) -> StageResult:
    """P2 模块边界推断：脚本给路由与分层，LLM 只做归并。"""
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


# --------------------------------------------------------------------------- P3


def _script_edges(facts: dict) -> list[dict]:
    """脚本抽取的内部依赖边：import + extends/implements。"""
    java = facts["project"].get("java") or []
    simple_to_file: dict[str, str] = {}
    for unit in java:
        for t in unit.get("types") or []:
            simple_to_file.setdefault(t.get("type", ""), unit.get("file", ""))

    edges: list[dict] = []
    for unit in java:
        src = unit.get("file")
        for imp in unit.get("imports") or []:
            simple = imp.rsplit(".", 1)[-1]
            target = simple_to_file.get(simple)
            edges.append(
                {
                    "from": src,
                    "to": target or imp,
                    "kind": "import-internal" if target else "import-external",
                    "import": imp,
                }
            )
        for t in unit.get("types") or []:
            for parent in list(t.get("extends") or []) + list(t.get("implements") or []):
                target = simple_to_file.get(parent.rsplit(".", 1)[-1])
                if target and target != src:
                    edges.append({"from": src, "to": target, "kind": "extends", "import": parent})
    return edges


#: 需要报警的跨层跳转（细分层 -> 粗分层）
_SUSPICIOUS = (("jsp", "dao"), ("jsp", "biz"), ("servlet", "dao"), ("dao", "servlet"), ("entity", "dao"))


def _edge_views(edges: list[dict]) -> tuple[str, str, str]:
    """把边压成三张小视图：跨层统计 / 可疑边 / 未解析外部依赖。"""
    matrix: dict[str, int] = {}
    for edge in edges:
        key = f"{_layer_of(edge['from'])} -> {_layer_of(str(edge['to']))}"
        matrix[key] = matrix.get(key, 0) + 1
    matrix_text = "\n".join(f"{k}: {v}" for k, v in sorted(matrix.items(), key=lambda kv: -kv[1]))

    susp = []
    external = []
    for edge in edges:
        src_layer, dst_layer = _layer_of(edge["from"]), _layer_of(str(edge["to"]))
        if (src_layer, dst_layer) in _SUSPICIOUS:
            susp.append(f"{edge['from']} -> {edge['to']} ({src_layer}->{dst_layer})")
        if edge["kind"] == "import-external" and edge.get("import", "").startswith("com."):
            external.append(edge["import"])

    return (
        matrix_text or "（无内部依赖边）",
        "\n".join(susp[:60]) or "（未发现跨层直连）",
        "\n".join(sorted(set(external))[:60]) or "（无项目内 com.* 外部依赖）",
    )


def stage_deps(ctx: StageContext, task: TaskDef) -> StageResult:
    """P3 依赖抽取。

    脚本边**无条件先落盘**——即使 LLM 这一步失败，依赖事实也不丢。
    LLM 只做违规判定，输入是压缩视图，输出很短，天然避开 TRUNCATED。
    """
    facts = ctx.facts_or_load()
    edges = _script_edges(facts)
    artifact = ctx.artifacts.write_jsonl("p3/deps.jsonl", edges)

    matrix_text, suspicious_text, external_text = _edge_views(edges)
    blocks = [
        Block(name="跨层依赖统计", text=matrix_text),
        Block(name="可疑跨层直连", text=suspicious_text),
        Block(name="未解析外部依赖", text=external_text),
        Block(name="脚本模块切分", text=json.dumps(_script_module_summary(facts), ensure_ascii=False)[:8000]),
    ]

    result = _call(ctx, task, kind="deps", blocks=blocks)
    parsed = require(result.text, task.acceptance, task_id=task.task_id)
    violations = parsed.get("violations") if isinstance(parsed, dict) else None
    ctx.artifacts.write_json(
        "p3/violations.json",
        {
            "count": len(violations or []),
            "violations": violations or [],
            "external": (parsed or {}).get("external", []) if isinstance(parsed, dict) else [],
            "notes": (parsed or {}).get("notes", "") if isinstance(parsed, dict) else "",
        },
    )

    matrix = ["# P3 分层依赖矩阵", "", f"- 脚本抽取边数：{len(edges)}", "", "| 方向 | 条数 |", "|---|---|"]
    for line in matrix_text.splitlines():
        if ": " in line:
            direction, count = line.rsplit(": ", 1)
            matrix.append(f"| {direction} | {count} |")
    if violations:
        matrix += ["", "## LLM 标记的跨层违规", ""]
        matrix += [f"- {v.get('from')} -> {v.get('to')}：{v.get('reason', '')}" for v in violations[:40]]
    ctx.artifacts.write_md("p3/layer_matrix", "\n".join(matrix) + "\n")

    return StageResult(text=result.text, artifact=artifact,
                        extra={"edges": len(edges), "violations": len(violations or [])}, result=result)


# --------------------------------------------------------------------------- P4


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


def stage_architecture(ctx: StageContext, task: TaskDef) -> StageResult:
    """P4 架构摘要 + 风险。

    一个任务覆盖全部模块（`payload.module = "auto"`），逐个模块调用并落盘：
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


# --------------------------------------------------------------------------- P5


def stage_report(ctx: StageContext, task: TaskDef) -> StageResult:
    """P5 晨报汇总：纯脚本聚合，保证最后一步不依赖后端。"""
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


# --------------------------------------------------------------------------- 分发


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
