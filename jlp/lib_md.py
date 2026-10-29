"""Markdown 渲染辅助 + 原子写。

Windows 注意：
  * 统一以 LF 落盘（newline="\\n"），避免跨平台 diff 噪声；
  * 先写 .tmp 再 os.replace，保证不会留下半截文件；
  * 单元格中的 `|` 会被转义，防止撑破 Markdown 表格。
"""

from __future__ import annotations

import os

import datetime


def h(level: int, text: str) -> str:
    return f"{'#' * level} {text}"


def esc(cell) -> str:
    s = "" if cell is None else str(cell)
    return s.replace("|", "\\|").replace("\n", " ").strip()


def table(headers, rows, empty_hint: str = "（无）") -> str:
    """渲染 Markdown 表格；rows 为空时返回提示行，避免出现无表头空表。"""
    if not rows:
        return f"{empty_hint}\n"
    head = "| " + " | ".join(esc(x) for x in headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    body = ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join([head, sep] + body) + "\n"


def bullets(items, prefix: str = "- ") -> str:
    items = [i for i in items if i not in (None, "")]
    if not items:
        return "（无）\n"
    return "\n".join(prefix + str(i) for i in items) + "\n"


def code(text: str, lang: str = "") -> str:
    body = text.rstrip("\n")
    fence = "```"
    return f"{fence}{lang}\n{body}\n{fence}\n"


def kv(pairs) -> str:
    return table(["项", "值"], [[k, v] for k, v in pairs])


def write_atomic(path: str, text: str) -> str:
    """写文件：临时文件 -> fsync -> rename。Windows 下 rename 到已存在文件需先删。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):
        os.remove(path)
    os.replace(tmp, path)
    return path


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
