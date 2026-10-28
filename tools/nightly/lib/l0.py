#!/usr/bin/env python3
"""L0 确定性图层：用脚本抽取"不可由模型臆造"的结构事实，注入提示词。

实测依据：直连补全时模型会写出
  "I will simulate running `find|wc -l` and report plausible exact numbers"
即无脚本供给时它会编造统计数字。因此行数/类名/方法数/依赖边必须由脚本给出，
模型只负责解释与叙述。

产出 <work>/ai/context/L0-inventory.md（≤20KB）
"""
import argparse
import os
import re
import sys

EXCLUDE = {".git", ".svn", "target", "build", "node_modules", "assets", "docs",
           "reports", "patches", "staging", "ai", "handoff", "tools"}

PKG_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
CLS_RE = re.compile(r"^\s*(?:public\s+)?(?:final\s+|abstract\s+)?(?:class|interface|enum)\s+(\w+)", re.M)
METHOD_RE = re.compile(r"^\s{0,8}(?:public|protected|private)\s+[\w<>\[\],\s\.]+\s+(\w+)\s*\(", re.M)
IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)", re.I)
SCRIPTLET_RE = re.compile(r"<%[-=]?")


def walk(root, exts):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        for fn in sorted(files):
            if fn.endswith(exts):
                yield os.path.join(dirpath, fn)


def lines_of(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-bytes", type=int, default=20000)
    a = ap.parse_args()

    java = list(walk(a.src, (".java",)))
    jsp = list(walk(a.src, (".jsp",)))
    sql = list(walk(a.src, (".sql",)))
    xml = list(walk(a.src, (".xml",)))

    rows = []
    pkg_stat = {}
    local_classes = {}   # 简单类名 -> 路径
    imports_by_file = {}
    total_java = 0

    for p in java:
        txt = lines_of(p)
        rel = os.path.relpath(p, a.src)
        nl = txt.count("\n") + 1
        total_java += nl
        pkg = (PKG_RE.search(txt) or [None, "?"])[1] if PKG_RE.search(txt) else "?"
        cls = CLS_RE.findall(txt)
        methods = METHOD_RE.findall(txt)
        cname = cls[0] if cls else os.path.splitext(os.path.basename(p))[0]
        local_classes[cname] = rel
        imports_by_file[rel] = IMPORT_RE.findall(txt)
        rows.append((rel, nl, pkg, cname, len(methods)))
        s = pkg_stat.setdefault(pkg, {"files": 0, "lines": 0, "methods": 0})
        s["files"] += 1
        s["lines"] += nl
        s["methods"] += len(methods)

    out = []
    out.append("# L0 确定性图层（脚本生成，行数来自 wc -l，禁止模型改写）\n")
    out.append("## 总量")
    out.append("| 维度 | 数量 |")
    out.append("|---|---|")
    out.append(f"| Java 文件 | {len(java)} |")
    out.append(f"| Java 总行数 | {total_java} |")
    out.append(f"| JSP 文件 | {len(jsp)} |")
    out.append(f"| SQL 文件 | {len(sql)} |")
    out.append(f"| XML 文件 | {len(xml)} |")
    out.append("")

    out.append("## 包级统计")
    out.append("| 包 | 文件数 | 行数 | 方法数 |")
    out.append("|---|---|---|---|")
    for pkg, s in sorted(pkg_stat.items(), key=lambda kv: -kv[1]["lines"]):
        out.append(f"| {pkg} | {s['files']} | {s['lines']} | {s['methods']} |")
    out.append("")

    out.append("## Java 文件清单（相对路径 | 行数 | 包 | 主类 | 方法数）")
    out.append("| 文件 | 行数 | 包 | 类 | 方法数 |")
    out.append("|---|---|---|---|---|")
    for rel, nl, pkg, cname, nm in sorted(rows, key=lambda r: -r[1]):
        out.append(f"| {rel} | {nl} | {pkg} | {cname} | {nm} |")
    out.append("")

    out.append("## JSP 文件清单（行数 | scriptlet 块数）")
    out.append("| 文件 | 行数 | scriptlet 块 |")
    out.append("|---|---|---|")
    for p in jsp:
        txt = lines_of(p)
        rel = os.path.relpath(p, a.src)
        out.append(f"| {rel} | {txt.count(chr(10)) + 1} | {len(SCRIPTLET_RE.findall(txt))} |")
    out.append("")

    if sql:
        out.append("## SQL 对象（CREATE TABLE）")
        for p in sql:
            rel = os.path.relpath(p, a.src)
            tabs = TABLE_RE.findall(lines_of(p))
            out.append(f"- `{rel}`: {', '.join(sorted(set(tabs))) if tabs else '无建表语句'}")
        out.append("")

    # 类级依赖边（仅本工程内部）
    edges = []
    for rel, imps in imports_by_file.items():
        for im in imps:
            short = im.split(".")[-1]
            if short in local_classes and local_classes[short] != rel:
                edges.append((os.path.basename(rel)[:-5], short))
    out.append("## 内部依赖边（import 解析，A -> B）")
    if edges:
        for a_, b_ in sorted(set(edges)):
            out.append(f"- {a_} -> {b_}")
    else:
        out.append("- （无内部 import 依赖：说明层间通过全限定名或反射调用，需人工确认）")
    out.append("")

    txt = "\n".join(out)
    if len(txt.encode()) > a.max_bytes:
        txt = txt[: a.max_bytes // 2] + "\n...（L0 图层已截断）\n"
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"L0 written: {a.out} ({len(txt.encode())} bytes)")


if __name__ == "__main__":
    main()
