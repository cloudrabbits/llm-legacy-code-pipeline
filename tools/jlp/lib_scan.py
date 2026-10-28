"""JSP 老项目的**确定性事实抽取层**。

工程原则（沿用并收敛自 nightly 编排器的实测结论）：
    "I will simulate running `find|wc -l` and report plausible exact numbers"
  —— LLM 在缺少脚本供给时会编造统计数字。因此本模块负责把**一切**数字、
     清单、依赖边、路由表算出来；上层最多让 LLM 把这些事实改写成叙述。

本文件只做静态解析，不编译、不执行、不联网、不写被分析项目（只读）。

Windows 适配：
  * 编码按 utf-8-sig -> utf-8 -> gb18030 -> big5 -> latin-1 逐级降级，
    并记录每个文件实际命中的编码（老项目 SQL/Java 常见 GBK）；
  * 只使用标准库，无第三方依赖；
  * 路径输出统一为 `/` 分隔符，避免 Windows 反斜杠进入 Markdown 表格。
"""

from __future__ import annotations

import os
import re
import json
import datetime

# ---------------------------------------------------------------- 基础配置

#: 需要读取正文的文本扩展名（其余按二进制计数，不解析）
TEXT_EXT = {
    ".java", ".jsp", ".jspf", ".tag", ".tld", ".html", ".htm",
    ".js", ".css", ".xml", ".properties", ".sql", ".json", ".md", ".txt",
    ".classpath", ".project", ".mymetadata", ".mf",
}

#: 参与"源码行数"统计的扩展名
CODE_EXT = {".java", ".jsp", ".jspf", ".html", ".htm", ".js", ".css", ".sql", ".xml"}

EXT_LABEL = {
    ".java": "Java 源码", ".jsp": "JSP 页面", ".jspf": "JSP 片段",
    ".tag": "JSP Tag", ".tld": "标签库描述", ".html": "HTML 页面",
    ".htm": "HTML 页面", ".js": "JavaScript", ".css": "样式表",
    ".xml": "XML 配置", ".properties": "属性配置", ".sql": "SQL 脚本",
    ".json": "JSON 数据", ".md": "Markdown", ".jar": "JAR 依赖包",
    ".class": "已编译字节码", ".MF": "清单文件", ".MF".lower(): "清单文件",
    ".png": "图片资源", ".jpg": "图片资源", ".jpeg": "图片资源",
    ".gif": "图片资源", ".dmp": "数据库转储",
    ".db": "Windows 缩略图缓存", ".prefs": "Eclipse 首选项",
    ".container": "Eclipse 容器配置", ".component": "Eclipse 组件配置",
    ".name": "Eclipse 名称配置", ".~sql": "SQL 备份副本",
}

#: 目录名黑名单（大小写不敏感）
SKIP_DIR_NAMES = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".gradle", ".mvn",
    "node_modules", "target", "build", "dist", "bin", "__pycache__",
    "classes",  # WEB-INF/classes 是 src 的编译镜像，重复计数会污染统计
}

#: 已知第三方 Jar 归属表：命名空间前缀 -> (可读名, 该库还需要的配套 jar 关键字)
KNOWN_LIBS = [
    ("net.sf.json", "json-lib", ["ezmorph", "commons-beanutils", "commons-collections",
                                 "commons-lang", "commons-logging"]),
    ("org.apache.commons.beanutils", "commons-beanutils", ["commons-collections", "commons-logging"]),
    ("org.apache.commons.collections", "commons-collections", []),
    ("org.apache.commons.lang", "commons-lang", []),
    ("org.apache.commons.logging", "commons-logging", []),
    ("org.apache.commons.fileupload", "commons-fileupload", ["commons-io"]),
    ("org.apache.struts", "Struts", ["struts"]),
    ("org.springframework", "Spring Framework", []),
    ("org.hibernate", "Hibernate", []),
    ("org.mybatis", "MyBatis", []),
    ("com.ibatis", "iBATIS", []),
    ("com.opensymphony", "OpenSymphony(XWork)", []),
    ("org.apache.struts2", "Struts2", []),
    ("freemarker", "FreeMarker", []),
    ("org.apache.velocity", "Velocity", []),
    ("javax.servlet.jsp.jstl", "JSTL API(容器提供)", []),
    ("org.apache.taglibs", "JSTL Impl", []),
    ("com.fasterxml.jackson", "Jackson", []),
    ("com.google.gson", "Gson", []),
    ("junit", "JUnit", []),
    ("log4j", "Log4j", []),
    ("org.slf4j", "SLF4J", []),
]

