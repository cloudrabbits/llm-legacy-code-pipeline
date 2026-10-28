"""心跳与显存采样。"""

from __future__ import annotations

import json
import os
import time

import pytest

from pipeline import monitor as monitor_module
from pipeline.monitor import Monitor, heartbeat_age_sec, query_gpu


def test_beat_writes_heartbeat(tmp_path):
    path = str(tmp_path / "heartbeat.json")
    mon = Monitor(heartbeat_path=path, gpu_log_path=str(tmp_path / "gpu.jsonl"))
    assert mon.beat() is True
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["pid"] == os.getpid()
    assert "ts" in data and "epoch" in data


def test_beat_throttled_within_interval(tmp_path):
    mon = Monitor(
        heartbeat_path=str(tmp_path / "hb.json"),
        gpu_log_path=None,
        heartbeat_interval_sec=30,
    )
    assert mon.beat() is True
    assert mon.beat() is False, "间隔内不应重复写盘"
    assert mon.beat(force=True) is True


def test_heartbeat_age(tmp_path):
    path = str(tmp_path / "hb.json")
    mon = Monitor(heartbeat_path=path, gpu_log_path=None)
    mon.beat()
    assert heartbeat_age_sec(path) is not None
    assert heartbeat_age_sec(path) < 5
    assert heartbeat_age_sec(str(tmp_path / "nope.json")) is None


def test_gpu_sampled_every_n_tasks(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        monitor_module,
        "query_gpu",
        lambda *a, **k: [monitor_module.GpuSample("ts", 0, "L20", 1000, 46000, 55)],
    )
    mon = Monitor(
        heartbeat_path=str(tmp_path / "hb.json"),
        gpu_log_path=str(tmp_path / "gpu.jsonl"),
        gpu_sample_every_tasks=3,
    )
    for i in range(6):
        samples = mon.on_task_finished()
        if i in (2, 5):
            assert len(samples) == 1
            calls["n"] += 1
        else:
            assert samples == []
    assert calls["n"] == 2
    with open(str(tmp_path / "gpu.jsonl"), "r", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    assert len(rows) == 2
    assert rows[0]["samples"][0]["memory_used_mb"] == 1000


def test_query_gpu_absent_returns_empty(monkeypatch):
    """没有 nvidia-smi 时必须优雅降级，而不是让整条流水线挂掉。"""
    import subprocess

    def boom(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(subprocess, "run", boom)
    assert query_gpu() == []


def test_monitor_tolerates_missing_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_module, "query_gpu", lambda *a, **k: [])
    mon = Monitor(heartbeat_path=str(tmp_path / "hb.json"), gpu_log_path=str(tmp_path / "gpu.jsonl"))
    assert mon.sample_gpu() == []
    assert not os.path.exists(str(tmp_path / "gpu.jsonl"))
