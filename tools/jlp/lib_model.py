"""派生模型层：把散落的静态事实聚合成"人类关心"的模型。

输入是 lib_scan 的事实字典，输出四类派生模型：
  * routes   —— URL 路由与前端控制器分派表（请求怎么流）
  * modules  —— 功能模块纵向切片（页面 -> Servlet -> Biz -> Dao -> 实体 -> 表）
  * matrix   —— 每个模块的 CRUD / 查询能力矩阵
  * risks    —— 确定性的风险清单（不靠模型"看感觉"，全部由检测规则命中）

这些结果同样由脚本算出，LLM 只负责改写成（可选），不参与生成。
"""

from __future__ import annotations

import os
import re

from lib_scan import RE_ACTION_EQ, RE_FORWARD, RE_REDIRECT, RE_PARAM, RE_BIZ_CALL


# ---------------------------------------------------------------- 控制器分派

def parse_dispatch_branches(text: str):
    """按 `if (action.equals("x"))` / `if (action == null)` 切分出每个分支的行为。

    老项目的 Servlet 基本都长这样：一个 process() 里用 if/else if 判断 action，
    每个分支里转发或重定向。把分支切开，才能知道"哪个动作 -> 跳哪个页面"。
    """
    marks = []
    for m in re.finditer(r'action\s*==\s*null', text):
        marks.append((m.start(), "(无 action 参数/默认)"))
    for m in RE_ACTION_EQ.finditer(text):
        marks.append((m.start(), m.group(1)))
    marks.sort(key=lambda x: x[0])

    branches = []
    for i, (pos, label) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end]
        branches.append({
            "action": label,
            "forwards": sorted(set(RE_FORWARD.findall(body))),
            "redirects": sorted(set(RE_REDIRECT.findall(body))),
            "params": sorted(set(RE_PARAM.findall(body))),
            "biz_calls": sorted({".".join(c) for c in RE_BIZ_CALL.findall(body)}),
        })
    return branches


def _route_kind(pattern: str) -> str:
    if pattern.startswith("*."):
        return "extension"
    if pattern.endswith("/*"):
        return "prefix"
    if pattern.startswith("/"):
        return "exact"
    return "other"


def _match_route(pattern: str, target: str) -> bool:
    """判断 URL patter 是否能命中 target（target 为规范化后的相对路径）。"""
    kind = _route_kind(pattern)
    if kind == "exact":
        return pattern == target or pattern.lstrip("/") == target.lstrip("/")
    if kind == "prefix":
        base = pattern.rstrip("/*")
        return target == base.lstrip("/") or target.startswith(base.lstrip("/") + "/")
    if kind == "extension":
        return target.endswith(pattern[1:])
    return pattern == target


def build_routes(project: dict) -> dict:
    """构建路由模型：web.xml 映射 + 前端控制器内部分派。

    返回 {routes, by_class, front_controllers, controllers}
    """
    webxml = project.get("webxml") or {}
    java = {u["primary_type"]: u for u in project["java"]}

    routes = []
    for m in webxml.get("servlet_mappings", []):
        cls = ""
        jsp = ""
        for s in webxml.get("servlets", []):
            if s["name"] == m["name"]:
                cls = s["class"]
                jsp = s.get("jsp", "")
        routes.append({
            "pattern": m["url_pattern"],
            "kind": _route_kind(m["url_pattern"]),
            "servlet_name": m["name"],
            "servlet_class": cls,
            "jsp_file": jsp,
        })

    # 精确 > 前缀 > 扩展名（Servlet 规范匹配优先级）
    order = {"exact": 0, "prefix": 1, "extension": 2, "other": 3}
    routes.sort(key=lambda r: order[r["kind"]])

    controllers = {}
    front = []
    for r in routes:
        u = java.get(r["servlet_class"].split(".")[-1])
        if not u:
            continue
        if u["actions"] or u["uses_action_param"]:
            branches = parse_dispatch_branches(u["_body"])
            controllers[r["servlet_class"]] = branches
            if u.get("jdbc_url") is None and not u["actions"]:
                pass
            # 前端控制器：用 requestURI 尾部判断 action，action 名字带 url 后缀
            if any(a.endswith((".do", ".action", ".do?"))
                   or re.search(r'action\.equals\("[\w.]+\.(do|action)"\)', u["_body"])
                   for a in u["actions"]):
                front.append(r["servlet_class"])

    return {
        "routes": routes,
        "controllers": controllers,
        "front_controllers": sorted(set(front)),
    }


