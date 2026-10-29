"""P3 依赖抽取。

脚本边**无条件先落盘**——即使 LLM 这一步失败，依赖事实也不丢。
LLM 只做违规判定，输入是压缩视图，输出很短，天然避开 TRUNCATED。
"""

from __future__ import annotations

import json

from ..acceptance import require
from ..models import TaskDef
from .common import Block, StageContext, StageResult, _call, _layer_of, _script_module_summary


def stage_deps(ctx: StageContext, task: TaskDef) -> StageResult:
    """产出 `p3/deps.jsonl`（脚本事实）+ `p3/violations.json`（LLM 判定）。"""
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
