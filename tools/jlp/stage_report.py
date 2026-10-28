"""阶段 4：汇总出品 —— 产出面向"人"的需求分析文档与一页摘要。

  * 10-requirement-analysis.md  完整需求分析报告（给接手的人通读）
  * 99-summary.md               一页纸速览（给开会/汇报用）

文档中所有数字、清单、依赖边均来自前几个阶段算出的事实；
本阶段只做组织与措辞，不新增未被证实的信息。
"""

from __future__ import annotations

import os

import lib_md as md
from lib_model import derive_risks
from lib_scan import strip_internal

TOOL_VERSION = "jlp 1.0"


def run(ctx) -> list:
    proj = ctx["project"]
    tech = ctx["tech"]
    routes = ctx["derived"]["routes"]
    modules = ctx["derived"]["modules"]
    unassigned = ctx["derived"]["unassigned_pages"]
    deps = ctx["derived"]["deps"]

    risks = derive_risks(proj, modules, unassigned)
    ctx["derived"]["risks"] = risks

    out = []
    out.append(md.h(1, "需求分析报告"))
    out.append(md.h(2, "文档信息"))
    out.append(md.table(
        ["项", "值"],
        [["被分析项目", proj["name"]],
         ["项目根路径", f"`{proj['root']}`"],
         ["生成时间", md.now()],
         ["生成工具", TOOL_VERSION + "（静态分析，未编译/未执行/未联网）"],
         ["事实来源", "01-structure.md / 02-dependencies.md / 03-modules.md"],
         ["LLM 参与", ctx.get("llm_state", "未启用（纯静态事实）")]]))

    out.append(md.h(2, "阅读说明"))
    out.append(
        "本报告由工具静态扫描源码得出，用于**快速建立对一个陌生老项目的认知**：\n\n"
        "1. 所有数量、清单、依赖边都是脚本数出来的，可直接复核；\n"
        "2. 涉及「意图」的判断（如某个类是废弃代码）均标注为提示，请人工确认；\n"
        "3. 分析过程对被分析目录**只读**，不会改动或生成任何源文件。\n")

    # ---------- 1. 概览
    code_lines = sum(f["lines"] for f in proj["files"] if f["ext"] in (".java", ".jsp"))
    out.append(md.h(2, "1. 项目概览"))
    out.append(f"**{proj['name']}** 是一个基于 {tech['arch']} 的 Java Web 应用，"
               f"共 {len(proj['java'])} 个 Java 类、{len(proj['jsp'])} 个 JSP 页面，"
               f"Java/JSP 代码约 {code_lines:,} 行。\n")
    if routes["front_controllers"]:
        fc = "、".join(c.split(".")[-1] for c in routes["front_controllers"])
        out.append(f"请求入口统一由前端控制器（{fc}）接收，再按 `action` 参数分发到各业务 Servlet，"
                   "由 Servlet 完成参数收集、调用业务层、转发到 JSP 展示。\n")
    out.append(md.h(3, "技术栈清单"))
    out.append(md.table(["维度", "现状"], [[r[0], r[1]] for r in tech["rows"]]))

    # ---------- 2. 结构
    out.append(md.h(2, "2. 项目结构"))
    out.append(md.table(["维度", "结论"], tech["build_rows"]))
    out.append("")
    out.append(md.h(3, "代码分布"))
    from collections import defaultdict
    pkg = defaultdict(lambda: {"files": 0, "lines": 0})
    for u in proj["java"]:
        p = pkg[u["package"] or "(默认包)"]
        p["files"] += 1
        p["lines"] += u["lines"]
    out.append(md.table(["Java 包", "文件数", "行数"],
                        [[k, v["files"], v["lines"]]
                         for k, v in sorted(pkg.items(), key=lambda kv: -kv[1]["lines"])]))
    jsp_dirs = defaultdict(int)
    for j in proj["jsp"]:
        d = os.path.dirname(j["file"]) or "."
        jsp_dirs[d] += 1
    if jsp_dirs:
        out.append("")
        out.append(md.h(3, "页面分布"))
        out.append(md.table(["目录", "页面数"],
                            [[f"`{k}`", v] for k, v in sorted(jsp_dirs.items(),
                                                              key=lambda kv: -kv[1])]))

    # ---------- 3. 请求流
    out.append(md.h(2, "3. 请求处理流程"))
    lines = []
    if proj.get("webxml", {}).get("filter_mappings"):
        fdesc = "、".join(f"{m['url_pattern']}" for m in proj["webxml"]["filter_mappings"])
        lines.append(f"过滤器生效范围：{fdesc}")
    lines.append("")
    lines.append("浏览器")
    lines.append("   │  *.do / *.html / *.jsp")
    lines.append("   ▼")
    if proj.get("webxml", {}).get("filters"):
        fnames = "、".join(f["class"].split(".")[-1] for f in proj["webxml"]["filters"])
        lines.append(f"[过滤器] {fnames}")
        lines.append("   │")
        lines.append("   ▼")
    fc = routes["front_controllers"]
    if fc:
        lines.append(f"[前端控制器] {fc[0].split('.')[-1]}   ← 负责登录/登出/改密 + 按 URI 分派")
        lines.append("   │ forward")
        lines.append("   ▼")
    biz_servlets = "、".join(s.split(".")[-1] for e in modules for s in e["servlet"])
    lines.append(f"[业务 Servlet] {biz_servlets or '（未识别）'}")
    lines.append("   │ 调用")
    lines.append("   ▼")
    lines.append("[业务层 Biz/Impl]")
    lines.append("   │ 调用")
    lines.append("   ▼")
    lines.append("[持久层 Dao/Impl]  ← extends BaseDao（JNDI 数据源 + PreparedStatement）")
    lines.append("   │ SQL")
    lines.append("   ▼")
    db = ctx["derived"]["deps"]["dialects"]
    lines.append(f"[数据库] {db[0]['db'] if db else '（未确定）'}")
    lines.append("")
    lines.append("返回结果经 request.setAttribute 注入请求域，Servlet forward 回 JSP 渲染。")
    out.append(md.code("\n".join(lines), "text"))

    # ---------- 4. 模块
    out.append(md.h(2, "4. 功能模块"))
    out.append(f"按真实调用链识别出 {len(modules)} 个业务模块：\n")
    for i, m in enumerate(modules, 1):
        out.append(md.h(3, f"4.{i} {m['domain']}"
                           + (f"（UI 术语 `{m['page_prefix']}*`）" if m["page_prefix"] else "")))
        pages = "、".join(f"`{os.path.basename(p)}`" for p in sorted(m["pages"])) or "（无专属页面）"
        tabs = "、".join(f"`{t}`" for t in m["tables"]) or "（未见）"
        beans = "、".join(s.split(".")[-1] for s in m["biz"]) or "-"
        daos = "、".join(s.split(".")[-1] for s in m["dao"]) or "-"
        ents = "、".join(s.split(".")[-1] for s in m["entity"]) or "-"
        srvs = "、".join(s.split(".")[-1] for s in m["servlet"]) or "-"
        comp = "、".join(m["competences"]) or "未检出"
        out.append(f"**职责**：{m['domain']} 域的 {comp}。"
                   f"页面集合 {pages}。\n")
        out.append(md.table(
            ["层", "构件"],
            [["控制层", srvs], ["业务层", beans], ["持久层", daos],
             ["实体/视图", ents], ["数据表", tabs],
             ["动作", "、".join(f"`{a}`" for a in m["actions"]) or "-"],
             ["能力", comp]]))
        out.append("")

    if unassigned:
        out.append(md.h(3, f"4.{len(modules)+1} 公共 / 其他页面"))
        out.append("不归属任何业务模块："
                   + "、".join(f"`{os.path.basename(p)}`" for p in sorted(unassigned)) + "\n")

    # ---------- 5. 依赖
    out.append(md.h(2, "5. 依赖与环境要求"))
    out.append(md.h(3, "5.1 war 内已打包的 JAR"))
    out.append(md.table(["JAR", "体积"],
                        [[f"`{j['file']}`", f"{j['size']/1024:.0f} KB"] for j in proj["jars"]])
                if proj["jars"] else "（无）\n")
    out.append(md.h(3, "5.2 第三方依赖核对"))
    tp_rows = []
    for tp in deps["third_party"]:
        tp_rows.append([tp["lib"], f"`{tp['namespace']}`", tp["usage"],
                        "是" if tp["in_war"] else "**否**",
                        "、".join(tp["missing_companions"]) or "-"])
    out.append(md.table(["依赖库", "命名空间", "引用次数", "已打包", "缺少配套"], tp_rows)
                if tp_rows else "（未见第三方依赖）\n")
    out.append(md.h(3, "5.3 运行容器要求"))
    reqs = []
    if proj["jndi"]:
        reqs.append("需在容器中配置 JNDI 数据源：" + "、".join(f"`{u}`" for u in proj["jndi"]))
    for d in deps["dialects"]:
        if not d["driver_in_war"]:
            reqs.append(f"{d['db']} 驱动（`{'` 或 `'.join(d['driver_jars'])}`）"
                        "未打进 war，需由容器 lib 目录提供")
    wxml = proj.get("webxml") or {}
    reqs.append(f"Servlet 容器需支持 Servlet {wxml.get('schema_version', '?')} 规范")
    out.append(md.bullets(reqs) if reqs else "（无法推断）\n")

    # ---------- 6. 数据
    out.append(md.h(2, "6. 数据对象"))
    alltabs = sorted({t for s in proj["sql"] for t in s["tables"]})
    views = sorted({t for s in proj["sql"] for t in s["views"]})
    seqs = sorted({t for s in proj["sql"] for t in s["sequences"]})
    used = sorted({t for u in proj["java"] for t in u["tables"]
                   if not t.startswith("(")})
    if alltabs or used:
        out.append(md.table(["类别", "对象"], [
            ["SQL 脚本中的表", "、".join(alltabs) or "-"],
            ["SQL 脚本中的视图", "、".join(views) or "-"],
            ["SQL 脚本中的序列", "、".join(seqs) or "-"],
            ["源码 SQL 引用的表", "、".join(used) or "-"]]))
    else:
        out.append("（未发现建表脚本或 SQL 引用）\n")

    # ---------- 7. 风险
    out.append(md.h(2, "7. 风险与技术债"))
    sev_order = {"高": 0, "中": 1, "低": 2, "提示": 3}
    for r in sorted(risks, key=lambda x: sev_order.get(x["level"], 9)):
        out.append(md.h(3, f"[{r['level']}] {r['title']}"))
        out.append(r["detail"] + "\n")
        if r["evidence"]:
            out.append("证据：\n")
            out.append(md.bullets([f"`{e}`" if not str(e).startswith("`") else str(e)
                                   for e in r["evidence"]]))

    # ---------- 8. 建议
    out.append(md.h(2, "8. 维护与现代化建议"))
    recs = _recommendations(proj, tech, risks, deps, modules)
    out.append(md.table(["优先级", "建议", "理由"], recs))

    # ---------- 附录
    out.append(md.h(2, "附录 A · 产物清单"))
    order = [("00-preflight.md", "环境预检"), ("01-structure.md", "项目结构"),
             ("02-dependencies.md", "依赖关系"), ("03-modules.md", "功能模块"),
             ("10-requirement-analysis.md", "需求分析报告（本文）"),
             ("99-summary.md", "一页摘要"), ("facts.json", "机读事实库")]
    out.append(md.table(["文件", "内容"], [[f"`{n}`", d] for n, d in order]))
    out.append(md.h(2, "附录 B · 复现命令"))
    out.append(md.code(ctx.get("repro", ""), "powershell"))
    out.append(md.h(2, "附录 C · Java 类全清单"))
    out.append(md.table(["类", "层", "包", "行数", "方法数"],
                        [[u["primary_type"], u["layer"], u["package"],
                          u["lines"], u["method_count"]]
                         for u in sorted(proj["java"], key=lambda x: (x["layer"], x["primary_type"]))]))

    text = "\n".join(out)
    p1 = md.write_atomic(os.path.join(ctx["out"], "10-requirement-analysis.md"), text)

    # ---------------- 一页摘要
    s = []
    s.append(md.h(1, f"{proj['name']} 分析摘要"))
    s.append(f"> 生成时间 {md.now()} · {TOOL_VERSION}\n")
    s.append(md.h(2, "一句话"))
    s.append(f"{proj['name']}：{tech['arch']} 的 Java Web 应用，"
             f"{len(proj['java'])} 类 / {len(proj['jsp'])} 页 / {code_lines:,} 行代码，"
             f"{len(modules)} 个业务模块。\n")
    s.append(md.h(2, "模块一览"))
    s.append(md.table(["模块", "UI 前缀", "页面", "能力", "主要表"],
                      [[m["domain"], f"`{m['page_prefix']}*`" if m["page_prefix"] else "-",
                        len(m["pages"]), "、".join(m["competences"]) or "-",
                        "、".join(m["tables"][:3]) or "-"] for m in modules]))
    s.append(md.h(2, "技术栈"))
    s.append(md.table(["维度", "现状"], [[r[0], r[1]] for r in tech["rows"]]))
    s.append(md.h(2, "Top 风险"))
    s.append(md.table(["级别", "问题"],
                      [[r["level"], r["title"]]
                       for r in sorted(risks, key=lambda x: sev_order.get(x["level"], 9))[:6]]))
    s.append(md.h(2, "建议优先做"))
    s.append(md.bullets([f"**{r[0]}** — {r[1]}" for r in recs[:4]]))
    s.append(md.h(2, "产物"))
    s.append(md.bullets([f"`{n}`" for n, _ in order]))
    text2 = "\n".join(s)
    p2 = md.write_atomic(os.path.join(ctx["out"], "99-summary.md"), text2)

    strip_internal(proj)
    ctx["docs"]["report"] = p1
    ctx["docs"]["summary"] = p2
    return [p1, p2]


