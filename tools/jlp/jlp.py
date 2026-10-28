#!/usr/bin/env python3
"""jlp —— JSP 遗留项目分析器（Windows 原生可跑）。

用法：
    python jlp.py --src D:\\IdeaProjects\\supermarketmanager
    python jlp.py --src <目录> --out <输出目录> --stages structure,deps
    python jlp.py --self-test

设计要点：
    * 只读：不对 --src 做任何写操作；
    * 零依赖：只用 Python 标准库；
    * 事实由脚本产出：所有数字/清单/依赖边都是算出来的，模型最多改写叙述；
    * Windows 友好：控制台强制 UTF-8，文件按编码链降级解码，路径统一 `/`。
"""

from __future__ import annotations

import argparse
import os
import sys

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _bootstrap_windows_console():
    """Windows 控制台默认可能是 GBK，先统一到 UTF-8，避免中文报表打印成问号。"""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


ALL_STAGES = ["preflight", "structure", "deps", "modules", "report"]


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        prog="jlp",
        description="JSP 遗留项目分析器：产出人类可读的需求分析文档")
    ap.add_argument("--src", help="被分析的 JSP 项目根目录（只读）")
    ap.add_argument("--out", help="产物输出目录，默认 <仓库>/out/<项目目录名>")
    ap.add_argument("--stages", help="逗号分隔的阶段：" + ",".join(ALL_STAGES) + "（默认全部）")
    ap.add_argument("--exclude-dir", action="append", default=[],
                    help="额外排除的目录名，可重复")
    ap.add_argument("--max-file-bytes", type=int, default=4 * 1024 * 1024,
                    help="超过该大小的文本跳过内容解析（默认 4MB）")
    ap.add_argument("--llm-url", help="开启 LLM 叙述增强，如 http://127.0.0.1:11434/api/generate")
    ap.add_argument("--llm-model", help="LLM 模型名，配合 --llm-url")
    ap.add_argument("--facts-only", action="store_true", help="只落机读事实库，不生成文档")
    ap.add_argument("--quiet", action="store_true", help="减少过程输出")
    ap.add_argument("--self-test", action="store_true",
                    help="用内置合成语料跑一遍全链路自检（不联网、不需要 LLM）")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    _bootstrap_windows_console()
    args = parse_args(argv)

    if args.self_test:
        import selftest
        return selftest.run()

    if not args.src:
        print("错误：缺少 --src（被分析的 JSP 项目根目录）", file=sys.stderr)
        print("示例：python jlp.py --src D:\\IdeaProjects\\supermarketmanager", file=sys.stderr)
        return 2

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        print(f"错误：目标不是目录或不存在：{src}", file=sys.stderr)
        return 2

    import lib_scan
    import lib_tech
    import stage_preflight
    import stage_structure
    import stage_deps
    import stage_modules
    import stage_report

    # tools/jlp/jlp.py -> tools/jlp -> tools -> <repo root>
    repo_root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    out = args.out or os.path.join(repo_root, "out", os.path.basename(src.rstrip("\\/")) or "project")
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)

    def log(msg):
        if not args.quiet:
            print(msg, flush=True)

    log(f"[jlp] 扫描 {src} ...")
    project = lib_scan.scan(src, max_file_bytes=args.max_file_bytes,
                            exclude_dirs=tuple(args.exclude_dir))
    log(f"[jlp] 扫描完成：{len(project['java'])} 个 Java / {len(project['jsp'])} 个 JSP / "
        f"{len(project['files'])} 个文本文件")

    ctx = {
        "src": src,
        "out": out,
        "project": project,
        "derived": {},
        "docs": {},
        "llm_state": "未启用（纯静态事实）",
        "repro": f"python \"{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jlp.py')}\" "
                 f"--src \"{src}\"",
    }

    facts_path = lib_scan.dump_facts(project, os.path.join(out, "facts.json"))
    log(f"[jlp] 事实库 -> {facts_path}")
    if args.facts_only:
        return 0

    stages = [s.strip() for s in args.stages.split(",")] if args.stages else ALL_STAGES
    unknown = [s for s in stages if s not in ALL_STAGES]
    if unknown:
        print(f"错误：未知阶段 {unknown}，可选：{ALL_STAGES}", file=sys.stderr)
        return 2

    # 技术栈指纹是多个阶段的公共输入，且代价极低，统一先算好
    ctx["tech"] = lib_tech.build(project)

    produced = []
    if "preflight" in stages:
        produced.append(stage_preflight.run(ctx))
    if "structure" in stages:
        produced.append(stage_structure.run(ctx))
    if "deps" in stages:
        produced.append(stage_deps.run(ctx))
    if "modules" in stages:
        produced.append(stage_modules.run(ctx))

    if args.llm_url and args.llm_model and "report" in stages:
        import stage_llm
        log(f"[jlp] LLM 增强 {args.llm_model} @ {args.llm_url} ...")
        p = stage_llm.run(ctx, args.llm_url, args.llm_model)
        if p:
            produced.append(p)
    elif args.llm_url or args.llm_model:
        print("提示：--llm-url 与 --llm-model 需同时提供，本次忽略 LLM 增强。",
              file=sys.stderr)

    if "report" in stages:
        # 报告依赖前面阶段的派生结果，缺失则即时补齐
        if "routes" not in ctx["derived"]:
            produced.append(stage_deps.run(ctx))
        if "modules" not in ctx["derived"]:
            produced.append(stage_modules.run(ctx))
        produced += stage_report.run(ctx)

    log("")
    log(f"[jlp] 产物目录：{out}")
    for p in produced:
        log(f"  - {os.path.basename(p)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