def resolve_owner(routes: dict, target: str):
    """把页面里的目标（`Users.do?action=add`）解析到真正处理它的 Servlet 类。

    返回 (servlet_class, 解析路径说明 list)
    """
    # 规范化：去协议/域名、去查询串、去 ../ 前缀
    t = target.strip()
    t = re.sub(r'^https?://[^/]+/', '', t)
    t = t.split("?")[0].split("#")[0]
    while t.startswith("../"):
        t = t[3:]
    t = t.lstrip("./")
    trace = []

    hit = None
    for r in routes["routes"]:
        if _match_route(r["pattern"], "/" + t) or _match_route(r["pattern"], t):
            hit = r
            break
    if not hit:
        return None, [f"{target}：未匹配任何 url-pattern"]

    trace.append(f"`{t}` 命中 `{hit['pattern']}`（{hit['kind']}）")
    if hit["servlet_class"] in routes["front_controllers"]:
        base = os.path.basename(t)
        branches = routes["controllers"].get(hit["servlet_class"], [])
        br = next((b for b in branches if b["action"].lower() == base.lower()), None)
        if not br:
            trace.append(f"{hit['servlet_class'].split('.')[-1]}：未找到 `{base}` 分派分支")
            return hit["servlet_class"], trace
        trace.append(f"{hit['servlet_class'].split('.')[-1]} 分派 `{base}`")
        dest = (br["forwards"] + br["redirects"])
        if not dest:
            return hit["servlet_class"], trace
        nxt = dest[0]
        trace.append(f"转交 `{nxt}`")
        t2 = nxt.split("?")[0]
        while t2.startswith("../"):
            t2 = t2[3:]
        t2 = t2.lstrip("./")
        for r in routes["routes"]:
            if _match_route(r["pattern"], "/" + t2) or _match_route(r["pattern"], t2):
                if r["servlet_class"]:
                    cls_short = r["servlet_class"].split(".")[-1]
                    trace.append(f"命中 `{r['pattern']}` -> {cls_short}")
                    return r["servlet_class"], trace
        return None, trace

    return hit["servlet_class"], trace


# ---------------------------------------------------------------- 页面归属

def _page_candidates(jsp_unit) -> list:
    """页面"主动发起"的请求目标（区别于全站导航栏链接）。"""
    out = []
    for a in jsp_unit["form_actions"]:
        out.append(("表单提交", a))
    for a in jsp_unit["ajax_urls"]:
        out.append(("异步请求", a))
    return out


def _strip_crud_suffix(stem: str) -> str:
    return re.sub(
        r'(?i)(add|save|update|edit|modify|delete|del|remove|list|view|detail'
        r'|index|form|query|search|input|new|main|manage)$', '', stem)


def _common_prefix(strings) -> str:
    if not strings:
        return ""
    s1 = min(strings)
    s2 = max(strings)
    for i, c in enumerate(s1):
        if c != s2[i]:
            return s1[:i]
    return s1


def page_group_label(stems) -> str:
    """从页面名反推"前端术语"：userAdd/userList -> user*。

    很多老项目后端命名（Suppliers）和前端命名（provider*）不一致，
    这个标签能让人一眼看出映射关系。
    """
    cores = [_strip_crud_suffix(s) for s in stems]
    cores = [c for c in cores if c]
    if len(cores) < 2:
        return ""
    p = _common_prefix(cores)
    return p.rstrip("-_") if len(p) >= 3 else ""


# ---------------------------------------------------------------- 模块切分

