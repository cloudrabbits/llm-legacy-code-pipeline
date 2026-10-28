"""产物验收：JSON 提取与各类断言。"""

from __future__ import annotations

import json

import pytest

from pipeline.acceptance import extract_json, require, validate_output
from pipeline.errors import ValidationError
from pipeline.models import Acceptance


def test_extract_json_fenced():
    text = '好的，结果如下：\n```json\n{"items":[{"file":"a"}]}\n```\n以上。'
    assert extract_json(text) == {"items": [{"file": "a"}]}


def test_extract_json_bare():
    assert extract_json('{"modules":[]}') == {"modules": []}


def test_extract_json_with_prose_around():
    text = '分析如下 {"edges":[1,2]} 完毕'
    assert extract_json(text) == {"edges": [1, 2]}


def test_extract_json_none_when_illegal():
    assert extract_json("完全不是 JSON") is None


def test_min_chars():
    ok, _, reason = validate_output("短", Acceptance(min_chars=10))
    assert ok is False and "过短" in reason


def test_required_keys():
    acc = Acceptance(required_keys=["items"])
    ok, parsed, reason = validate_output('{"rows":[]}', acc)
    assert ok is False and "缺少必需键" in reason

    ok, parsed, _ = validate_output('{"items":[]}', acc)
    assert ok and parsed == {"items": []}


def test_regex_must():
    acc = Acceptance(regex_must=[r'"layer"\s*:\s*"(biz|dao)"'])
    assert validate_output('{"layer":"biz"}', acc)[0] is True
    assert validate_output('{"layer":"unknown"}', acc)[0] is False


def test_llm_free_only_checks_length():
    acc = Acceptance(llm_free=True, min_chars=5)
    ok, parsed, _ = validate_output("纯脚本产物，不是 JSON", acc)
    assert ok and parsed == "纯脚本产物，不是 JSON"


def test_schema_ref(tmp_path):
    schema = {
        "type": "object",
        "required": ["modules"],
        "properties": {"modules": {"type": "array", "minItems": 1}},
    }
    path = tmp_path / "modules.schema.json"
    path.write_text(json.dumps(schema), encoding="utf-8")

    acc = Acceptance(schema_ref=str(path))
    assert validate_output('{"modules":[{"name":"x"}]}', acc)[0] is True
    assert validate_output('{"modules":[]}', acc)[0] is False


def test_missing_schema_file_rejected():
    acc = Acceptance(schema_ref="not-exist.schema.json")
    ok, _, reason = validate_output('{"a":1}', acc)
    assert ok is False and "找不到 JSON Schema" in reason


def test_require_raises_validation_error():
    with pytest.raises(ValidationError):
        require("不是 JSON", Acceptance(required_keys=["items"]), task_id="t1")
