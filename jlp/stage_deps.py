"""阶段 2：依赖关系 —— 回答"谁依赖谁、请求怎么流、缺什么包"。

输出 02-dependencies.md：分层画像、类清单、内部依赖图、请求路由表、
页面↔后端调用矩阵、第三方依赖与缺失检测。
"""

from __future__ import annotations

import os
from collections import defaultdict

import lib_md as md
import lib_scan
from lib_model import build_routes, resolve_owner


def run(ctx) -> str:
    proj = ctx["project"]
    java = proj["java"]
    jsp = proj["jsp"]
    out = []

    by_name = {u["primary_type"]: u for u in java}
    routes = build_routes(proj)
    ctx["derived"]["routes"] = routes

    internal_names = {t["type"] for u in java for t in u["types"]}
    edges = lib_scan.internal_edges(java)
    ext_groups = lib_scan.external_import_groups(java, internal_names)
    third_party, dialects = lib_scan.detect_missing_deps(proj, ext_groups)

    out.append(md.h(1, "02 · 依赖关系分析"))
    out.append("> 依赖边由 import / extends / implements / 同包引用解析得出；"
               "URL 链路由 web.xml 与 Servlet 分支还原。\n")

    # ---------------- 分层
    out.append(md.h(2, "分层画像"))
    layer_stat = defaultdict(lambda: {"n": 0, "lines": 0, "methods": 0})
    for u in java:
        s = layer_stat[u["layer"]]
        s["n"] += 1
        s["lines"] += u["lines"]
        s["methods"] += u["method_count"]
    out.append(md.table(["层", "类数", "行数", "方法数"],
                        [[k, v["n"], v["lines"], v["methods"]]
                         for k, v in sorted(layer_stat.items(),
                                            key=lambda kv: -kv[1]["lines"])]))

    # ---------------- 类清单
    out.append(md.h(2, "Java 类清单"))
    out.append("按行数降序。`继承/实现` 一列能直接看出接口 - 实现配对与基础类复用。\n")
    rows = []
    for u in sorted(java, key=lambda x: -x["lines"]):
        t = u["types"][0] if u["types"] else {}
        inh = " / ".join(x for x in [t.get("extends", ""), t.get("implements", "")] if x)
        rows.append([u["primary_type"], u["layer"], u["package"],
                     u["lines"], u["method_count"], inh or "-"])
    out.append(md.table(["类", "层", "包", "行数", "方法数", "继承 / 实现"], rows))

    # ---------------- 内部依赖
    out.append(md.h(2, "内部依赖关系"))
    out.append(md.h(3, "类级依赖边（A → B）"))
    out.append(md.bullets([f"`{a}` → `{b}`" for a, b in edges]))

    out.append(md.h(3, "分层调用矩阵"))
    out.append("行＝调用方，列＝被依赖方，数字＝该方向的依赖边数量。\n")
    layer_of = {u["primary_type"]: u["layer"] for u in java}
    matrix = defaultdict(int)
    for a, b in edges:
        matrix[(layer_of.get(a, "未分类"), layer_of.get(b, "未分类"))] += 1
    layers = sorted({k[0] for k in matrix} | {k[1] for k in matrix})
    out.append(md.table(["调用方 \\ 被依赖方"] + layers,
                        [[src] + [matrix.get((src, dst), 0) or "-" for dst in layers]
                         for src in layers]))

    violations = []
    rules = [("控制层", "持久层", "控制层直接依赖持久层"),
             ("业务层", "控制层", "业务层反向依赖控制层"),
             ("持久层", "控制层", "持久层反向依赖控制层"),
             ("持久层", "业务层", "持久层反向依赖业务层"),
             ("实体/POJO", "控制层", "实体反向依赖控制层"),
             ("实体/POJO", "业务层", "实体反向依赖业务层"),
             ("实体/POJO", "持久层", "实体反向依赖持久层")]
    for src, dst, why in rules:
        hit = [f"`{a}` → `{b}`" for a, b in edges
               if layer_of.get(a) == src and layer_of.get(b) == dst]
        if hit:
            violations.append(f"{why}：" + "、".join(hit))
    out.append(md.h(3, "分层违规检查"))
    out.append(md.bullets(violations) if violations else
               "未发现跨层反向依赖，调用方向自上而下，符合经典分层。\n")

    # ---------------- 请求路由
    out.append(md.h(2, "请求路由（web.xml）"))
    wxml = proj.get("webxml") or {}
    if wxml.get("servlet_mappings"):
        clsfile = {u["primary_type"]: u["file"] for u in java}
        rows = []
        for m in wxml["servlet_mappings"]:
            cls = next((s["class"] for s in wxml["servlets"] if s["name"] == m["name"]), "")
            short = cls.split(".")[-1] if cls else "-"
            rows.append([f"`{m['url_pattern']}`", m["name"], cls or "-",
                         f"`{clsfile.get(short, '（未找到源文件）')}`"])
        out.append(md.table(["URL 模式", "Servlet 名", "Servlet 类", "源文件"], rows))
    else:
        out.append("（未解析到 servlet-mapping）\n")

    if wxml.get("filter_mappings"):
        out.append(md.h(3, "过滤器链"))
        fcls = {f["name"]: f["class"] for f in wxml["filters"]}
        out.append(md.table(["URL 模式", "过滤器类"],
                            [[f"`{m['url_pattern']}`", fcls.get(m["name"], "-")]
                             for m in wxml["filter_mappings"]]))
    if wxml.get("welcome_files"):
        out.append(md.h(3, "欢迎文件"))
        out.append(md.bullets([f"`{w}`" for w in wxml["welcome_files"]]))

    # ---------------- 前端控制器分派
    out.append(md.h(2, "前端控制器 / Servlet 分派表"))
    for cls, branches in routes["controllers"].items():
        short = cls.split(".")[-1]
        tag = "（前端控制器）" if cls in routes["front_controllers"] else ""
        out.append(md.h(3, f"{short}{tag}"))
        rows = []
        for b in branches:
            dest = "、".join(f"`{x}`" for x in (b["forwards"] + b["redirects"])) or "-"
            rows.append([f"`{b['action']}`", dest,
                         "、".join(f"`{p}`" for p in b["params"]) or "-",
                         "、".join(f"`{c}`" for c in b["biz_calls"]) or "-"])
        out.append(md.table(["action", "跳转目标", "读取的参数", "调用的业务方法"], rows))

    # ---------------- 页面 -> 后端
    out.append(md.h(2, "页面 → 后端 调用矩阵"))
    out.append("只统计**主动发起**的调用（表单 action、AJAX URL），导航栏链接不计入，"
               "否则每个页面都会因为导航栏而同时引用所有模块。\n")
    rows = []
    for j in sorted(jsp, key=lambda x: x["file"]):
        targets = []
        for a in j["form_actions"]:
            targets.append(("表单提交", a))
        for a in j["ajax_urls"]:
            targets.append(("异步请求", a))
        if not targets:
            rows.append([f"`{j['file']}`", "-", "-", "-"])
            continue
        for kind, t in targets:
            owner, trace = resolve_owner(routes, t)
            rows.append([f"`{j['file']}`", kind, f"`{t}`",
                         owner.split(".")[-1] if owner else "解析失败"])
    out.append(md.table(["页面", "方式", "目标", "处理者"], rows))

    out.append(md.h(3, "页面 → 静态/内部包含"))
    inc_rows = [[f"`{j['file']}`",
                 "、".join(f"`{x}`" for x in j["includes_directive"]) or "-",
                 "、".join(f"`{x}`" for x in j["includes_runtime"]) or "-",
                 str(j["scriptlet_blocks"]), str(len(j["el_expressions"]))]
                for j in sorted(jsp, key=lambda x: x["file"])]
    out.append(md.table(["页面", "静态包含", "运行时包含", "脚本片段数", "EL 表达式数"], inc_rows))

    # ---------------- 后端 -> 页面
    out.append(md.h(2, "后端 → 页面 跳转"))
    rows = []
    for u in java:
        if u["forwards"] or u["redirects"]:
            rows.append([f"`{u['primary_type']}`",
                         "、".join(f"`{x}`" for x in u["forwards"]) or "-",
                         "、".join(f"`{x}`" for x in u["redirects"]) or "-"])
    out.append(md.table(["类", "转发 (forward)", "重定向 (redirect)"], rows))

    # ---------------- 第三方依赖
    out.append(md.h(2, "第三方依赖"))
    out.append(md.h(3, "war 内已打包的 JAR"))
    out.append(md.table(["文件", "体积"],
                        [[f"`{j['file']}`", f"{j['size']/1024:.0f} KB"] for j in proj["jars"]])
                if proj["jars"] else "（无）\n")

    out.append(md.h(3, "源码实际使用的第三方命名空间"))
    lib_rows = []
    for tp in third_party:
        status = "已在 war 中" if tp["in_war"] else "**war 中缺失**"
        lack = ("、".join(tp["missing_companions"])) if tp["missing_companions"] else "-"
        lib_rows.append([f"`{tp['namespace']}`", tp["lib"], tp["usage"], status, lack])
    out.append(md.table(["命名空间", "依赖库", "引用次数", "打包状态", "缺少的配套 jar"], lib_rows)
                if lib_rows else "（未见第三方依赖，纯 JDK/Servlet API）\n")

    plat = {k: v for k, v in sorted(ext_groups.items()) if lib_scan.is_platform_ns(k)}
    if plat:
        out.append(md.h(3, "平台 / 容器提供的命名空间（无需打包）"))
        out.append(md.table(["命名空间", "引用次数"], [[f"`{k}`", v] for k, v in plat.items()]))

    # ---------------- 平台 / 容器 / JDK 提供的依赖
    # 这些命名空间在上面的第三方表里被过滤掉了，但升级容器 / JDK 时恰恰是它们最先炸。
    platform_deps = proj.get("platform_deps")
    if platform_deps is None:
        import lib_registry
        platform_deps = lib_registry.detect_platform_deps(proj)
    if platform_deps:
        provider_label = {"container": "容器", "jdk": "JDK", "app": "war", "unknown": "待确认"}
        out.append(md.h(3, "平台 / 容器 / JDK 提供的依赖（不打进 war，升级时最易漏）"))
        out.append(md.table(
            ["组件", "由谁提供", "状态", "版本线索", "引用次数", "迁移目标", "阶段"],
            [[d["name"], provider_label.get(d["provided_by"], d["provided_by"]), d["status"],
              d["version_hint"] or "-", d["usage"], d["migration_target"] or "-",
              d["phase"] or "-"] for d in platform_deps]))
        for d in platform_deps:
            out.append(f"\n- **{d['name']}**：" + "；".join(d["evidence"][:5]))
            if d["notes"]:
                out.append(f"  - 提示：{d['notes']}")
        out.append("")

    # ---------------- 组件改造台账（迁移登记）
    ledger = proj.get("components")
    if ledger is None:
        import lib_registry
        ledger = lib_registry.detect_components(proj)
    out.append(md.h(2, "组件改造台账（迁移登记）"))
    out.append("> 由 `config/legacy/components.json` 与内置基线共同判定；"
               "闭源组件请在该文件里补充包名前缀 / jar 名 / 配置文件 / 基类签名。\n")
    if ledger:
        out.append(md.table(
            ["组件", "类别", "状态", "引用次数", "war 内 jar", "缺失配套", "迁移目标",
             "破坏性", "阶段"],
            [[c["name"], c["category"], c["status"], c["usage"],
              "、".join(c["jars"]) or "**未打包**",
              "、".join(c["missing_companions"]) or "-",
              c["migration_target"] or "-", c["breaking"] or "-", c["phase"] or "-"]
             for c in ledger]))
        for c in ledger:
            if c["notes"]:
                out.append(f"- **{c['name']}**：{c['notes']}")
    else:
        out.append("（未检出需登记的第三方/闭源组件）\n")

    # ---------------- 数据依赖
    out.append(md.h(2, "数据库依赖"))
    if dialects:
        out.append(md.table(
            ["数据库", "判定依据", "驱动 jar 关键字", "驱动是否在 war 内"],
            [[d["db"], d["evidence"], "、".join(d["driver_jars"]),
              "是" if d["driver_in_war"] else "否（由容器 lib 提供）"] for d in dialects]))
    if proj["jndi"]:
        out.append("\n数据源通过 JNDI 获取，需在运行容器的配置中提供资源：\n")
        out.append(md.bullets([f"`{u}`" for u in proj["jndi"]]))
    if proj["sql"]:
        out.append(md.h(3, "SQL 脚本中的数据库对象"))
        rows = []
        for s in proj["sql"]:
            rows.append([f"`{s['file']}`", s["encoding"],
                         "、".join(s["tables"]) or "-",
                         "、".join(s["views"]) or "-",
                         "、".join(s["sequences"]) or "-"])
        out.append(md.table(["脚本", "编码", "表", "视图", "序列"], rows))

    ctx["derived"]["deps"] = {
        "edges": edges, "third_party": third_party, "dialects": dialects,
        "ext_groups": ext_groups, "layer_of": layer_of,
    }

    text = "\n".join(out)
    path = os.path.join(ctx["out"], "02-dependencies.md")
    md.write_atomic(path, text)
    ctx["docs"]["dependencies"] = path
    return path
