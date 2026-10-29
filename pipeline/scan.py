"""事实层：调用仓库里既有的静态分析器 `tools/jlp` 取结构化事实。

原则（沿用 tools/jlp 的「事实优先」）：
    **数量、清单、依赖边一律由脚本算出**；LLM 只负责归类、归并、叙述，
    不允许产生事实。因此 P0 / P2 / P3 的骨架全部来自这里。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any, Iterable, Sequence

from .context import Block
from .errors import ConfigError

__all__ = ["ROOT", "JLP_DIR", "load_jlp", "load_registry", "load_project_facts",
           "component_ledger", "platform_deps", "strip_bodies", "source_blocks", "read_source"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JLP_DIR = os.path.join(ROOT, "tools", "jlp")

#: 单文件送入 LLM 的最大字符数（超出截断并标注，避免单块吃掉整个预算）
DEFAULT_MAX_CHARS = 20_000


def _load_module(name: str, path: str):
    """按文件路径加载模块（tools/jlp 不是包，不能 import）。"""
    if not os.path.exists(path):
        raise ConfigError(f"缺少静态分析器: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ConfigError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_JLP_CACHE: dict[str, Any] = {}


def load_jlp() -> tuple[Any, Any]:
    """加载 `lib_scan` 与 `lib_model`。

    `tools/jlp` 内部的模块之间用的是裸 import（`from lib_scan import ...`），
    因此需要把该目录临时放进 `sys.path`。
    """
    if "scan" in _JLP_CACHE:
        return _JLP_CACHE["scan"], _JLP_CACHE["model"]
    if JLP_DIR not in sys.path:
        sys.path.insert(0, JLP_DIR)
    lib_scan = _load_module("jlp_lib_scan", os.path.join(JLP_DIR, "lib_scan.py"))
    lib_model = _load_module("jlp_lib_model", os.path.join(JLP_DIR, "lib_model.py"))
    _JLP_CACHE["scan"] = lib_scan
    _JLP_CACHE["model"] = lib_model
    return lib_scan, lib_model


def load_registry() -> Any:
    """加载 `lib_registry`（组件台账 / 闭源分派 / 模块边界 / 风险规则）。

    配置目录默认 `<仓库>/config/legacy`，可用环境变量 `JLP_RULES_DIR` 覆盖。
    这份配置是**外置输入**，与画像配置同理：加载失败必须快速失败，不能静默降级。
    """
    if "registry" in _JLP_CACHE:
        return _JLP_CACHE["registry"]
    lib_registry = _load_module("jlp_lib_registry", os.path.join(JLP_DIR, "lib_registry.py"))
    _JLP_CACHE["registry"] = lib_registry
    return lib_registry


def strip_bodies(project: dict) -> dict:
    """剥离 `_body`（源码正文只用于构造 prompt，不进产物 JSON）。"""
    for unit in project.get("java") or []:
        unit.pop("_body", None)
    return project


def load_project_facts(project_root: str, *, exclude_dirs: Sequence[str] = ()) -> dict:
    """扫描目标项目，返回事实集合。

    Returns:
        {
          "project": 扫描结果（files/java/jsp/sql/webxml/jars/...），
          "routes":  URL 路由还原结果，
          "modules": 脚本切分出的模块列表（每项含 `domain`）,
          "unassigned": 未归属页面,
        }

    Raises:
        ConfigError: 目标路径不存在，或静态分析器不可用。
    """
    if not os.path.isdir(project_root):
        raise ConfigError(f"目标项目路径不存在或不是目录: {project_root}")
    lib_scan, lib_model = load_jlp()
    project = lib_scan.scan(project_root, exclude_dirs=tuple(exclude_dirs))
    # 组件台账与平台依赖是「事实」，必须在剥 _body 之前算完（正文正则需要源码）
    load_registry().enrich(project)
    routes = lib_model.build_routes(project)
    modules, unassigned, _owner = lib_model.derive_modules(project, routes)
    return {"project": project, "routes": routes, "modules": modules, "unassigned": unassigned}


def component_ledger(facts: dict) -> list[dict]:
    """第三方 / 闭源组件改造台账（`project["components"]`）。"""
    return list((facts.get("project") or {}).get("components") or [])


def platform_deps(facts: dict) -> list[dict]:
    """容器 / JDK / 未知外部提供的依赖（`project["platform_deps"]`）。"""
    return list((facts.get("project") or {}).get("platform_deps") or [])


def module_names(facts: dict) -> list[str]:
    """脚本切分出的模块名（`domain`），供 P4 生成每个模块的摘要任务。"""
    names = []
    for mod in facts.get("modules") or []:
        name = (mod or {}).get("domain")
        if name:
            names.append(name)
    return names


def read_source(rel: str, project_root: str | None = None) -> str:
    """按老项目常见的混编码降级读取源码：`utf-8-sig -> utf-8 -> gb18030 -> latin-1`。"""
    path = rel if os.path.isabs(rel) else os.path.join(project_root or "", rel)
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as fh:
                return fh.read()
        except (UnicodeDecodeError, LookupError):
            continue
    with open(path, "rb") as fh:  # 最后兜底：二进制也能读，只是可能有乱码
        return fh.read().decode("utf-8", errors="replace")


def _truncate(text: str, max_chars: int) -> str:
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + f"\n/* ... 截断，原文共 {len(text)} 字符 ... */"
    return text


def source_blocks(
    facts: dict,
    rels: Iterable[str] | None = None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    project_root: str | None = None,
) -> list[Block]:
    """把源码文件转成输入块（块名 = 仓库相对路径）。

    Args:
        rels: 只取这些文件；None 表示全部 `.java` + `.jsp`。
    """
    project = facts.get("project") or {}
    root = project_root or project.get("root")
    wanted = set(rels) if rels is not None else None

    blocks: list[Block] = []
    for unit in list(project.get("java") or []) + list(project.get("jsp") or []):
        rel = unit.get("file")
        if not rel:
            continue
        if wanted is not None and rel not in wanted:
            continue
        text = unit.get("_body")
        if not text:
            text = read_source(rel, root)
        blocks.append(Block(name=rel, text=_truncate(text, max_chars)))
    return blocks


def rel_list(facts: dict, exts: Sequence[str] = (".java", ".jsp")) -> list[str]:
    """按扩展名列出源码相对路径，供 planner 生成任务。"""
    exts = tuple(e.lower() for e in exts)
    return sorted(
        f["file"] for f in (facts.get("project", {}).get("files") or [])
        if str(f.get("ext", "")).lower() in exts
    )