def derive_modules(project: dict, routes: dict) -> list:
    """按"业务纵向切片"聚类出功能模块。

    以 XxxBiz（业务接口）作为领域种子，向下找 Dao / 实体 / 表，向上找 Servlet，
    再用真实的调用边把页面挂到对应 Servlet 上。
    """
    java_units = project["java"]
    by_name = {u["primary_type"]: u for u in java_units}
    java_to_file = {u["primary_type"]: u["file"] for u in java_units}

    def full(cls_short):
        u = by_name.get(cls_short)
        return f"{u['package']}.{cls_short}" if u and u["package"] else cls_short

    modules = []

    # 领域种子：优先 XxxBiz / XxxService，退化到 XxxServlet
    seeds = {}
    for u in java_units:
        t = u["primary_type"]
        for suf in ("Biz", "Service", "Dao", "Servlet", "Action", "Manager"):
            if t.endswith(suf) and len(t) > len(suf):
                seeds.setdefault(t[:-len(suf)], []).append(u)

    # 前端控制器属于基础设施，不作为业务模块种子（否则会多出一个空壳模块）
    front_short = {c.split(".")[-1] for c in routes.get("front_controllers", [])}

    for domain, units in sorted(seeds.items()):
        if all(u["primary_type"] in front_short for u in units):
            continue
        mod = {
            "domain": domain,
            "servlet": [], "biz": [], "dao": [], "entity": [],
            "tables": [], "pages": [], "actions": [],
            "competences": [], "page_prefix": "",
        }
        for u in units:
            t = u["primary_type"]
            if t.endswith(("Servlet", "Action")):
                mod["servlet"].append(full(t))
            elif t.endswith(("Biz", "Service", "Manager")):
                mod["biz"].append(full(t))
            elif t.endswith(("Dao", "Mapper", "Repository")):
                mod["dao"].append(full(t))

        # 各层的实现类（XxxBizImpl）
        impls = []
        for u in java_units:
            t = u["primary_type"]
            m = re.match(rf'^{re.escape(domain)}(Biz|Service|Dao|Servlet|Action)Impl$', t)
            if m:
                impls.append(full(t))
                key = {"Biz": "biz", "Service": "biz", "Dao": "dao",
                       "Servlet": "servlet", "Action": "servlet"}[m.group(1)]
                mod[key].append(full(t))
        mod["_impls"] = impls

        # 实体 + 表：通过该领域的 Dao 实现所 import / 引用的本工程实体得到
        entity_names = set()
        for fqbean in [m for m in mod["dao"]]:
            short = fqbean.split(".")[-1]
            u = by_name.get(short)
            if not u:
                continue
            for imp in u["imports"]:
                cand = imp.split(".")[-1]
                v = by_name.get(cand)
                if v and v["layer"] in ("实体/POJO", "视图对象"):
                    entity_names.add(cand)
            same_pkg = [v["primary_type"] for v in java_units
                        if v["package"] == u["package"] and v["layer"] in ("实体/POJO", "视图对象")]
            for cand in same_pkg:
                if re.search(rf"\b{re.escape(cand)}\b", u.get("_body", "")):
                    entity_names.add(cand)
        # 兜底：同名实体
        if not entity_names and domain in by_name:
            entity_names.add(domain)
        mod["entity"] = sorted(full(e) for e in entity_names)

        # 数据表：SQL 里的表名 + 实体同名的表
        tables = set()
        for fqbean in mod["dao"]:
            u = by_name.get(fqbean.split(".")[-1])
            if u:
                tables |= set(u["tables"])
        mod["tables"] = sorted(tables)

        modules.append(mod)

    # ---- 页面归属：三级信号，优先级从强到弱
    #   1. 页面主动发起（表单提交 / 异步请求）——最可靠
    #   2. Servlet forward 到该页面——覆盖「查看详情」这类纯展示页
    #   3. 页面内的普通链接——先剔除全站导航栏（在多数页面都出现的链接）
    jsp_units = project["jsp"]
    owner_of = {}

    for ju in jsp_units:
        for kind, target in _page_candidates(ju):
            if not target or target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            owner, trace = resolve_owner(routes, target)
            if owner:
                owner_of.setdefault(ju["file"], (owner, kind, target, trace))
                break

    # -- 二级：Servlet forward 目标
    def _norm_page(t: str) -> str:
        t = t.split("?")[0].split("#")[0]
        while t.startswith("../"):
            t = t[3:]
        return t.lstrip("./")

    for u in java_units:
        if not u["package"]:
            continue
        fq = f"{u['package']}.{u['primary_type']}"
        for fwd in u["forwards"]:
            t = _norm_page(fwd)
            for ju in jsp_units:
                if t and ju["file"].endswith(t) and ju["file"] not in owner_of:
                    owner_of.setdefault(
                        ju["file"],
                        (fq, "Servlet 转发", fwd, [f"`{u['primary_type']}` 转发到 `{fwd}`"]))
        for rd in u["redirects"]:
            t = _norm_page(rd)
            if not t or t.endswith((".do", ".action")):
                continue
            for ju in jsp_units:
                if ju["file"].endswith(t) and ju["file"] not in owner_of:
                    owner_of.setdefault(
                        ju["file"],
                        (fq, "Servlet 重定向", rd, [f"`{u['primary_type']}` 重定向到 `{rd}`"]))

    # -- 三级：普通链接（剔除导航栏）
    from collections import Counter
    freq = Counter(h.split("?")[0] for ju in jsp_units for h in ju["hrefs"])
    nav_threshold = max(2, int(0.5 * len(jsp_units)))
    nav_targets = {h for h, c in freq.items() if c >= nav_threshold}
    for ju in jsp_units:
        if ju["file"] in owner_of:
            continue
        for h in ju["hrefs"]:
            t = h.split("?")[0]
            if t in nav_targets or not t or \
                    t.startswith(("http://", "https://", "#", "mailto:", "javascript:")):
                continue
            owner, trace = resolve_owner(routes, h)
            if owner:
                owner_of.setdefault(ju["file"], (owner, "页面链接", h, trace))
                break

    for mod in modules:
        srv_short = {s.split(".")[-1] for s in mod["servlet"]}
        for ju in jsp_units:
            info = owner_of.get(ju["file"])
            if info and info[0].split(".")[-1] in srv_short:
                mod["pages"].append(ju["file"])

    # 模块能力：从 Dao 实现的 SQL 与方法名推断
    for mod in modules:
        ops = {"新增": False, "删除": False, "修改": False, "查询": False, "分页": False,
               "模糊查询": False}
        for fqbean in mod["dao"]:
            u = by_name.get(fqbean.split(".")[-1])
            if not u:
                continue
            blob = " ".join(u["sqls"]).lower()
            if "insert into" in blob:
                ops["新增"] = True
            if "delete from" in blob:
                ops["删除"] = True
            if blob.strip().startswith("update") or " update " in blob:
                ops["修改"] = True
            if "select" in blob or " count(" in blob:
                ops["查询"] = True
            if "rownum" in blob or "limit" in blob or "pageinfo" in blob.lower():
                ops["分页"] = True
            if "like ?" in blob or "like '%" in blob:
                ops["模糊查询"] = True
            mnames = {m["name"].lower() for m in u["methods"]}
            if {"getpageinfo", "getpage", "page"} & mnames:
                ops["分页"] = True
            if {"findbyname", "search", "querybyname"} & mnames:
                ops["模糊查询"] = True
        mod["competences"] = [k for k, v in ops.items() if v]

        stems = [os.path.splitext(os.path.basename(p))[0] for p in mod["pages"]]
        mod["page_prefix"] = page_group_label(stems)

    # 动作清单：Servlet 分支
    for mod in modules:
        acts = set()
        for s in mod["servlet"]:
            for br in routes["controllers"].get(s, []):
                acts.add(br["action"])
        mod["actions"] = sorted(acts)

    # 去掉基础设施残留：既没有专属页面、也没有完整的 控制层+业务层+持久层 三件套
    modules = [m for m in modules
               if m["pages"] or (m["servlet"] and m["biz"] and m["dao"])]

    # 「未归属」指没能落到任何**业务模块**上；被前端控制器转发产生的不算归属。
    mod_short = {s.split(".")[-1] for m in modules for s in m["servlet"]}
    unassigned = [j["file"] for j in jsp_units
                  if not (owner_of.get(j["file"])
                          and owner_of[j["file"]][0].split(".")[-1] in mod_short)]
    return modules, unassigned, owner_of


