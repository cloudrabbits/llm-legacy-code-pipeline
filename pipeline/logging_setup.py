"""分类日志与按天轮转。

当前只有一类：`orchestrator`。显存采样另走 `runtime/<slug>/logs/gpu.jsonl`
（由 `pipeline/monitor.py` 自行 append），看门狗日志由
`ops/watchdog.ps1` / `ops/deploy/linux/watchdog.sh` 自行写 `logs/watchdog.log`——
两者都不经过本文件的 logger，因此这里不预留它们的分类。
`TimedRotatingFileHandler(backupCount=14)` 保证只保留 14 天。
"""

from __future__ import annotations

import glob
import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler

from .util import ensure_dir

__all__ = ["CATEGORIES", "setup_logging", "get_logger", "prune_old_logs"]

#: 只声明**真正有人在写**的分类。
#: 历史上一度声明了 backend / gpu / watchdog，但 Python 侧从未有人取用这三个
#: logger（`monitor.py` 的显存采样是自行 append `gpu.jsonl`），结果每天旋转出
#: 三个恒为 0 字节的空文件。删掉它们不影响任何输出，只去掉噪音。
CATEGORIES = ("orchestrator",)
_PREFIX = "nightly"

#: 已配置的日志目录（进程内重复初始化或换目录时用于重建 handler）
_CONFIGURED_DIR: dict[str, str | None] = {"dir": None}


def setup_logging(
    log_dir: str = "logs",
    *,
    retention_days: int = 14,
    level: str | int = logging.INFO,
    console: bool = True,
    console_level: str | int = logging.WARNING,
) -> logging.Logger:
    """初始化四类日志，返回 orchestrator 日志器。

    Args:
        log_dir: 日志目录。
        retention_days: 轮转保留天数（规格书要求 14 天）。
        level: 文件日志级别。
        console: 是否同时输出到控制台（手动触发时便于观察）。
    """
    ensure_dir(log_dir)
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    if isinstance(console_level, str):
        console_level = getattr(logging, console_level.upper(), logging.WARNING)

    # 换了目录（多进程测试 / 重跑不同 runtime）时必须重建 handler，否则日志写不回新目录
    current_dir = os.path.abspath(log_dir)
    if _CONFIGURED_DIR["dir"] and _CONFIGURED_DIR["dir"] != current_dir:
        for category in CATEGORIES:
            existing = logging.getLogger(f"{_PREFIX}.{category}")
            for handler in list(existing.handlers):
                if getattr(handler, "_nightly_category", None):
                    existing.removeHandler(handler)
                    handler.close()
    _CONFIGURED_DIR["dir"] = current_dir

    for category in CATEGORIES:
        logger = logging.getLogger(f"{_PREFIX}.{category}")
        logger.setLevel(level)
        logger.propagate = False
        # 重复调用（测试 / 重启）时不叠加 handler
        if any(getattr(h, "_nightly_category", None) == category for h in logger.handlers):
            continue

        handler = TimedRotatingFileHandler(
            os.path.join(log_dir, f"{category}.log"),
            when="midnight",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(formatter)
        handler._nightly_category = category  # type: ignore[attr-defined]
        logger.addHandler(handler)

        if console:
            stream = logging.StreamHandler()
            stream.setLevel(console_level)
            stream.setFormatter(formatter)
            stream._nightly_category = category  # type: ignore[attr-defined]
            logger.addHandler(stream)

    return get_logger("orchestrator")


def get_logger(category: str = "orchestrator") -> logging.Logger:
    """取某个分类的日志器；未初始化时也能安全使用（退化为根日志器命名的子日志器）。"""
    return logging.getLogger(f"{_PREFIX}.{category}")


def prune_old_logs(log_dir: str = "logs", retention_days: int = 14) -> int:
    """删除超过保留天数的轮转日志（TimedRotatingFileHandler 已做，这里是兜底）。

    Returns:
        被删除的文件数。
    """
    if not os.path.isdir(log_dir):
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for path in glob.glob(os.path.join(log_dir, "*.log.*")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed
