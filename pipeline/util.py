"""通用小工具：点号路径读写、原子写、目录准备。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any, Mapping

__all__ = ["get_path", "set_path", "unset_path", "atomic_write_text", "ensure_dir", "utc_now_iso", "project_slug"]


def _split(path: str) -> list[str]:
    """把 `choices.0.message.content` 切成 ['choices','0','message','content']。"""
    return [p for p in path.split(".") if p != ""]


def get_path(data: Any, path: str, default: Any = None) -> Any:
    """按点号路径取值，支持列表下标（数字段）。"""
    cur = data
    for part in _split(path):
        if isinstance(cur, Mapping):
            if part not in cur:
                return default
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                idx = int(part)
            except ValueError:
                return default
            if idx >= len(cur):
                return default
            cur = cur[idx]
        else:
            return default
    return cur


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    """按点号路径写值，中间层自动创建 dict/list。"""
    parts = _split(path)
    cur: Any = data
    for i, part in enumerate(parts[:-1]):
        nxt = parts[i + 1]
        container_is_list = nxt.isdigit()
        if isinstance(cur, list):
            idx = int(part)
            while len(cur) <= idx:
                cur.append(None)
            if cur[idx] is None:
                cur[idx] = [] if container_is_list else {}
            cur = cur[idx]
        else:
            if part not in cur or not isinstance(cur[part], (dict, list)):
                cur[part] = [] if container_is_list else {}
            cur = cur[part]
    last = parts[-1]
    if isinstance(cur, list):
        idx = int(last)
        while len(cur) <= idx:
            cur.append(None)
        cur[idx] = value
    else:
        cur[last] = value


def unset_path(data: dict[str, Any], path: str) -> None:
    """按点号路径删除键；不存在则忽略。"""
    parts = _split(path)
    cur: Any = data
    for part in parts[:-1]:
        cur = get_path(cur, part)
        if cur is None:
            return
    last = parts[-1]
    if isinstance(cur, list):
        try:
            idx = int(last)
            if idx < len(cur):
                cur.pop(idx)
        except ValueError:
            return
    elif isinstance(cur, dict):
        cur.pop(last, None)


def atomic_write_text(path: str, text: str, *, encoding: str = "utf-8") -> None:
    """先写临时文件再 `os.replace`，保证读者永远看到完整文件（Windows/NTFS 同样成立）。"""
    ensure_dir(os.path.dirname(os.path.abspath(path)))
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def atomic_write_json(path: str, obj: Any, *, encoding: str = "utf-8") -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding=encoding)


def ensure_dir(path: str | None) -> None:
    if path:
        os.makedirs(path, exist_ok=True)


def utc_now_iso() -> str:
    """带毫秒的本地 ISO8601 时间戳（北京时间 +08:00 由本机时区决定）。"""
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def project_slug(project: str) -> str:
    """从被分析项目路径派生运行根目录名 `runtime/<slug>/`。

    ★ **唯一真源**：取项目目录名并清洗为安全字符（仅 ASCII 字母数字、点、
    下划线、连字符）。跨语言脚本无法直接调用本函数，因此各自保有一份等价实现：

        PowerShell  ops/watchdog.ps1          Get-ProjectSlug
        bash        ops/deploy/linux/ common.sh _project_slug

    由 `tests/test_slug_consistency.py` 用同一组样例比对三方结果，防止漂移——
    一旦漂移，看门狗会读错心跳路径，进而误杀并重启一个**正在正常运行**的编排器。

    同名目录靠身份守卫（`Checkpoint` 里的 `project` 字段）兜底，
    避免不同路径的同名目录串台。
    """
    name = os.path.basename(os.path.normpath(project)).strip()
    if not name:
        name = "project"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name) or "project"
