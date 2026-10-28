"""产物验收。

验收标准必须**可自动校验**（规格书第五节第 1 条）。LLM 的产出先过这里，
不过就判 `ValidationError`，由编排器决定重试还是标记 NEEDS_REVIEW。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .errors import ValidationError
from .models import Acceptance

__all__ = ["extract_json", "validate_output", "SCHEMA_DIR"]

SCHEMA_DIR = os.path.join("schemas")

_FENCE = re.compile(r"```(?:json|jsonl)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """从 LLM 输出里提取 JSON：优先 ```json 围栏，其次首个 {...} / [...] 片段。"""
    stripped = text.strip()
    match = _FENCE.search(stripped)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _load_schema(ref: str) -> dict | None:
    path = ref if os.path.isabs(ref) else os.path.join(SCHEMA_DIR, ref)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_output(text: str, acceptance: Acceptance | None = None, *, task_id: str = "") -> tuple[bool, Any, str]:
    """校验产出文本。

    Returns:
        (ok, parsed, reason)：ok=True 时 reason 为空串。
    """
    if acceptance is None:
        return True, text, ""
    if acceptance.llm_free:
        # 纯脚本阶段：只校验长度
        if len(text) < acceptance.min_chars:
            return False, text, f"产出过短：{len(text)} < {acceptance.min_chars}"
        return True, text, ""

    if len(text.strip()) < acceptance.min_chars:
        return False, text, f"产出过短：{len(text.strip())} < {acceptance.min_chars}"

    for pattern in acceptance.regex_must:
        if not re.search(pattern, text):
            return False, text, f"未命中必需模式: {pattern}"

    needs_json = bool(acceptance.required_keys or acceptance.schema_ref)
    parsed: Any = text
    if needs_json:
        parsed = extract_json(text)
        if parsed is None:
            return False, text, "产出中找不到合法 JSON"

        if acceptance.required_keys:
            if not isinstance(parsed, dict):
                return False, parsed, f"产出应为对象，实际为 {type(parsed).__name__}"
            missing = [k for k in acceptance.required_keys if k not in parsed]
            if missing:
                return False, parsed, f"缺少必需键: {missing}"

        if acceptance.schema_ref:
            schema = _load_schema(acceptance.schema_ref)
            if schema is None:
                return False, parsed, f"找不到 JSON Schema: {acceptance.schema_ref}"
            try:
                import jsonschema  # 延迟导入：未配置 schema 时不需要

                jsonschema.validate(parsed, schema)
            except Exception as exc:  # noqa: BLE001
                return False, parsed, f"JSON Schema 校验失败: {exc}"

    return True, parsed, ""


def require(text: str, acceptance: Acceptance | None, *, task_id: str = "") -> Any:
    """校验失败即抛 ValidationError（编排器按异常分类处理）。"""
    ok, parsed, reason = validate_output(text, acceptance, task_id=task_id)
    if not ok:
        raise ValidationError(f"任务 {task_id} 验收不通过: {reason}", task_id=task_id, rule="acceptance")
    return parsed
