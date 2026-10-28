"""阶段 0：环境预检 —— 在动 LLM 之前先确认"这条路走得通"。

Windows 上最容易翻车的三件事：
  1. 控制台/文件编码（GBK 老文件被当成 UTF-8 读就是满屏乱码）；
  2. 路径不存在或权限不足（OneDrive / 中文路径 / 长路径）；
  3. 目标目录里混着体积巨大的资源/备份文件。
预检报告把这些问题一次性暴露出来，输出 00-preflight.md。
"""

from __future__ import annotations

import os
import platform
import sys

import lib_md as md


def run(ctx) -> str:
    proj = ctx["project"]
    src = ctx["src"]
    out = []

    checks = []

    # --- 运行环境
    py = sys.version.split()[0]
    checks.append(("Python", py, "OK" if sys.version_info >= (3, 8) else "需 >=3.8"))
    checks.append(("操作系统", f"{platform.system()} {platform.release()}", "OK"))
    checks.append(("本机 CPU 架构", platform.machine(), "OK"))
    checks.append(("控制台输出", "已强制 UTF-8"
                   if getattr(sys.stdout, "encoding", "").lower().startswith("utf")
                   else "非 UTF-8（已按 replace 降级，不影响产物）", "OK"))

    # --- 目标路径
    exists = os.path.isdir(src)
    checks.append(("目标路径", src, "OK" if exists else "不存在"))
    if exists:
        readable = os.access(src, os.R_OK)
        checks.append(("目录可读", "是" if readable else "否", "OK" if readable else "阻塞"))
        writable = os.access(src, os.W_OK)
        checks.append(("目录可写", "是" if writable else "否",
                       "提示：只读挂载也可以，本工具对目标只读"))

    # --- 规模
    n_text = len(proj["files"])
    n_bin = len(proj["binaries"])
    total_lines = sum(f["lines"] for f in proj["files"])
    checks.append(("文本文件数", n_text, "OK" if n_text else "未发现可解析文件"))
    checks.append(("二进制/其他文件数", n_bin, "OK"))
    checks.append(("文本总行数", f"{total_lines:,}", "OK"))

    # --- 编码普查
    enc = proj["encoding_stats"]
    main_enc = max(enc.items(), key=lambda kv: kv[1])[0] if enc else "-"
    mixed = len(enc) > 1
    checks.append(("主编码", main_enc, "OK"))
    checks.append(("是否混编码", "是（已逐个文件降级解码）" if mixed else "否",
                   "提示" if mixed else "OK"))

    # --- 巨大文件
    big = [b for b in proj["binaries"] if b["size"] > 5 * 1024 * 1024]
    if big:
        checks.append(("超过 5MB 的资源", f"{len(big)} 个", "提示：已跳过内容解析"))

    out.append(md.h(1, "00 · 环境预检报告"))
    out.append("> 本阶段不调用任何模型，纯本地静态检查。\n")
    out.append(md.h(2, "检查项"))
    out.append(md.table(["检查项", "结果", "判定"], checks))

    if enc:
        out.append(md.h(2, "编码普查"))
        out.append("按命中次数排列。**混编码是老项目常态**，所有读取都走"
                   "`utf-8-sig → utf-8 → gb18030 → big5 → latin-1` 降级链，"
                   "不会因个别文件乱码而中断。\n")
        out.append(md.table(["编码", "文件数"],
                            [[k, v] for k, v in enc.items()]))

    gbkish = [f["file"] for f in proj["files"]
              if f["encoding"].lower().startswith(("gb", "big5", "latin"))]
    if gbkish:
        out.append(md.h(2, "非 UTF-8 文件清单"))
        out.append("这些文件在迁移到 UTF-8 工具链（Maven/Gradle/新版 IDE）时需要转码：\n")
        out.append(md.bullets([f"`{p}`" for p in sorted(gbkish)]))

    out.append(md.h(2, "分析入口判定"))
    web = proj.get("webxml")
    if web:
        out.append(f"- 部署描述文件：`{web.get('file', '-')}`，"
                   f"声明版本 `{web.get('declared_version')}`，"
                   f"Schema 版本 `{web.get('schema_version')}`")
    if proj["java"]:
        pkgs = sorted({u["package"] for u in proj["java"] if u["package"]})
        out.append(f"- Java 源文件 {len(proj['java'])} 个，根包："
                   + ", ".join(f"`{p}`" for p in pkgs[:5]))
    if proj["jsp"]:
        out.append(f"- JSP 页面 {len(proj['jsp'])} 个")
    out.append("")

    blocking = [c for c in checks if c[2] in ("阻塞", "需 >=3.8")]
    out.append(md.h(2, "结论"))
    if blocking:
        out.append("存在阻塞项，请先处理后重跑：\n")
        out.append(md.table(["检查项", "原因"], [[c[0], c[1]] for c in blocking]))
    else:
        out.append(f"**通过**：环境满足条件，目标可读，共发现 {n_text} 个可解析文本文件"
                   f"（{total_lines:,} 行）。继续执行后续阶段。\n")

    text = "\n".join(out)
    path = os.path.join(ctx["out"], "00-preflight.md")
    md.write_atomic(path, text)
    ctx["docs"]["preflight"] = path
    return path