#: JDBC 方言线索 -> (数据库名, 驱动 jar 关键字)
JDBC_HINTS = [
    ("oracle", "Oracle", ["ojdbc"]),
    ("mysql", "MySQL", ["mysql-connector"]),
    ("sqlserver", "SQL Server", ["mssql-jdbc", "sqljdbc"]),
    ("postgresql", "PostgreSQL", ["postgresql"]),
    ("db2", "DB2", ["db2jcc"]),
    ("hsql", "HSQLDB", ["hsqldb"]),
    ("derby", "Derby", ["derby"]),
]

# ---------------------------------------------------------------- 正则

RE_PACKAGE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.M)
RE_IMPORT = re.compile(r'^\s*import\s+(?:static\s+)?([\w.*]+)\s*;', re.M)

RE_TYPE = re.compile(
    r'^[ \t]*(?:(?:public|protected|private|abstract|final|static|strictfp)\s+)*'
    r'(class|interface|enum|@interface)\s+(\w+)'
    r'(?:\s*<[^{;]*?>)?'
    r'(?:\s+extends\s+([^{\n]*?))?'
    r'(?:\s+implements\s+([^{\n]*?))?'
    r'\s*\{', re.M)

RE_METHOD = re.compile(
    r'^[ \t]{0,8}(?:@\w+(?:\([^)]*\))?[ \t]*\n[ \t]*)*'
    r'(?!if|for|while|switch|catch|return|new|throw|else|synchronized|do\b)'
    #          接口里的方法常常不带 public：改成可选，否则所有 interface 的方法数都为 0
    r'(?:(?:public|protected|private)\s+)?'
    r'(?:static\s+|final\s+|abstract\s+|synchronized\s+|native\s+)*'
    r'[\w.<>\[\],?\s]+?\s+(\w+)\s*\(\s*([^)]*?)\s*\)'
    #             接口方法以 `;` 结尾，抽象方法同理，此处必须一并接受
    r'(?:\s+throws\s+[\w.,\s]+)?\s*[{;]', re.M)

RE_SQL = re.compile(
    r'"\s*((?:select|insert|update|delete|create|drop|alter|merge)\s[^"]*)"', re.I)
RE_TABLE = re.compile(
    r'\b(?:from|into|update)\s+([`"\w.]+)', re.I)

RE_FORWARD = re.compile(r'getRequestDispatcher\(\s*"([^"]+)"\s*\)')
RE_REDIRECT = re.compile(r'sendRedirect\(\s*"([^"]+)"\s*\)')
RE_ACTION_EQ = re.compile(r'action\.equals\(\s*"([^"]+)"')
RE_ACTION_NULL = re.compile(r'action\s*==\s*null')
RE_ACTION_PARAM = re.compile(r'getParameter\(\s*"action"\s*\)')
RE_PARAM = re.compile(r'getParameter\(\s*"([^"]+)"\s*\)')
RE_REQ_ATTR = re.compile(r'request\.setAttribute\(\s*"([^"]+)"')
RE_SES_ATTR = re.compile(r'session\.setAttribute\(\s*"([^"]+)"')
RE_JNDI = re.compile(r'lookup\(\s*"([^"]+)"')
RE_DRIVER = re.compile(r'Class\.forName\(\s*"([^"]+)"')
RE_JDBC_URL = re.compile(r'jdbc:[\w:@/\-.;?=&]+', re.I)
RE_BIZ_CALL = re.compile(r'\b(\w*[Bb]iz\w*)\s*\.\s*(\w+)\s*\(')
RE_PRINTLN = re.compile(r'System\.(?:out|err)\.print')
RE_TODO = re.compile(r'//\s*(TODO|FIXME|XXX)\b')