# ---------------------------------------------------------------- 风险

STATIC_EXT = {".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".ico",
              ".html", ".htm", ".svg", ".woff", ".woff2", ".ttf", ".swf"}


def derive_risks(project: dict, modules, unassigned):
    """确定性风险清单。每条都带证据，便于人工复核。"""
    risks = []
    root = project["root"]
    java = project["java"]

    # 1) 缺失/悬空静态资源引用
    web_roots = set()
    for ju in project["jsp"] + []:
        web_roots.add(os.path.dirname(os.path.join(root, ju["file"])))
    for f in project["files"]:
        d = os.path.dirname(os.path.join(root, f["file"]))
        if os.sep + "WebRoot" in d or d.endswith("WebRoot"):
            web_roots.add(d)

    dangling = []
    htmlish = [f for f in project["files"] if f["ext"] in (".jsp", ".html", ".htm")]
    for f in htmlish:
        text, _ = None, None
        from lib_scan import read_text
        try:
            text, _ = read_text(os.path.join(root, f["file"]))
        except OSError:
            continue
        base_dir = os.path.dirname(os.path.join(root, f["file"]))
        # 去掉注释块，否则被 `<!-- ... -->` 注释掉的旧引用会被当成缺失资源
        scan_src = re.sub(r'<!--.*?-->', '', text, flags=re.S)
        for ref in re.findall(r'(?:href|src)\s*=\s*"([^"]+)"', scan_src):
            r = ref.strip()
            if not r or r.startswith(("http://", "https://", "//", "#", "mailto:", "javascript:")):
                continue
            if "${" in r or "<%" in r:
                continue
            ext = os.path.splitext(r.split("?")[0])[1].lower()
            if ext not in STATIC_EXT:
                continue
            candidates = [os.path.normpath(os.path.join(base_dir, r))]
            for wr in _app_root_candidates(root, f["file"]):
                candidates.append(os.path.normpath(os.path.join(wr, r.lstrip("/"))))
            if not any(os.path.exists(c) for c in candidates):
                dangling.append((f["file"], r))
    if dangling:
        risks.append({
            "level": "中",
            "title": "静态资源悬空引用",
            "detail": "页面引用了仓库中不存在的文件，部署后对应样式/脚本/图片会 404。",
            "evidence": [f"`{a}` -> `{b}`" for a, b in sorted(set(dangling))[:15]],
        })

    # 2) welcome-file 指向缺失资源
    webxml = project.get("webxml") or {}
    missing_welcome = []
    for w in webxml.get("welcome_files", []):
        paths = [os.path.join(root, w.lstrip("/"))]
        for wr in _app_root_candidates(root, ""):
            paths.append(os.path.join(wr, w.lstrip("/")))
        if not any(os.path.exists(p) for p in paths):
            missing_welcome.append(w)
    if missing_welcome:
        risks.append({
            "level": "低",
            "title": "欢迎页配置失效",
            "detail": "web.xml 声明的 welcome-file 在仓库中不存在，容器会退到下一个或报 404。",
            "evidence": missing_welcome,
        })

    # 3) 调试输出
    pl = sum(u["println_count"] for u in java)
    if pl:
        worst = sorted(java, key=lambda u: -u["println_count"])[:5]
        risks.append({
            "level": "低",
            "title": "遗留 System.out 调试输出",
            "detail": f"共 {pl} 处 console 打印，生产环境应改为日志框架便于分级与落盘。",
            "evidence": [f"`{u['primary_type']}` × {u['println_count']}" for u in worst if u["println_count"]],
        })

    # 4) TODO/FIXME
    td = sum(u["todo_count"] for u in java)
    if td:
        risks.append({
            "level": "低",
            "title": "遗留 TODO/FIXME 标记",
            "detail": f"共 {td} 处未完成标记。",
            "evidence": sorted({u["primary_type"] for u in java if u["todo_count"]}),
        })

    # 5) 会话中保存敏感字段
    pwd_attrs = sorted({a for u in java for a in u["session_attrs"]
                        if re.search(r'(?i)pwd|pass|password', a)})
    if pwd_attrs:
        risks.append({
            "level": "高",
            "title": "会话中明文保存口令类字段",
            "detail": "密码被写入 HttpSession，任何能访问会话的代码/调试页都可读取。",
            "evidence": pwd_attrs,
        })

    # 6) 逐操作取连接、无显式事务
    txish = [u["primary_type"] for u in java
             if "commit(" not in u.get("_body", "") and u["layer"] == "持久层"
             and "getPoolConnection" in u.get("_body", "")]
    if txish:
        risks.append({
            "level": "中",
            "title": "无显式事务边界",
            "detail": "持久层每条 SQL 独立取连接且未调用 commit/rollback，跨表写操作无法保证一致性。",
            "evidence": sorted(txish),
        })

    # 7) 未归属页面
    if unassigned:
        risks.append({
            "level": "提示",
            "title": "未归属到业务模块的页面",
            "detail": "这些页面没有指向任何 Servlet 的表单/异步请求，通常是公共页或已被废弃。",
            "evidence": sorted(unassigned),
        })

    # 8) 未接入工程的类
    assigned = set()
    for m in modules:
        for key in ("servlet", "biz", "dao", "entity"):
            assigned |= {s.split(".")[-1] for s in m[key]}
    orphan = [u["primary_type"] for u in java if u["primary_type"] not in assigned]
    if orphan:
        risks.append({
            "level": "提示",
            "title": "未参与任何业务切片的类",
            "detail": "通常是工具类/过滤器/基础设施，也可能是已废弃代码，需人工确认。",
            "evidence": sorted(orphan),
        })

    return risks


def _app_root_candidates(project_root: str, rel_file: str):
    """猜 Web 应用根（WebRoot / webapp / src/main/webapp / 项目根）。"""
    cands = []
    for name in ("WebRoot", "webapp", "WebContent", "src/main/webapp"):
        p = os.path.join(project_root, *name.split("/"))
        if os.path.isdir(p):
            cands.append(p)
    cands.append(project_root)
    return cands
