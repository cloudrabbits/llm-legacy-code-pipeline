"""技术栈指纹：从磁盘上的"物证"推断老项目的技术选型与运行环境。

判定全部带**证据**（哪个文件、哪行 counstruct），避免拍脑袋下结论。
"""

from __future__ import annotations

import os
import re

import lib_scan


def build(project: dict) -> dict:
    root = project["root"]
    rows = []
    build_rows = []
    notes = []

    java = project["java"]
    jsp = project["jsp"]
    allnames = set()
    for f in project["files"]:
        allnames.add(os.path.basename(f["file"]).lower())
    for b in project["binaries"]:
        allnames.add(os.path.basename(b["file"]).lower())

    # ---- 视图层
    if jsp:
        s_cnt = sum(j["scriptlet_blocks"] for j in jsp)
        el_files = sum(1 for j in jsp if j["el_expressions"])
        jstl = sorted({p for j in jsp for p in j["taglibs"]})
        rows.append(("视图技术", "JSP（含脚本片段）" if s_cnt else "JSP",
                     f"{len(jsp)} 个 .jsp，累计 {s_cnt} 个 `<% %>` 片段；"
                     f"{el_files} 个文件使用 EL 表达式"))
        rows.append(("标签库", "JSTL：" + "、".join(jstl) if jstl else "未使用 taglib",
                     "来自 `<%@ taglib %>` 指令" if jstl else "全仓库未见 taglib 指令"))
        encs = sorted({j["page_directives"].get("pageEncoding", "") for j in jsp} - {""})
        if encs:
            rows.append(("页面编码", "、".join(encs), "JSP `pageEncoding` 指令"))

    # ---- 控制层（Servlet vs 框架）
    webxml = project.get("webxml") or {}
    servlets = webxml.get("servlets", [])
    mvc_framework = None
    for name, label in (("struts.xml", "Struts2"), ("struts-config.xml", "Struts1"),
                        ("applicationContext.xml", "Spring"), ("spring-servlet.xml", "Spring MVC")):
        if name in allnames:
            mvc_framework = label
    if mvc_framework:
        rows.append(("MVC 框架", mvc_framework, f"存在 `{mvc_framework}` 配置文件"))
    else:
        rows.append(("MVC 框架", "无框架，裸 Servlet + 前端控制器",
                     f"web.xml 声明 {len(servlets)} 个 Servlet，"
                     "未见 Struts/Spring 配置"))

    # 是否有"前端控制器"模式
    fc = [u for u in java if re.search(r'action\.equals\("[\w.]+\.(do|action)"\)', u["_body"])]
    if fc:
        rows.append(("请求分发模式", "前端控制器（Front Controller）",
                     "、".join(f"`{u['primary_type']}`" for u in fc)
                     + " 用 `requestURI` 尾段 + `action` 字符串分派"))

    # ---- 浏览器端
    js_libs = []
    for f in project["files"]:
        bn = os.path.basename(f["file"]).lower()
        if f["ext"] == ".js":
            if "jquery" in bn:
                js_libs.append(f"jQuery（`{f['file']}`）")
            elif bn.endswith(".min.js"):
                js_libs.append(f"`{f['file']}`")
    if js_libs:
        rows.append(("前端脚本", "、".join(sorted(set(js_libs))[:4]),
                     "静态资源目录扫描"))
    ajax = sorted({u for j in jsp for u in j["ajax_urls"]})
    if ajax:
        rows.append(("异步交互", f"{len(ajax)} 个异步入口",
                     "、".join(f"`{a}`" for a in ajax[:5])))

    # ---- 持久层
    dao = [u for u in java if u["layer"] == "持久层"]
    if dao:
        raw_jdbc = [u for u in dao if "java.sql.Connection" in u["imports"]]
        orm = None
        for ns, name in (("org.hibernate", "Hibernate"), ("org.mybatis", "MyBatis"),
                         ("com.ibatis", "iBATIS"), ("javax.persistence", "JPA")):
            if any(i.startswith(ns) for u in java for i in u["imports"]):
                orm = name
        if orm:
            rows.append(("持久层", orm, f"import 前缀 `{ns}`"))
        else:
            rows.append(("持久层", "手写 JDBC（PreparedStatement）",
                         f"{len(raw_jdbc)} 个 DAO 直接使用 `java.sql.*`，未见 ORM import"))

    # ---- 数据源 / 数据库
    if project["jndi"]:
        rows.append(("数据源获取", "JNDI 容器数据源（DataSource）",
                     "、".join(f"`{u}`" for u in project["jndi"])))
    if project["jdbc_urls"]:
        rows.append(("连接串", "、".join(project["jdbc_urls"]), "源码字符串"))
    if project["drivers"]:
        rows.append(("显式驱动注册", "、".join(project["drivers"]), "`Class.forName`"))

    from lib_scan import detect_missing_deps, external_import_groups
    internal = {t["type"] for u in java for t in u["types"]}
    ext = external_import_groups(java, internal)
    _, dialects = detect_missing_deps(project, ext)
    if dialects:
        d = dialects[0]
        rows.append(("数据库类型", d["db"], f"证据：{d['evidence']}"))
    elif dao:
        rows.append(("数据库类型", "未能确定（需人工确认）",
                     "DAO 有 JDBC 调用，但未见连接串或方言函数"))

    # ---- Servlet 规范版本
    if project.get("webxml"):
        w = project["webxml"]
        rows.append(("Servlet 规范",
                     f"web.xml 声明 {w['declared_version']} / Schema {w['schema_version']}",
                     f"`{w['file']}`"))

    # ================= 构建形态 =================
    ide = []
    for mark, label in ((".project", "Eclipse/MyEclipse"), (".mymetadata", "MyEclipse Web 模块"),
                        (".classpath", "Eclipse classpath"), ("pom.xml", "Maven"),
                        ("build.xml", "Ant"), ("build.gradle", "Gradle"),
                        (".idea", "IntelliJ IDEA"), (".settings", "Eclipse 设置目录")):
        if mark.startswith(".") and mark != ".settings":
            p = os.path.join(root, mark)
            if os.path.exists(p):
                ide.append(label)
        elif mark in allnames:
            ide.append(label)
    build_rows.append(("构建方式", "、".join(sorted(set(ide))) or "无构建脚本（纯 IDE 工程）"))
    build_rows.append(("依赖管理", "手工拷贝 JAR 到 WEB-INF/lib"
                       if project["jars"] and "pom.xml" not in allnames
                       else ("Maven/Gradle" if {"pom.xml", "build.gradle"} & allnames else "未知")))
    build_rows.append(("打包形态", "WAR 目录结构（WebRoot）"
                       if any(f["file"].startswith("WebRoot/") for f in project["files"])
                       or any(b["file"].startswith("WebRoot/") for b in project["binaries"])
                       else "非标准 WAR 布局"))

    compiled = [b for b in project["binaries"] if b["ext"] == ".class"]
    if compiled:
        notes.append(f"仓库内混入了 {len(compiled)} 个 `.class` 编译产物"
                     "（`WEB-INF/classes`），它们与 `src` 重复，统计时已排除；"
                     "这类文件入库会让 diff 噪声很大，建议加入 `.gitignore`。")

    arch_bits = []
    if mvc_framework:
        arch_bits.append(mvc_framework)
    if any(u["layer"] == "控制层" for u in java):
        arch_bits.append("Servlet")
    if any(u["layer"] == "业务层" for u in java):
        arch_bits.append("Biz/Service")
    if any(u["layer"] == "持久层" for u in java):
        arch_bits.append("DAO")
    arch = " + ".join(arch_bits) if arch_bits else "未识别 layered"

    layers_present = sorted({u["layer"] for u in java})
    build_rows.append(("分层形态", "、".join(layers_present)))

    return {"arch": arch, "rows": rows, "build_rows": build_rows, "notes": notes}
