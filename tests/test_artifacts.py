"""产物与摘要仓库。"""

from __future__ import annotations

import json
import os

import pytest

from pipeline.artifacts import ArtifactStore, SummaryStore
from pipeline.errors import ValidationError
from pipeline.tokenizer import Tokenizer

TOK = Tokenizer(prefer="heuristic")


def test_write_json_is_atomic_and_no_tmp_left(tmp_path):
    store = ArtifactStore(root=str(tmp_path / "artifacts"))
    path = store.write_json("p1/classify-0001.json", {"rows": [1, 2, 3]})
    assert os.path.exists(path)
    leftovers = [p for p in os.listdir(os.path.dirname(path)) if p.startswith(".tmp-")]
    assert not leftovers
    assert store.read_json("p1/classify-0001.json") == {"rows": [1, 2, 3]}


def test_write_jsonl(tmp_path):
    store = ArtifactStore(root=str(tmp_path / "artifacts"))
    store.write_jsonl("p1/rows.jsonl", [{"a": 1}, {"a": 2}])
    lines = store.read_text("p1/rows.jsonl").strip().splitlines()
    assert [json.loads(x) for x in lines] == [{"a": 1}, {"a": 2}]


def test_write_md_adds_extension(tmp_path):
    store = ArtifactStore(root=str(tmp_path / "artifacts"))
    path = store.write_md("p4/users", "# 摘要")
    assert path.endswith("users.md")


def test_path_escape_rejected(tmp_path):
    store = ArtifactStore(root=str(tmp_path / "artifacts"))
    with pytest.raises(ValidationError):
        store.write_text("../../evil.txt", "x")


def test_list_phase(tmp_path):
    store = ArtifactStore(root=str(tmp_path / "artifacts"))
    store.write_json("p2/modules.json", {})
    store.write_json("p2/edges.jsonl", {})
    assert store.list_phase("p2") == ["edges.jsonl", "modules.json"]


def test_summary_store_respects_token_cap(tmp_path):
    store = SummaryStore(root=str(tmp_path / "summaries"), max_tokens=200, tokenizer=TOK)
    ok = store.write("session-0001", "摘要" * 20)
    assert os.path.exists(ok)
    with pytest.raises(ValidationError):
        store.write("session-0002", "很长的摘要" * 500)


def test_summary_store_recent_ordering(tmp_path):
    store = SummaryStore(root=str(tmp_path / "summaries"), tokenizer=TOK)
    for i in range(4):
        store.write(store.session_name(i + 1, "users"), f"第{i + 1}轮")
    assert store.recent(2) == ["session-0003-users.md", "session-0004-users.md"]
    assert store.load_recent_texts(1) == ["第4轮"]
