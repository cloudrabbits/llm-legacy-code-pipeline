"""资源与存活监控：心跳文件 + 显存水位采样。

心跳：每 30s 原子写一次 `runtime/state/heartbeat.json`；
      看门狗（tools/watchdog.ps1）10 分钟无更新即重启编排器。
显存：每 10 个任务调一次 nvidia-smi，水位写 `logs/gpu.jsonl`，
      用于事后判断是否有显存缓慢增长（KV cache 泄漏）。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

from .util import atomic_write_json, ensure_dir, utc_now_iso

__all__ = ["GpuSample", "Monitor", "query_gpu", "heartbeat_age_sec", "DEFAULT_HEARTBEAT_PATH"]

DEFAULT_HEARTBEAT_PATH = os.path.join("runtime", "state", "heartbeat.json")

#: nvidia-smi 查询字段（CSV，无表头，无单位）
_GPU_QUERY = "index,name,memory.used,memory.total,utilization.gpu"


@dataclass
class GpuSample:
    ts: str
    index: int
    name: str
    memory_used_mb: int
    memory_total_mb: int
    utilization_pct: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "index": self.index,
            "name": self.name,
            "memory_used_mb": self.memory_used_mb,
            "memory_total_mb": self.memory_total_mb,
            "utilization_pct": self.utilization_pct,
        }


def query_gpu(timeout_sec: float = 10.0) -> list[GpuSample]:
    """调 nvidia-smi 采样；机器上没有 GPU 或命令不可用时返回空列表（不抛异常）。"""
    try:
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        proc = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_GPU_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            creationflags=flags,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []

    samples: list[GpuSample] = []
    ts = utc_now_iso()
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            samples.append(
                GpuSample(
                    ts=ts,
                    index=int(float(parts[0])),
                    name=parts[1],
                    memory_used_mb=int(float(parts[2])),
                    memory_total_mb=int(float(parts[3])),
                    utilization_pct=int(float(parts[4])),
                )
            )
        except ValueError:
            continue
    return samples


def heartbeat_age_sec(path: str = DEFAULT_HEARTBEAT_PATH, *, now: float | None = None) -> float | None:
    """心跳文件的年龄（秒）。文件不存在或不可解析时返回 None。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        beat_ts = float(data.get("epoch", 0))
    except Exception:  # noqa: BLE001
        return None
    return (now if now is not None else time.time()) - beat_ts


class Monitor:
    """心跳 + 显存采样的组合开关。"""

    def __init__(
        self,
        heartbeat_path: str = DEFAULT_HEARTBEAT_PATH,
        gpu_log_path: str | None = os.path.join("logs", "gpu.jsonl"),
        *,
        heartbeat_interval_sec: float = 30.0,
        gpu_sample_every_tasks: int = 10,
        logger=None,
    ) -> None:
        self.heartbeat_path = heartbeat_path
        self.gpu_log_path = gpu_log_path
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.gpu_sample_every_tasks = max(1, gpu_sample_every_tasks)
        self.logger = logger
        self._last_beat = 0.0
        self.task_seq = 0
        self.last_gpu: list[GpuSample] = []
        ensure_dir(os.path.dirname(os.path.abspath(heartbeat_path)))
        if gpu_log_path:
            ensure_dir(os.path.dirname(os.path.abspath(gpu_log_path)))

    # ------------------------------------------------------------------ 心跳

    def beat(self, *, force: bool = False, **extra: Any) -> bool:
        """写心跳；距上次不足间隔且非强制时跳过。返回是否真的写了。"""
        now = time.time()
        if not force and now - self._last_beat < self.heartbeat_interval_sec:
            return False
        payload: dict[str, Any] = {
            "ts": utc_now_iso(),
            "epoch": now,
            "pid": os.getpid(),
            "task_seq": self.task_seq,
        }
        payload.update(extra)
        atomic_write_json(self.heartbeat_path, payload)
        self._last_beat = now
        return True

    # ------------------------------------------------------------------ 显存

    def on_task_finished(self) -> list[GpuSample]:
        """每完成一个任务调一次；到第 N 个才真正采样。"""
        self.task_seq += 1
        if self.task_seq % self.gpu_sample_every_tasks != 0:
            return []
        return self.sample_gpu()

    def sample_gpu(self) -> list[GpuSample]:
        """采样并追加一行到 gpu.jsonl。"""
        samples = query_gpu()
        self.last_gpu = samples
        if not samples:
            if self.logger:
                self.logger.debug("nvidia-smi 不可用或无 GPU，跳过显存采样")
            return []
        if self.gpu_log_path:
            line = json.dumps(
                {"task_seq": self.task_seq, "samples": [s.as_dict() for s in samples]},
                ensure_ascii=False,
            )
            with open(self.gpu_log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        if self.logger:
            for s in samples:
                self.logger.info(
                    "GPU[%d] %s 显存 %d/%d MB 利用率 %d%%",
                    s.index,
                    s.name,
                    s.memory_used_mb,
                    s.memory_total_mb,
                    s.utilization_pct,
                )
        return samples
