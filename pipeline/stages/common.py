"""P0–P5 阶段处理器的公共部分。

原来这些全部挤在单个 `stages.py`（677 行）里。按阶段拆开后，
跨阶段共用的装配 / 读取 / 视图 helper 集中在本文件——否则 p3 要用 p2 的
`_script_module_summary`、p4 要用 p1 的 `_p1_rows`，就会形成阶段之间的横向依赖。

分工原则（沿用 `jlp` 的「事实优先」）：
    * P0 / P3 依赖边 / P2 骨架 —— **脚本算**，LLM 不产生事实。
    * P1 打标 / P2 边界归并 / P3 违规核对 / P4 摘要与风险 —— LLM 做归类与叙述，
      产出必须过 `acceptance.py` 的自动校验。
    * P5 晨报 —— 纯脚本聚合，保证夜里最后一步不会因为后端抖动而失败。

教训（首夜实测）：让模型「复述」大表会撑爆 max_tokens 并截断成非法 JSON。
因此凡是脚本已经算出来的事实，一律先落盘，只把**压缩视图**交给模型。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..artifacts import ArtifactStore, SummaryStore
from ..context import Block, build_task_context
from ..models import Budget, Result, TaskDef
from ..scan import load_project_facts

__all__ = [
    "Block",
    "StageContext",
    "StageResult",
    "SYSTEM_PROMPTS",
    "LAYER_VALUES",
    "LAYER_BY_PATH",
    "DIGEST_CHARS",
    "digest",
    "_call",
    "_rows_from_output",
    "_layer_of",
    "_p1_rows",
    "_script_module_summary",
]

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


# --------------------------------------------------------------------------- 产物读取


def _p1_rows(ctx: StageContext) -> list[dict]:
    """读取 P1 阶段全部打标行（P2 / P4 都要用）。"""
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