# --- JSP 专属
RE_PAGE_DIR = re.compile(r'<%@\s*page\s+([^%]*?)\s*%>', re.S)
RE_TAGLIB = re.compile(r'<%@\s*taglib\s+([^%]*?)\s*%>', re.S)
RE_INCLUDE = re.compile(r'<%@\s*include\s+file\s*=\s*"([^"]+)"')
RE_JSP_INC = re.compile(r'<jsp:include\s+page\s*=\s*"([^"]+)"')
RE_FORM_ACTION = re.compile(r'<form[^>]*?\baction\s*=\s*"([^"]*)"', re.I | re.S)
RE_FORM_METHOD = re.compile(r'<form[^>]*?\bmethod\s*=\s*"([^"]*)"', re.I | re.S)
RE_HREF = re.compile(r'\bhref\s*=\s*"([^"]+)"')
RE_AJAX_URL = re.compile(r'(?:\burl\s*:\s*["\']([^"\']+)|location\.href\s*=\s*["\']([^"\']+)'
                         r'|location\s*=\s*["\']([^"\']+)|\.load\(\s*["\']([^"\']+))')
RE_SCRIPTLET = re.compile(r'<%(?!@|!)')
RE_DECL = re.compile(r'<%!')
RE_EXPR = re.compile(r'<%=')
RE_EL = re.compile(r'\$\{\s*([\w.]+)')
RE_TITLE = re.compile(r'<title>(.*?)</title>', re.I | re.S)
RE_USE_BEAN = re.compile(r'<jsp:useBean')

# 锚定到行首（允许前置 `;`），避免把 `grant create view to cxp;` 误判成建视图
_RE_ANCHOR = r'^\s*(?:;\s*)?'
RE_CREATE_TABLE = re.compile(
    _RE_ANCHOR + r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?([\w.$]+)',
    re.I | re.M)