def _recommendations(proj, tech, risks, deps, modules) -> list:
    recs = []
    titles = {r["title"] for r in risks}

    if any(r["level"] == "高" for r in risks):
        recs.append(["P0", "处理会话中的口令类字段",
                     "会话明文保存密码，属安全问题，应先于任何重构处理"])
    if "静态资源悬空引用" in titles:
        recs.append(["P1", "补齐或移除悬空的 css/js/图片引用",
                     "页面当前依赖不存在的文件，属于可直接修复的显性缺陷"])
    if "欢迎页配置失效" in titles:
        recs.append(["P2", "修正 web.xml 的 welcome-file",
                     "配置指向不存在资源，会导致首屏 404 或回退行为不确定"])

    missing = [t for t in deps["third_party"] if not t["in_war"] or t["missing_companions"]]
    if missing:
        recs.append(["P1", "补齐第三方依赖清单",
                     "源码引用了 war 中缺失的库：" + "、".join(m["lib"] for m in missing)])
    if proj["jndi"] and any(not d["driver_in_war"] for d in deps["dialects"]):
        recs.append(["P1", "固化运行环境说明（JNDI + 驱动）",
                     "数据源与 JDBC 驱动都在容器侧，缺少文档会导致「换台机器就跑不起来」"])
    if "遗留 System.out 调试输出" in titles:
        recs.append(["P2", "用日志框架替换 System.out",
                     "便于分级、落盘与线上排障"])
    if "无显式事务边界" in titles:
        recs.append(["P1", "为跨表写操作补事务边界",
                     "逐语句取连接且无 commit/rollback，异常时会产生脏数据"])
    if "遗留 TODO/FIXME 标记" in titles:
        recs.append(["P3", "清理 TODO/FIXME 并登记为条目",
                     "避免未完成意图被埋没在代码里"])
    recs.append(["P3", "把 `WEB-INF/classes` 的 `.class` 与体积较大的二进制加入 .gitignore",
                 "编译产物入库会让 diff/评审噪声变大"])
    recs.append(["P3", "先固化一份「能跑起来的环境说明」再谈重构",
                 "老项目最大的风险是无人知道如何启动；本报告第 5 节已给出线索"])
    return sorted(recs, key=lambda r: r[0])
