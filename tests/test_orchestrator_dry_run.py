"""编排器 dry-run 集成测试：断点续跑 + 产物落盘 + 检查点收尾。

用合成小项目，不依赖真实老项目路径，也不发任何网络请求。
"""

from __future__ import annotations

import json
import os

import pytest

import orchestrator
from pipeline.checkpoint import Checkpoint
from pipeline.util import project_slug


@pytest.fixture
def sample_project(tmp_path):
    root = tmp_path / "demo"
    (root / "src" / "com" / "demo").mkdir(parents=True)
    (root / "WebRoot" / "WEB-INF").mkdir(parents=True)
    (root / "src" / "com" / "demo" / "UsersDao.java").write_text(
        "package com.demo;\nimport java.util.List;\n"
        "public class UsersDao { public List<String> findAll() { return null; } }\n",
        encoding="utf-8",
    )
    (root / "src" / "com" / "demo" / "UsersServlet.java").write_text(
        "package com.demo;\npublic class UsersServlet { private UsersDao dao = new UsersDao(); }\n",
        encoding="utf-8",
    )
    (root / "WebRoot" / "userList.jsp").write_text("<%@ page contentType=\"text/html\" %>\n", encoding="utf-8")
    (root / "WebRoot" / "WEB-INF" / "web.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<web-app xmlns="http://java.sun.com/xml/ns/javaee" version="2.5">
  <servlet><servlet-name>UsersServlet</servlet-name>
    <servlet-class>com.demo.UsersServlet</servlet-class></servlet>
  <servlet-mapping><servlet-name>UsersServlet</servlet-name>
    <url-pattern>/Users.do</url-pattern></servlet-mapping>
</web-app>
""",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def tasks_dir(tmp_path):
    directory = tmp_path / "tasks"
    directory.mkdir()
    (directory / "p0.json").write_text(
        json.dumps(
            [{"task_id": "P0-baseline", "phase": "P0", "kind": "baseline",
              "acceptance": {"llm_free": True, "min_chars": 10}}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (directory / "p5.json").write_text(
        json.dumps(
            [{"task_id": "P5-report", "phase": "P5", "kind": "report",
              "depends_on": ["P0-baseline"], "acceptance": {"llm_free": True, "min_chars": 10}}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return directory


def run_once(sample_project, tasks_dir, runtime, max_tasks=None):
    argv = [
        "--project", str(sample_project),
        "--dry-run",
        "--tasks", str(tasks_dir),
        "--runtime", str(runtime),
        "--budget", str(os.path.abspath(os.path.join("config", "budget.yaml"))),
    ]
    if max_tasks is not None:
        argv += ["--max-tasks", str(max_tasks)]
    args = orchestrator.parse_args(argv)
    return orchestrator.run(args)


def test_dry_run_end_to_end(sample_project, tasks_dir, tmp_path):
    runtime = tmp_path / "runtime"
    assert run_once(sample_project, tasks_dir, runtime) == 0

    assert (runtime / "artifacts" / "p0" / "inventory.json").exists()
    assert (runtime / "artifacts" / "p0" / "baseline.md").exists()
    assert (runtime / "artifacts" / "p5" / "nightly_report.md").exists()
    assert (runtime / "state" / "index.json").exists()

    ckpt = Checkpoint(
        path=str(runtime / "state" / "checkpoint.jsonl"),
        index_path=str(runtime / "state" / "index.json"),
    )
    assert ckpt.state.tasks["P0-baseline"].status == "succeeded"
    assert ckpt.state.tasks["P5-report"].status == "succeeded"
    assert ckpt.state.ended_ts, "收尾必须写 RUN_END"


def test_resume_skips_finished_tasks(sample_project, tasks_dir, tmp_path):
    runtime = tmp_path / "runtime"
    assert run_once(sample_project, tasks_dir, runtime) == 0

    ckpt = Checkpoint(
        path=str(runtime / "state" / "checkpoint.jsonl"),
        index_path=str(runtime / "state" / "index.json"),
    )
    seq_before = ckpt.state.seq

    # 第二次运行：所有任务都已终态，只应追加 RUN_START/RUN_END，不重复执行
    assert run_once(sample_project, tasks_dir, runtime) == 0
    ckpt2 = Checkpoint(
        path=str(runtime / "state" / "checkpoint.jsonl"),
        index_path=str(runtime / "state" / "index.json"),
    )
    assert ckpt2.state.seq > seq_before
    assert ckpt2.state.tasks["P0-baseline"].attempts == 1, "已完成的任务不得重复执行"


def test_max_tasks_limits_queue(sample_project, tasks_dir, tmp_path):
    runtime = tmp_path / "runtime"
    assert run_once(sample_project, tasks_dir, runtime, max_tasks=1) == 0
    ckpt = Checkpoint(
        path=str(runtime / "state" / "checkpoint.jsonl"),
        index_path=str(runtime / "state" / "index.json"),
    )
    assert ckpt.state.tasks["P0-baseline"].status == "succeeded"
    # P5 由收尾兜底逻辑补跑（P5 是纯脚本，必须尽最大努力产出晨报）
    assert ckpt.state.tasks["P5-report"].status == "succeeded"


def test_heartbeat_and_logs_written(sample_project, tasks_dir, tmp_path):
    runtime = tmp_path / "runtime"
    assert run_once(sample_project, tasks_dir, runtime) == 0
    assert (runtime / "state" / "heartbeat.json").exists()
    assert (runtime / "logs" / "orchestrator.log").exists()


def test_guard_refuses_different_project_same_runtime(sample_project, tasks_dir, tmp_path):
    """身份守卫：同一 runtime 被另一个项目复用时，必须拒绝而非静默跳过。"""
    runtime = tmp_path / "runtime"
    assert run_once(sample_project, tasks_dir, runtime) == 0

    other = tmp_path / "other_demo"
    other.mkdir()
    with pytest.raises(orchestrator.PipelineError):
        run_once(other, tasks_dir, runtime)


def test_default_runtime_is_project_scoped(sample_project, tasks_dir, tmp_path, monkeypatch):
    """未显式给 --runtime 时，产物应按项目派生 runtime/<slug>/ 隔离。"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.chdir(tmp_path)
    argv = [
        "--project", str(sample_project),
        "--dry-run",
        "--tasks", str(tasks_dir),
        "--config", os.path.join(repo_root, "config", "pipeline.yaml"),
        "--budget", os.path.join(repo_root, "config", "budget.yaml"),
    ]
    args = orchestrator.parse_args(argv)
    assert orchestrator.run(args) == 0
    slug = project_slug(str(sample_project))
    assert (tmp_path / "runtime" / slug / "state" / "checkpoint.jsonl").exists()
    assert (tmp_path / "runtime" / slug / "artifacts" / "p0" / "baseline.md").exists()


def test_project_runtime_slug_is_stable_and_safe():
    """slug 规则由 pipeline/util.py 的 project_slug 提供（跨语言唯一真源）。

    规则一致性本身由 tests/test_slug_consistency.py 三方比对，这里只锚定
    编排器拿到的值符合直觉。
    """
    assert project_slug("D:\\IdeaProjects\\supermarketmanager") == "supermarketmanager"
    assert project_slug("/data/my project v2/") == "my_project_v2"
    # 不同路径、同名目录应产生相同 slug（靠身份守卫而非 slug 区分）
    a = project_slug("/data/foo")
    b = project_slug("/backup/foo")
    assert a == b == "foo"