RE_CREATE_VIEW = re.compile(
    _RE_ANCHOR + r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+[`"\[]?([\w.$]+)',
    re.I | re.M)
RE_CREATE_SEQ = re.compile(
    _RE_ANCHOR + r'CREATE\s+SEQUENCE\s+[`"\[]?([\w.$]+)', re.I | re.M)


# ---------------------------------------------------------------- 读取

def _decode(raw: bytes):
    """按优先级猜测编码，返回 (text, encoding_name)。Windows 上 GBK 老项目很常见。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "unknown(replace)"


def read_text(path: str):
    with open(path, "rb") as f:
        raw = f.read()
    text, enc = _decode(raw)
    return text, enc


# ---------------------------------------------------------------- 遍历

def _norm(rel: str) -> str:
    return rel.replace("\\", "/")


def walk_files(root: str, extra_skip=()):
    """产出 (rel, abs) ，跳过黑名单目录。"""
    skip = {s.lower() for s in SKIP_DIR_NAMES} | {s.lower() for s in extra_skip}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip]
        dirs.sort()
        for fn in sorted(files):
            abs_p = os.path.join(dirpath, fn)
            rel = _norm(os.path.relpath(abs_p, root))
            yield rel, abs_p


# ---------------------------------------------------------------- Java / JSP 解析

def _layer_of(package: str, stem: str):
    """推断 Java 文件的分层角色。"""
    segs = [s.lower() for s in package.split(".")] if package else []
    table = [
        ("controller", "控制层"), ("action", "控制层"), ("servlet", "控制层"),
        ("web", "控制层"), ("biz", "业务层"), ("service", "业务层"),
        ("dao", "持久层"), ("mapper", "持久层"), ("repository", "持久层"),
        ("entity", "实体/POJO"), ("model", "实体/POJO"), ("domain", "实体/POJO"),
        ("pojo", "实体/POJO"), ("vo", "视图对象"), ("filter", "过滤器/拦截器"),
        ("interceptor", "过滤器/拦截器"), ("listener", "监听器"),
        ("util", "工具类"), ("utils", "工具类"), ("common", "工具类"),
        ("exception", "异常定义"), ("config", "配置类"),
    ]
    for key, label in table:
        if key in segs:
            return label
    if stem.endswith("Servlet"):
        return "控制层"
    if stem.endswith(("Biz", "Service")):
        return "业务层"
    if stem.endswith(("Dao", "Mapper")):
        return "持久层"
    if stem.endswith(("Filter", "Interceptor")):
        return "过滤器/拦截器"
    if stem.endswith(("Exception", "Error")):
        return "异常定义"
    return "未分类"


def parse_java(rel: str, text: str, lines: int, enc: str) -> dict:
    imports = RE_IMPORT.findall(text)
    package = RE_PACKAGE.search(text)
    package = package.group(1) if package else ""

    types = []
    for kind, name, ext, impl in RE_TYPE.findall(text):
        types.append({
            "type": name,
            "kind": {"class": "class", "interface": "interface",
                     "enum": "enum", "@interface": "annotation"}.get(kind, kind),
            "extends": (ext or "").strip().replace("\n", " "),
            "implements": (impl or "").strip().replace("\n", " "),
        })
    primary = types[0]["type"] if types else os.path.splitext(os.path.basename(rel))[0]

    methods = []
    for name, args in RE_METHOD.findall(text):
        methods.append({"name": name, "args": args.replace("\n", " ").strip()})

    sqls = [s.replace("\n", " ").strip() for s in RE_SQL.findall(text)]

    return {
        "file": rel,
        "lines": lines,
        "encoding": enc,
        "package": package,
        "primary_type": primary,
        "types": types,
        "imports": imports,
        "methods": methods,
        "method_count": len(methods),
        "layer": _layer_of(package, primary),
        "sqls": sqls,
        "tables": sorted({t.lower().strip('`"') for s in sqls for t in RE_TABLE.findall(s)}),
        "forwards": sorted(set(RE_FORWARD.findall(text))),
        "redirects": sorted(set(RE_REDIRECT.findall(text))),
        "actions": sorted(set(RE_ACTION_EQ.findall(text))),
        "action_null_branch": bool(RE_ACTION_NULL.search(text)),
        "uses_action_param": bool(RE_ACTION_PARAM.search(text)),
        "params": sorted(set(RE_PARAM.findall(text))),
        "request_attrs": sorted(set(RE_REQ_ATTR.findall(text))),
        "session_attrs": sorted(set(RE_SES_ATTR.findall(text))),
        "biz_calls": sorted({".".join(c) for c in RE_BIZ_CALL.findall(text)}),
        "jndi": sorted(set(RE_JNDI.findall(text))),
        "jdbc_url": sorted(set(RE_JDBC_URL.findall(text))),
        "driver": sorted(set(RE_DRIVER.findall(text))),
        "println_count": len(RE_PRINTLN.findall(text)),
        "todo_count": len(RE_TODO.findall(text)),
    }


def parse_jsp(rel: str, text: str, lines: int, enc: str) -> dict:
    page_blobs = RE_PAGE_DIR.findall(text)
    page_attrs = {}
    for chunk in page_blobs:
        for k, v in re.findall(r'(\w+)\s*=\s*"([^"]*)"', chunk):
            page_attrs[k] = v

    page_imports = set()
    for imp in re.findall(r'\bimport\s*=\s*"([^"]+)"', " ".join(page_blobs)):
        for one in imp.replace(",", ";").split(";"):
            one = one.strip()
            if one:
                page_imports.add(one)

    taglib_map = {}
    for chunk in RE_TAGLIB.findall(text):
        m = re.search(r'prefix\s*=\s*"([^"]+)"', chunk)
        u = re.search(r'uri\s*=\s*"([^"]+)"', chunk)
        if m and u:
            taglib_map[m.group(1)] = u.group(1)
        elif u:
            taglib_map[u.group(1).rsplit("/", 1)[-1]] = u.group(1)

    title = RE_TITLE.search(text)
    title = re.sub(r"\s+", " ", title.group(1)).strip() if title else ""

    ajax = []
    for grp in RE_AJAX_URL.findall(text):
        for u in grp:
            if u:
                ajax.append(u)

    return {
        "file": rel,
        "lines": lines,
        "encoding": enc,
        "title": title,
        "page_directives": page_attrs,
        "imports": sorted(page_imports),
        "taglibs": {k: taglib_map[k] for k in sorted(taglib_map)},
        "includes_directive": sorted(set(RE_INCLUDE.findall(text))),
        "includes_runtime": sorted(set(RE_JSP_INC.findall(text))),
        "form_actions": sorted(set(RE_FORM_ACTION.findall(text))),
        "form_methods": sorted({m.upper() for m in RE_FORM_METHOD.findall(text)}),
        "hrefs": sorted(set(RE_HREF.findall(text))),
        "ajax_urls": sorted(set(ajax)),
        "el_expressions": sorted(set(RE_EL.findall(text))),
        "scriptlet_blocks": len(RE_SCRIPTLET.findall(text)),
        "declarations": len(RE_DECL.findall(text)),
        "expressions": len(RE_EXPR.findall(text)),
        "use_bean": bool(RE_USE_BEAN.search(text)),
    }


def parse_webxml(text: str) -> dict:
    """轻量 web.xml（DD）解析：servlet / mapping / filter / listener / welcome。"""

    def blocks(tag):
        # 必须写成 `<tag\s*>`，否则 `<servlet\b[^>]*>` 会把 `<servlet-mapping>`、
        # `<filter-mapping>` 也吞进来，导致 servlet-class 错位。
        return re.findall(rf'<{tag}\s*>(.*?)</{tag}\s*>', text, re.S)

    def inner(body, tag):
        m = re.search(rf'<{tag}\s*>(.*?)</{tag}\s*>', body, re.S)
        return m.group(1).strip() if m else ""

    servlets = []
    for b in blocks("servlet"):
        servlets.append({
            "name": inner(b, "servlet-name"),
            "class": inner(b, "servlet-class"),
            "jsp": inner(b, "jsp-file"),
            "init_params": dict(re.findall(
                r'<param-name>(.*?)</param-name>\s*<param-value>(.*?)</param-value>', b, re.S)),
            "load_on_startup": inner(b, "load-on-startup"),
        })

    mappings = []
    for b in blocks("servlet-mapping"):
        for p in re.findall(r'<url-pattern>(.*?)</url-pattern>', b, re.S):
            mappings.append({"name": inner(b, "servlet-name"), "url_pattern": p.strip()})

    filters = []
    for b in blocks("filter"):
        filters.append({"name": inner(b, "filter-name"), "class": inner(b, "filter-class")})

    filter_maps = []
    for b in blocks("filter-mapping"):
        for p in re.findall(r'<url-pattern>(.*?)</url-pattern>', b, re.S):
            filter_maps.append({"name": inner(b, "filter-name"), "url_pattern": p.strip()})

    listeners = [inner(b, "listener-class") for b in blocks("listener")]

    ver = re.search(r'<web-app[^>]*\bversion\s*=\s*"([^"]+)"', text)
    ns_version = re.search(r'web-app_(\d+_\d+)\.xsd', text)

    return {
        "declared_version": ver.group(1) if ver else "未声明",
        "schema_version": (ns_version.group(1).replace("_", ".") if ns_version else "未推断"),
        "servlets": servlets,
        "servlet_mappings": mappings,
        "filters": filters,
        "filter_mappings": filter_maps,
        "listeners": listeners,
        "welcome_files": re.findall(r'<welcome-file>(.*?)</welcome-file>', text, re.S),
        "context_params": dict(re.findall(
            r'<param-name>(.*?)</param-name>\s*<param-value>(.*?)</param-value>', text, re.S)),
    }


def parse_sql(rel: str, text: str, enc: str) -> dict:
    return {
        "file": rel,
        "encoding": enc,
        "tables": sorted({t.lower() for t in RE_CREATE_TABLE.findall(text)}),
        "views": sorted({t.lower() for t in RE_CREATE_VIEW.findall(text)}),
        "sequences": sorted({t.lower() for t in RE_CREATE_SEQ.findall(text)}),
    }


# ---------------------------------------------------------------- 主扫描

def scan(root: str, max_file_bytes: int = 4 * 1024 * 1024, exclude_dirs=()) -> dict:
    root = os.path.abspath(root)
    files, binaries = [], []
    java, jsp, sqls, xml_props = [], [], [], []
    webxml = None
    jars = []
    jndi_urls, jdbc_urls, drivers = set(), set(), set()
    enc_counter = {}

    for rel, abs_p in walk_files(root, exclude_dirs):
        try:
            st = os.stat(abs_p)
        except OSError:
            continue
        ext = os.path.splitext(rel)[1].lower()
        size = st.st_size

        if ext in TEXT_EXT:
            if size > max_file_bytes:
                binaries.append({"file": rel, "ext": ext, "size": size, "note": "过大跳过"})
                continue
            text, enc = read_text(abs_p)
            lines = text.count("\n") + 1
            enc_counter[enc] = enc_counter.get(enc, 0) + 1
            files.append({"file": rel, "ext": ext, "size": size,
                          "lines": lines, "encoding": enc,
                          "label": EXT_LABEL.get(ext, ext.lstrip("."))})

            if ext == ".java":
                u = parse_java(rel, text, lines, enc)
                u["_body"] = text  # 仅用于同包引用解析，落盘前剥离
                java.append(u)
                jndi_urls |= set(u["jndi"])
                jdbc_urls |= set(u["jdbc_url"])
                drivers |= set(u["driver"])
            elif ext == ".jsp":
                jsp.append(parse_jsp(rel, text, lines, enc))
            elif ext == ".sql":
                sqls.append(parse_sql(rel, text, enc))
            elif ext in (".xml", ".properties"):
                xml_props.append({"file": rel, "ext": ext, "encoding": enc})
                if os.path.basename(rel).lower() == "web.xml":
                    try:
                        webxml = parse_webxml(text)
                        webxml["file"] = rel
                    except Exception as e:  # DD 损坏不应中断全局扫描
                        webxml = {"file": rel, "parse_error": str(e)}
        else:
            note = ""
            if ext == ".class":
                note = "编译产物（src 的镜像，已排除以免重复计数）"
            binaries.append({"file": rel, "ext": ext, "size": size, "note": note})
            if ext == ".jar":
                jars.append({"file": rel, "name": os.path.basename(rel), "size": size})

    # 内部类型索引：简单名 / 全限定名 -> java unit 下标
    idx_simple, idx_fq = {}, {}
    for u in java:
        for t in u["types"]:
            idx_simple.setdefault(t["type"], u["file"])
            if u["package"]:
                idx_fq[f"{u['package']}.{t['type']}"] = u["file"]

    return {
        "root": root,
        "name": os.path.basename(root.rstrip("\\/")) or root,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": files,
        "binaries": binaries,
        "java": java,
        "jsp": jsp,
        "sql": sqls,
        "xml_props": xml_props,
        "webxml": webxml,
        "jars": jars,
        "jndi": sorted(jndi_urls),
        "jdbc_urls": sorted(jdbc_urls),
        "drivers": sorted(drivers),
        "encoding_stats": dict(sorted(enc_counter.items(), key=lambda kv: -kv[1])),
        "_idx_simple": idx_simple,
        "_idx_fq": idx_fq,
    }


def strip_internal(project: dict) -> dict:
    """剥离运行期私有字段（下划线开头），使事实库只含可比对的事实。"""
    for u in project.get("java", []):
        for k in [k for k in u if k.startswith("_")]:
            u.pop(k, None)
    return project


def _clean(unit: dict) -> dict:
    return {k: v for k, v in unit.items() if not k.startswith("_")}


def dump_facts(project: dict, path: str) -> str:
    """落盘机读事实库（去掉私有索引，保证稳定可比）。**不修改内存中的 project**。"""
    proj = {k: v for k, v in project.items() if not k.startswith("_")}
    if "java" in proj:
        proj["java"] = [_clean(u) for u in proj["java"]]
    import lib_md
    return lib_md.write_atomic(path, json.dumps(proj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 派生关系

#: 由平台（JDK / Servlet 容器）提供、无需打进 war 的命名空间
PLATFORM_NS = ("java.", "javax.", "jakarta.", "sun.", "com.sun.",
               "org.w3c.", "org.xml.", "org.ietf.")


def is_platform_ns(ns: str) -> bool:
    return ns.startswith(PLATFORM_NS)


def _third_party_key(imp: str) -> str:
    """把第三方 import 折叠到"库粒度"命名空间：com.xxx.yyy / org.xxx.yyy / net.xxx。"""
    parts = imp.split(".")
    if parts[0] in ("org", "net", "com", "io", "edu"):
        n = 3 if parts[0] == "com" and len(parts) >= 3 else 3
        return ".".join(parts[:n])
    return imp


def external_import_groups(java_units, internal_names):
    """Import 三方/containers 分组：(第三方命名空间 -> 出现次数)。"""
    from collections import Counter
    c = Counter()
    for u in java_units:
        for imp in u["imports"]:
            if imp.endswith(".*"):
                base = imp[:-2]
            else:
                base = imp
            short = base.split(".")[-1]
            if short in internal_names and short != "*":
                continue  # 本工程类
            if is_platform_ns(base):
                continue
            c[_third_party_key(base)] += 1
    return dict(c.most_common())


def internal_edges(java_units):
    """内部依赖边 A -> B（import / extends / implements 解析到本工程类）。"""
    known = set()
    for u in java_units:
        for t in u["types"]:
            known.add(t["type"])

    edges = set()
    for u in java_units:
        src = u["primary_type"]
        deps = set()

        for imp in u["imports"]:
            short = imp.split(".")[-1]
            if short in known and short != src:
                deps.add(short)

        for t in u["types"]:
            for word in re.findall(r"[\w.]+", f"{t['extends']} {t['implements']}"):
                short = word.split(".")[-1]
                if short in known and short != src:
                    deps.add(short)

        # 同包其他类的引用（同包无需 import）
        same_pkg_others = {t["type"] for v in java_units
                           if v["package"] == u["package"] and v["file"] != u["file"]
                           for t in v["types"]}
        for other in same_pkg_others:
            if re.search(rf"\b{re.escape(other)}\b", u["_body"]):
                deps.add(other)

        for d in deps:
            edges.add((src, d))
    return sorted(edges)


def _resolve(ns: str):
    """第三方命名空间 -> (可读库名, 依赖 jar 关键字列表)。"""
    for prefix, name, needs in KNOWN_LIBS:
        if ns == prefix or ns.startswith(prefix + "."):
            return name, needs
    return None, []


def detect_missing_deps(project, ext_groups):
    """对照 WEB-INF/lib 里的 jar，找出"用了但 war 里没打包"的第三方库。"""
    jar_blob = " ".join(j["name"].lower() for j in project["jars"])
    findings = []
    for ns, hits in sorted(ext_groups.items()):
        libname, needs = _resolve(ns)
        if not libname:
            continue
        token = libname.split("(")[0].strip().lower().replace(" ", "-")
        present = token in jar_blob or token.split("-")[0] in jar_blob
        missing_needs = [n for n in needs if n not in jar_blob]
        findings.append({
            "namespace": ns, "lib": libname, "usage": hits,
            "in_war": present, "missing_companions": missing_needs,
        })

    # JDBC 驱动 / 数据源
    all_sql = " ".join(
        s for u in project["java"] for s in u["sqls"]).lower()
    dialects = []
    for kw, dbname, jars_kw in JDBC_HINTS:
        evidence = []
        if f"jdbc:{kw}" in " ".join(project["jdbc_urls"]).lower():
            evidence.append("连接串")
        if kw in all_sql:
            evidence.append("SQL 方言")
        if kw == "oracle" and ("rownum" in all_sql or "to_date(" in all_sql
                               or "nvl(" in all_sql):
            evidence.append("SQL 方言")
        if evidence:
            dialects.append({
                "db": dbname, "evidence": "、".join(sorted(set(evidence))),
                "driver_jars": jars_kw,
                "driver_in_war": any(k in jar_blob for k in jars_kw),
            })
    return findings, dialects
