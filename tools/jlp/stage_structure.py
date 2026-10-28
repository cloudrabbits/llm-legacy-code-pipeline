"""阶段 1：项目结构 —— 回答"这个工程长什么样、用什么技术栈、怎么构建"。

输出 01-structure.md：目录骨架、文件画像、最大的源文件、技术栈指纹、
构建与部署形态。所有数字来自 lib_scan，不含任何推测。
"""

from __future__ import annotations

import os
from collections import defaultdict

import lib_md as md
from lib_scan import EXT_LABEL


def _tree(files, max_depth: int = 4):
    """(dir -> {count, lines}) 递归聚合。超过 max_depth 的目录**向上并入**该深度祖先，
    这样既不丢数量，也不把叶子文件重复计入某一层（早期版本曾把文件名也当成一层，
    导致 js 目录的文件数与行数翻倍）。
    """
    agg = defaultdict(lambda: {"count": 0, "lines": 0})
    for f in files:
        parts = f["file"].split("/")
        dirs = parts[:-1] or ["."]
        depth = min(len(dirs), max_depth)
        for i in range(1, depth + 1):
            key = "/".join(dirs[:i])
            agg[key]["count"] += 1
            agg[key]["lines"] += f["lines"]
    return agg


def render_tree(files, max_depth=3) -> str:
    agg = _tree(files, max_depth)
    nodes = sorted(agg.items(), key=lambda kv: kv[0])

    lines = []

    def depth_of(k):
        return k.count("/") + (0 if k == "." else 1)

    for key, stat in nodes:
        if key == ".":
            continue
        d = depth_of(key)
        name = key.split("/")[-1]
        pad = "  " * (d - 1)
        lines.append(f"{pad}- /{name} （该目录累计 {stat['count']} 个文件 · "
                     f"{stat['lines']:,} 行）")
    return "\n".join(lines)


def run(ctx) -> str:
    proj = ctx["project"]
    files = proj["files"]
    out = []

    total_files = len(files) + len(proj["binaries"])
    code_lines = sum(f["lines"] for f in files if f["ext"] in {".java", ".jsp"})
    all_lines = sum(f["lines"] for f in files)

    out.append(md.h(1, "01 · 项目结构分析"))
    out.append("> 全部数字由脚本统计得出，非估算。\n")

    out.append(md.h(2, "一句话画像"))
    tech = ctx.get("tech", {})
    out.append(f"**{proj['name']}** 是一个 "
               f"{tech.get('arch', '未知架构')} 的 Web 应用："
               f"{len(proj['java'])} 个 Java 类、{len(proj['jsp'])} 个 JSP 页面、"
               f"共 {code_lines:,} 行 Java/JSP 代码"
               f"（全量文本 {all_lines:,} 行 / {total_files} 个文件）。\n")

    out.append(md.h(2, "规模总览"))
    out.append(md.table(
        ["维度", "数量"],
        [["Java 源文件", len(proj["java"])],
         ["JSP 页面", len(proj["jsp"])],
         ["SQL 脚本", len(proj["sql"])],
         ["XML / properties 配置", len(proj["xml_props"])],
         ["JAR 依赖包", len(proj["jars"])],
         ["Java + JSP 代码行数", f"{code_lines:,}"],
         ["文本总行数", f"{all_lines:,}"],
         ["仓库文件总数", total_files]]))

    out.append(md.h(2, "目录骨架（≤4 层）"))
    out.append("每个节点显示的是**该目录及其子目录**的累计文件数与行数；"
               "更深的目录已并入第 4 层祖先。\n")
    out.append(md.code(render_tree(files, 4), "text"))

    out.append(md.h(2, "文件类型画像"))
    ext_stat = defaultdict(lambda: {"n": 0, "lines": 0, "bytes": 0})
    for f in files:
        s = ext_stat[f["ext"]]
        s["n"] += 1
        s["lines"] += f["lines"]
        s["bytes"] += f["size"]
    for b in proj["binaries"]:
        s = ext_stat[b["ext"]]
        s["n"] += 1
        s["bytes"] += b["size"]
    rows = [[e, EXT_LABEL.get(e, e.lstrip(".") or "(无扩展名)"), s["n"],
             f"{s['lines']:,}" if s["lines"] else "-", f"{s['bytes']/1024:.0f} KB"]
            for e, s in sorted(ext_stat.items(), key=lambda kv: -kv[1]["n"])]
    out.append(md.table(["扩展名", "类别", "文件数", "行数", "体积"], rows))

    out.append(md.h(2, "Java 包分布"))
    pkg = defaultdict(lambda: {"files": 0, "lines": 0, "methods": 0})
    for u in proj["java"]:
        p = pkg[u["package"] or "(默认包)"]
        p["files"] += 1
        p["lines"] += u["lines"]
        p["methods"] += u["method_count"]
    out.append(md.table(
        ["包", "文件数", "行数", "方法数"],
        [[k, v["files"], v["lines"], v["methods"]]
         for k, v in sorted(pkg.items(), key=lambda kv: -kv[1]["lines"])]))

    out.append(md.h(2, "体积最大的源文件（前 15）"))
    top = sorted(files, key=lambda f: -f["lines"])[:15]
    out.append(md.table(["文件", "行数", "类别"],
                        [[f"`{f['file']}`", f["lines"], f["label"]] for f in top]))

    out.append(md.h(2, "技术栈指纹"))
    out.append(md.table(["维度", "判定", "证据"], tech.get("rows", [])))

    out.append(md.h(2, "构建与部署形态"))
    out.append(md.table(["维度", "结论"], tech.get("build_rows", [])))

    if tech.get("notes"):
        out.append(md.h(2, "结构上的注意事项"))
        out.append(md.bullets(tech["notes"]))

    text = "\n".join(out)
    path = os.path.join(ctx["out"], "01-structure.md")
    md.write_atomic(path, text)
    ctx["docs"]["structure"] = path
    return path
