"""阶段 3：功能模块 —— 回答"这个系统到底有哪些功能、每个功能由哪些代码承载"。

切分依据不是文件名猜的，而是**真实调用边**：页面里的表单/AJAX 目标
经路由解析落到哪个 Servlet，就归到哪个模块；再用 Dao 引用反查实体与表。

输出 03-modules.md。
"""

from __future__ import annotations

import os

import lib_md as md
from lib_model import build_routes, derive_modules


def run(ctx) -> str:
    proj = ctx["project"]
    out = []

    routes = build_routes(proj)
    modules, unassigned, owner_of = derive_modules(proj, routes)
    ctx["derived"]["routes"] = routes
    ctx["derived"]["modules"] = modules
    ctx["derived"]["unassigned_pages"] = unassigned

    jsp_by_file = {j["file"]: j for j in proj["jsp"]}
    java_by_type = {u["primary_type"]: u for u in proj["java"]}

    out.append(md.h(1, "03 · 功能模块分析"))
    out.append(f"> 共识别出 **{len(modules)} 个业务模块**，"
               f"另有 {len(unassigned)} 个页面未挂接到任何业务 Servlet。\n")

    out.append(md.h(2, "模块总览"))
    out.append(md.table(
        ["#", "后端领域", "前端页面前缀", "Servlet", "页面数", "能力"],
        [[i + 1, f"**{m['domain']}**",
          f"`{m['page_prefix']}*`" if m["page_prefix"] else "-",
          "、".join(s.split(".")[-1] for s in m["servlet"]) or "-",
          len(m["pages"]),
          "、".join(m["competences"]) or "-"]
         for i, m in enumerate(modules)]))

    out.append("> 「前端页面前缀」是从页面名（`userAdd` / `userList` …）反推出的 UI 术语。"
               "老项目常见后端 `Suppliers` 与前端 `provider*` 不一致，这里显式标出映射。\n")

    # ---------------- 逐模块
    for i, m in enumerate(modules, 1):
        out.append(md.h(2, f"{i}. {m['domain']}"
                           + (f"（页面群：`{m['page_prefix']}*`）" if m["page_prefix"] else "")))

        slice_rows = [
            ["页面层", "、".join(f"`{p}`" for p in m["pages"]) or "-"],
            ["控制层", "、".join(f"`{s}`" for s in m["servlet"]) or "-"],
            ["业务层", "、".join(f"`{s}`" for s in m["biz"]) or "-"],
            ["持久层", "、".join(f"`{s}`" for s in m["dao"]) or "-"],
            ["实体/视图对象", "、".join(f"`{s}`" for s in m["entity"]) or "-"],
            ["数据表", "、".join(f"`{t}`" for t in m["tables"]) or "-"],
        ]
        out.append(md.table(["层", "构件"], slice_rows))

        if m["actions"]:
            out.append(md.h(3, "支持的动作"))
            out.append(md.bullets([f"`{a}`" for a in m["actions"]]))

        if m["pages"]:
            out.append(md.h(3, "页面清单"))
            rows = []
            for p in sorted(m["pages"]):
                j = jsp_by_file.get(p, {})
                acts = "、".join(f"`{a}`" for a in j.get("form_actions", [])) or "-"
                rows.append([f"`{p}`", j.get("lines", "-"),
                             j.get("scriptlet_blocks", "-"), acts])
            out.append(md.table(["页面", "行数", "脚本片段", "表单提交目标"], rows))

        if m["tables"]:
            out.append(md.h(3, "涉及的数据对象"))
            out.append(md.bullets([f"`{t}`" for t in m["tables"]]))

        out.append("")

    # ---------------- 公共构件
    out.append(md.h(2, "公共 / 基础设施构件"))
    assigned = set()
    for m in modules:
        for key in ("servlet", "biz", "dao", "entity"):
            assigned |= {s.split(".")[-1] for s in m[key]}
    infra = [u for u in proj["java"] if u["primary_type"] not in assigned]
    out.append(md.table(["类", "层", "行数", "说明"],
                        [[f"`{u['primary_type']}`", u["layer"], u["lines"],
                          _describe(u)] for u in sorted(infra, key=lambda x: x["layer"])]))

    # ---------------- 未归属页面
    if unassigned:
        out.append(md.h(2, "未归属到业务模块的页面"))
        out.append("这些页面不承载任何业务模块的 CRUD，通常是登录/改密/欢迎页等"
                   "由前端控制器直接处理的公共页，或已废弃页面：\n")
        out.append(md.table(
            ["页面", "行数", "表单目标", "归属说明"],
            [[f"`{p}`", jsp_by_file.get(p, {}).get("lines", "-"),
              "、".join(f"`{a}`" for a in jsp_by_file.get(p, {}).get("form_actions", [])) or "-",
              _why_unassigned(jsp_by_file.get(p, {}), owner_of.get(p))]
             for p in sorted(unassigned)]))

    # ---------------- 请求流示意
    out.append(md.h(2, "典型请求链路"))
    chain_rows = []
    for m in modules:
        for p in sorted(m["pages"])[:1]:
            info = owner_of.get(p)
            if not info:
                continue
            _, kind, target, trace = info
            servlet = [s.split(".")[-1] for s in m["servlet"]]
            dao = [s.split(".")[-1] for s in m["dao"]]
            if servlet and dao:
                chain_rows.append([
                    f"`{p}`",
                    " → ".join([f"`{target}`"] + [f"`{x}`" for x in servlet]
                               + [f"`{x}`" for x in dao]),
                    " → ".join(trace),
                ])
    out.append(md.table(["入口页面", "调用链", "解析过程"], chain_rows)
                if chain_rows else "（未能构造）\n")

    text = "\n".join(out)
    path = os.path.join(ctx["out"], "03-modules.md")
    md.write_atomic(path, text)
    ctx["docs"]["modules"] = path
    return path


def _describe(u) -> str:
    t = u["types"][0] if u["types"] else {}
    bits = []
    if t.get("extends"):
        bits.append(f"继承 `{t['extends']}`")
    if t.get("implements"):
        bits.append(f"实现 `{t['implements']}`")
    if u["sqls"]:
        bits.append(f"{len(u['sqls'])} 条 SQL")
    if u["_body"] and "getPoolConnection" in u["_body"]:
        bits.append("提供连接获取")
    return "；".join(bits) or "-"


def _why_unassigned(j, info) -> str:
    """解释为什么不落在业务模块里——要么由前端控制器直管，要么没有任何调用边。"""
    if info:
        owner, kind, target, _trace = info
        tgt = target if str(target).startswith("`") else f"`{target}`"
        return (f"由基础设施 {owner.split('.')[-1]} 处理（{kind} {tgt}），"
                "不属于任何业务模块")
    if not j:
        return "-"
    if j.get("form_actions"):
        return ("表单提交到 " + "、".join(f"`{a}`" for a in j["form_actions"])
                + "，未解析到业务 Servlet")
    return "未见任何指向它的调用边，可能是未被引用或已被替代的历史页面"
