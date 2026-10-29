"""扩展注册表：组件识别 / 闭源分派 / 模块边界 / 风险规则。

本模块是「老项目改造」知识的**唯一外置入口**。代码里只放通用基线，
项目专属知识一律写在 `<仓库>/config/legacy/*.json`：

    components.json   组件改造台账：谁依赖什么、谁来提供、迁到哪、破坏性多大
    dispatch.json     闭源框架的分派机制（老项目常有自研前端控制器 / 平台路由）
    modules.json      模块边界划分（覆盖脚本默认的「类名后缀」切分）
    risk_rules.json   风险规则（声明式，命中即带证据）

合并语义（ predictable，便于人工维护）：
    * `components` / `risk_rules`：列表项按 `id` 归并 —— 同 id 覆盖，新 id 追加。
    * `dispatch`：同上，按 `id` 归并。
    * `modules`：整体对象覆盖（缺省字段回落到代码默认行为）。
    * `enabled: false` 的条目整体不生效，留作模板占位。

设计约束（与 tools/jlp 一致）：
    * 只用标准库，Python >= 3.8；只读磁盘，不编译、不执行、不联网。
    * 配置缺失 = 该扩展口子不启用；配置**非法** = 直接抛 ValueError（快速失败，不静默降级）。
"""

from __future__ import annotations

import fnmatch
import json
import os
import re

__all__ = [
    "RULES_ENV",
    "DEFAULT_SECTIONS",
    "BUILTIN_COMPONENTS",
    "BUILTIN_RISK_RULES",
    "set_default_dir",
    "default_dir",
    "load",
    "components",
    "app_components",
    "platform_components",
    "component_for_namespace",
    "dispatch_rules",
    "module_rules",
    "risk_rules",
    "detect_components",
    "detect_platform_deps",
    "apply_risk_rules",
    "jar_present",
    "enrich",
]

#: 覆盖默认配置目录的环境变量（无人值守部署时用得上）
RULES_ENV = "JLP_RULES_DIR"

#: 段名 -> (文件名, 段内列表键)；`modules` 是对象，单独处理
DEFAULT_SECTIONS = {
    "components": ("components.json", "components"),
    "dispatch": ("dispatch.json", "rules"),
    "risk_rules": ("risk_rules.json", "rules"),
    "modules": ("modules.json", "modules"),
}

# tools/jlp/lib_registry.py -> tools/jlp -> tools -> <仓库根>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DEFAULT_DIR = os.path.join(_REPO_ROOT, "config", "legacy")
_OVERRIDE_DIR: str | None = None

_CACHE: dict[str, dict] = {}

#: 单条规则扫描正文时的文件数上限，避免大仓被正则拖垮
MAX_SCAN_FILES = 400


# ===========================================================================
# 内置基线：通用第三方 / 平台组件
#
# 字段含义：
#   provided_by  app=打进 war | container=容器提供 | jdk=JDK 提供 | unknown=待人工确认
#   status       active=活跃 | maintenance=仅维护 | EOL=已停更 | unknown=未知（常见于闭源）
#   migration    {target, breaking(low|medium|high), phase(S0..S5)}
#   hint_from    webxml_declared_version / webxml_schema_version —— 平台组件的版本线索来源
# ===========================================================================

BUILTIN_COMPONENTS: list[dict] = [
    # ---- 构建 ----
    dict(id="ant", name="Apache Ant", category="构建", status="maintenance", provided_by="app",
         namespaces=["org.apache.tools.ant"], jar_patterns=["ant"], file_markers=["build.xml"],
         code_patterns=["org\\.apache\\.tools\\.ant"], requires=[],
         migration=dict(target="Maven 3.x 或 Gradle", breaking="medium", phase="S1"),
         notes="构建脚本与 MyEclipse 元数据（.project/.classpath/.mymetadata）需一并迁移"),
    # ---- 视图 / 模板 ----
    dict(id="velocity", name="Apache Velocity", category="视图/模板", status="maintenance",
         provided_by="app", namespaces=["org.apache.velocity"],
         jar_patterns=["velocity"], file_markers=["velocity.properties", "*.vm"],
         code_patterns=["VelocityEngine", "VelocityContext"],
         requires=["commons-collections", "commons-lang"],
         migration=dict(target="Velocity 2.x；或 FreeMarker / Thymeleaf", breaking="medium",
                        phase="S2"),
         notes="1.x 已停更；2.x 包名不变但要求 Java 8+，模板语法基本兼容"),
    # ---- 持久层 ----
    dict(id="ibatis2", name="iBATIS 2.x（SQL Maps）", category="持久层", status="EOL",
         provided_by="app", namespaces=["com.ibatis"], jar_patterns=["ibatis", "sqlmap"],
         file_markers=["sqlmap-config.xml", "*.sqlmap.xml"],
         code_patterns=["SqlMapClient", "SqlMapClientBuilder", "startTransaction"],
         requires=[],
         migration=dict(target="MyBatis 3.5.x", breaking="high", phase="S3"),
         notes="SqlMapClient -> SqlSession；`#v#`/`$v$` 与 `<dynamic>` 需改写为 `#{}`/`<if>`；"
               "手动事务边界改声明式事务"),
    dict(id="hibernate", name="Hibernate", category="持久层", status="maintenance",
         provided_by="app", namespaces=["org.hibernate"], jar_patterns=["hibernate"],
         file_markers=["hibernate.cfg.xml", "*.hbm.xml"], code_patterns=["SessionFactory"],
         requires=[], migration=dict(target="Hibernate 5.x/6.x", breaking="high", phase="S3")),
    # ---- 调度 ----
    dict(id="quartz", name="Quartz Scheduler", category="调度", status="maintenance",
         provided_by="app", namespaces=["org.quartz"], jar_patterns=["quartz"],
         file_markers=["quartz.properties"],
         code_patterns=["SchedulerFactory", "CronTrigger", "JobDetail", "JobBuilder"],
         requires=[],
         migration=dict(target="Quartz 2.x，或 Spring @Scheduled / 分布式调度平台",
                        breaking="high", phase="S3"),
         notes="1.x -> 2.x 是破坏性升级：Scheduler 接口、Trigger/Job 构建器、"
               "Job.execute 异常签名全变"),
    # ---- 文档处理 ----
    dict(id="poi", name="Apache POI", category="文档处理", status="active",
         provided_by="app", namespaces=["org.apache.poi"], jar_patterns=["poi"],
         file_markers=[], code_patterns=["HSSFWorkbook", "XSSFWorkbook", "SXSSFWorkbook"],
         requires=["poi-ooxml", "commons-io"],
         migration=dict(target="POI 5.x（poi / poi-ooxml / poi-scratchpad 成套升级）",
                        breaking="medium", phase="S3"),
         notes="3.x -> 5.x：单元格类型枚举、颜色/字体 API、日期工具均有变更；"
               "大文件导出须改 SXSSF 流式，否则 OOM"),
    # ---- WebService ----
    dict(id="axis", name="Apache Axis 1.x", category="WebService", status="EOL",
         provided_by="app", namespaces=["org.apache.axis"], jar_patterns=["axis"],
         file_markers=["server-config.wsdd", "*.wsdd", "*.wsdl"],
         code_patterns=["org\\.apache\\.axis\\.client\\.Service", "org\\.apache\\.axis\\.client\\.Call"],
         requires=["jaxrpc", "saaj", "commons-discovery", "wsdl4j"],
         migration=dict(target="JAX-WS（Metro）/ Apache CXF，或改 REST",
                        breaking="high", phase="S3"),
         notes="1.x 已停止维护；生成 stub 需重新生成，WSDL 契约须先冻结做回归基线"),
    dict(id="axis2", name="Apache Axis2", category="WebService", status="maintenance",
         provided_by="app", namespaces=["org.apache.axis2"], jar_patterns=["axis2"],
         file_markers=["services.xml", "*.aar"], code_patterns=["org\\.apache\\.axis2"],
         requires=[], migration=dict(target="Apache CXF / JAX-WS", breaking="high", phase="S3")),
    # ---- XML ----
    dict(id="dom4j", name="dom4j", category="XML 处理", status="maintenance",
         provided_by="app", namespaces=["org.dom4j"], jar_patterns=["dom4j"],
         file_markers=[], code_patterns=["SAXReader", "DocumentHelper", "OutputFormat"],
         requires=[],
         migration=dict(target="dom4j 2.1.x（或 JDK StAX / JAXB）", breaking="low", phase="S2"),
         notes="1.6.1 存在 XXE 相关 CVE；升级同时须关闭外部实体解析"),
    # ---- Commons 系列 ----
    dict(id="commons-beanutils", name="Commons BeanUtils", category="工具库", status="maintenance",
         provided_by="app", namespaces=["org.apache.commons.beanutils"],
         jar_patterns=["commons-beanutils"], code_patterns=["BeanUtils.copyProperties"],
         requires=["commons-collections", "commons-logging"],
         migration=dict(target="1.9.4+；长期看改为显式 getter/setter 或 Spring BeanWrapper",
                        breaking="low", phase="S2"),
         notes="1.8.x 有 ClassLoader 相关 CVE；属性拷贝是隐式依赖，改造时最易漏测"),
    dict(id="commons-collections", name="Commons Collections", category="工具库",
         status="maintenance", provided_by="app",
         namespaces=["org.apache.commons.collections"], jar_patterns=["commons-collections"],
         code_patterns=["CollectionUtils", "InvokerTransformer"], requires=[],
         migration=dict(target="commons-collections4（`org.apache.commons.collections4`）",
                        breaking="medium", phase="S4"),
         notes="包名带版本号是破坏性变更；3.1 的 InvokerTransformer 是反序列化利用链常见环节"),
    dict(id="commons-dbcp", name="Commons DBCP", category="数据源", status="maintenance",
         provided_by="app", namespaces=["org.apache.commons.dbcp"], jar_patterns=["commons-dbcp"],
         code_patterns=["BasicDataSource"], requires=["commons-pool"],
         migration=dict(target="commons-dbcp2（或 HikariCP / 容器 JNDI 数据源）",
                        breaking="medium", phase="S3"),
         notes="2.x 包名加 `2`，且 maxActive/maxWait 改名为 maxTotal/maxWaitMillis；"
               "配置漏改会静默回到默认值"),
    dict(id="commons-fileupload", name="Commons FileUpload", category="工具库",
         status="maintenance", provided_by="app",
         namespaces=["org.apache.commons.fileupload"], jar_patterns=["commons-fileupload"],
         code_patterns=["ServletFileUpload", "DiskFileItemFactory"], requires=["commons-io"],
         migration=dict(target="1.5（修复 DoS CVE）；Servlet 3.0+ 可改 @MultipartConfig",
                        breaking="medium", phase="S2"),
         notes="上传入口是安全敏感面，改造须回归：大小限制、临时目录清理、文件名过滤"),
    dict(id="commons-io", name="Commons IO", category="工具库", status="active", provided_by="app",
         namespaces=["org.apache.commons.io"], jar_patterns=["commons-io"],
         code_patterns=["IOUtils", "FileUtils"], requires=[],
         migration=dict(target="2.x（Java 8+）", breaking="low", phase="S2")),
    dict(id="commons-logging", name="Commons Logging", category="日志", status="maintenance",
         provided_by="app", namespaces=["org.apache.commons.logging"],
         jar_patterns=["commons-logging"], code_patterns=["LogFactory.getLog"], requires=[],
         migration=dict(target="SLF4J + jcl-over-slf4j（统一日志出口）", breaking="low",
                        phase="S2"),
         notes="老工程常见『多套日志并存』：JCL + Log4j 1.x + 自写日志，改造第一步是统一出口"),
    dict(id="commons-lang", name="Commons Lang", category="工具库", status="active",
         provided_by="app", namespaces=["org.apache.commons.lang"], jar_patterns=["commons-lang"],
         code_patterns=["StringUtils", "DateUtils"], requires=[],
         migration=dict(target="commons-lang3（`org.apache.commons.lang3`）", breaking="low",
                        phase="S2")),
    dict(id="log4j1", name="Log4j 1.x", category="日志", status="EOL", provided_by="app",
         namespaces=["org.apache.log4j"], jar_patterns=["log4j"], file_markers=["log4j.properties"],
         code_patterns=["Logger.getLogger", "PropertyConfigurator"], requires=[],
         migration=dict(target="Log4j 2.x / Logback（经 SLF4J）", breaking="medium", phase="S2"),
         notes="1.x 已 EOL 且有 CVE；配置文件语法不兼容，须重写"),
    # ---- 平台 / 容器 / JDK 提供（不进 war，单独一条检测通道） ----
    dict(id="servlet-api", name="Servlet API（javax.servlet）", category="平台 API", status="EOL",
         provided_by="container", namespaces=["javax.servlet", "javax.servlet.http"],
         jar_patterns=["servlet-api"], file_markers=["web.xml"],
         code_patterns=["HttpServlet", "HttpServletRequest", "Filter", "ServletContextListener"],
         hint_from="webxml_declared_version",
         migration=dict(target="jakarta.servlet 6.x（Tomcat 10.1+）", breaking="high", phase="S4"),
         notes="javax -> jakarta 是一次性全量改名，决定其余组件的可选版本轨道，必须最先定档"),
    dict(id="jsp-api", name="JSP API（javax.servlet.jsp）", category="平台 API", status="EOL",
         provided_by="container", namespaces=["javax.servlet.jsp"], jar_patterns=["jsp-api"],
         code_patterns=["JspWriter", "PageContext"], hint_from="webxml_schema_version",
         migration=dict(target="jakarta.servlet.jsp 3.x", breaking="high", phase="S4")),
    dict(id="jce-sunjce", name="JCE Provider（Sun / SunJCE）", category="安全/平台 API",
         status="maintenance", provided_by="jdk",
         namespaces=["javax.crypto", "javax.crypto.spec", "com.sun.crypto"],
         jar_patterns=["sunjce_provider"],
         code_patterns=["Security.addProvider", "SunJCE", "Cipher.getInstance",
                        "MessageDigest.getInstance", "KeyGenerator.getInstance"],
         migration=dict(target="标准 JCA 调用（不写死 Provider）；需要国密/特殊算法再引 BouncyCastle",
                        breaking="medium", phase="S3"),
         notes="硬编码 `new SunJCE()` / `sun.misc.*` 属于 JDK 内部 API，"
               "JDK 9+ 模块化后不可移植，且弱算法（MD5/DES/RC4/SHA1）通常不合合规要求"),
]


# ===========================================================================
# 内置风险规则（通用；项目专属规则写进 risk_rules.json）
#
# scope 四类探测器，命中任一即算命中：
#   namespaces    源码 import 前缀
#   code_patterns 源码正文正则（按 file_exts 限定范围，默认 .java）
#   jar_patterns  war 内 jar 文件名关键字
#   file_markers  文件名（支持 `*vm` 这类通配符）
# ===========================================================================

BUILTIN_RISK_RULES: list[dict] = [
    dict(id="jdk-internal-api", level="高",
         title="依赖 JDK 内部 API（sun.* / com.sun.*）",
         detail="`sun.misc.BASE64Encoder`、`com.sun.crypto.provider.SunJCE` 等属于 JDK 内部实现，"
                "JDK 9+ 模块化封装后不可移植，升级 JDK 会直接编译失败或运行期 NoClassDefFoundError。",
         scope=dict(namespaces=["sun.misc", "sun.security", "com.sun.crypto"],
                    code_patterns=["sun\\.misc\\.BASE64", "new\\s+SunJCE",
                                   "com\\.sun\\.crypto\\.provider"],
                    file_exts=[".java"]),
         evidence_limit=15, tags=["JDK 升级", "兼容性"]),
    dict(id="hardcoded-crypto-provider", level="中",
         title="硬编码 JCE Provider",
         detail="代码里 `Security.addProvider(new SunJCE())` 或直接 `new SunJCE()` 写死了 Provider，"
                "换 JDK / 换厂商 / 上国产密码套件时都要改代码，且无法集中管控算法白名单。",
         scope=dict(code_patterns=["Security\\.addProvider", "new\\s+com\\.sun\\.crypto"],
                    file_exts=[".java"]),
         evidence_limit=15, tags=["安全", "可移植性"]),
    dict(id="weak-crypto-algorithm", level="高",
         title="使用弱哈希 / 弱对称算法",
         detail="MD5、SHA-1、DES、3DES、RC4 已不满足现行合规要求；口令存储与报文签名场景须换 "
                "SHA-256 系列 / AES-GCM / SM3 / SM4，并补盐或改用 KDF。",
         scope=dict(code_patterns=["MessageDigest\\.getInstance\\(\\s*\"(MD5|SHA-1|SHA1)\"",
                                   "Cipher\\.getInstance\\(\\s*\"[^\"]*(DES|DESede|RC4|RC2|Blowfish)",
                                   "KeyGenerator\\.getInstance\\(\\s*\"(DES|DESede|RC4)\""],
                    file_exts=[".java"]),
         evidence_limit=15, tags=["安全", "合规"]),
    dict(id="javax-to-jakarta", level="中",
         title="javax.* 平台 API 需迁移到 jakarta.*",
         detail="Jakarta EE 9 起 `javax.servlet/jsp/jstl/el` 等包名整体改为 `jakarta.*`，"
                "是一次性全量改名，必须与其他组件的版本选型同步定档。",
         scope=dict(namespaces=["javax.servlet", "javax.servlet.jsp", "javax.el"],
                    file_exts=[".java"]),
         evidence_limit=10, tags=["平台迁移"]),
]


# ===========================================================================
# 加载
# ===========================================================================

def default_dir() -> str:
    """当前生效的配置目录（可用 `set_default_dir` 或环境变量覆盖）。"""
    return _OVERRIDE_DIR or os.environ.get(RULES_ENV) or _DEFAULT_DIR


def set_default_dir(path: str | None) -> None:
    """覆盖默认配置目录（CLI `--rules` 用）。传 None 恢复仓库默认。"""
    global _OVERRIDE_DIR
    _OVERRIDE_DIR = str(path) if path else None
    _CACHE.clear()


def _resolve_dir(rules_dir: str | None) -> str:
    return str(rules_dir) if rules_dir else default_dir()


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"扩展配置不是合法 JSON：{path}（{exc}）") from exc
    except OSError as exc:
        raise ValueError(f"扩展配置读取失败：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"扩展配置顶层必须是对象：{path}")
    return data


def _section(data: dict, key: str, path: str) -> list | dict | None:
    """取段内数据。`modules` 段允许直接写在顶层（省一层嵌套）。"""
    if key == "modules":
        value = data.get(key)
        if isinstance(value, dict):
            return value
        if value is not None:
            raise ValueError(f"{path} 的 `modules` 必须是对象")
        return {k: v for k, v in data.items()
                if not str(k).startswith("_") and k != "version"}
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{path} 的 `{key}` 必须是数组")
    return value


def _require_id(entry: dict, path: str, index: int) -> str:
    if not isinstance(entry, dict):
        raise ValueError(f"{path} 第 {index} 项必须是对象")
    eid = entry.get("id")
    if not isinstance(eid, str) or not eid.strip():
        raise ValueError(f"{path} 第 {index} 项缺少字符串字段 `id`")
    return eid


def _merge_by_id(builtin: list[dict], override: list | None, path: str) -> list[dict]:
    """同 id 覆盖（整体替换），新 id 追加；`enabled: false` 的条目整体丢弃。"""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for src in (builtin, override or []):
        for i, entry in enumerate(src):
            eid = _require_id(entry, path, i)
            if eid not in merged:
                order.append(eid)
            merged[eid] = entry
    out = []
    for eid in order:
        entry = merged[eid]
        if entry.get("enabled", True):
            out.append(entry)
    return out


def load(rules_dir: str | None = None) -> dict:
    """加载并合并四份扩展配置。目录不存在时返回「只有内置基线」的注册表。"""
    directory = _resolve_dir(rules_dir)
    key = os.path.abspath(directory)
    if key in _CACHE:
        return _CACHE[key]

    reg: dict = {
        "dir": directory,
        "exists": os.path.isdir(directory),
        "components": list(BUILTIN_COMPONENTS),
        "dispatch": [],
        "modules": {},
        "risk_rules": list(BUILTIN_RISK_RULES),
    }

    if os.path.isdir(directory):
        for name, (filename, key_in_file) in DEFAULT_SECTIONS.items():
            path = os.path.join(directory, filename)
            if not os.path.exists(path):
                continue
            data = _read_json(path)
            section = _section(data, key_in_file, path)
            if name == "modules":
                reg["modules"] = dict(section or {})
            elif name == "components":
                reg["components"] = _merge_by_id(BUILTIN_COMPONENTS, section, path)
            elif name == "risk_rules":
                reg["risk_rules"] = _merge_by_id(BUILTIN_RISK_RULES, section, path)
            else:
                reg["dispatch"] = _merge_by_id([], section, path)

    _validate_modules(reg["modules"], os.path.join(directory, "modules.json"))
    _CACHE[key] = reg
    return reg


def _validate_modules(mods: dict, path: str) -> None:
    if not isinstance(mods, dict):
        raise ValueError(f"{path} 的 `modules` 必须是对象")
    for key in ("seed_suffixes", "exclude_types"):
        value = mods.get(key)
        if value is not None and not isinstance(value, list):
            raise ValueError(f"{path} 的 `{key}` 必须是数组")
    for key in ("domain_aliases", "package_modules"):
        value = mods.get(key)
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"{path} 的 `{key}` 必须是对象")
    merge = mods.get("force_merge")
    if merge is not None:
        if not isinstance(merge, list) or any(
            not isinstance(pair, list) or len(pair) != 2 for pair in merge):
            raise ValueError(f"{path} 的 `force_merge` 必须是二元组数组")


# ===========================================================================
# 查询
# ===========================================================================

def components(reg: dict | None = None) -> list[dict]:
    return (reg or load())["components"]


def app_components(reg: dict | None = None) -> list[dict]:
    """随应用打包的组件（第三方库 / 闭源 SDK）。"""
    return [c for c in components(reg) if c.get("provided_by", "app") == "app"]


def platform_components(reg: dict | None = None) -> list[dict]:
    """由容器 / JDK / 未知外部提供的组件（不打进 war，漏了上线才炸）。"""
    return [c for c in components(reg)
            if c.get("provided_by", "app") in ("container", "jdk", "unknown")]


def _ns_match(ns: str, prefixes) -> bool:
    for p in prefixes or ():
        if ns == p or ns.startswith(p + "."):
            return True
    return False


def component_for_namespace(reg: dict | None, ns: str) -> dict | None:
    """按 import 命名空间反查组件（只查 app 组件，平台组件走另一条通道）。"""
    for comp in app_components(reg):
        if _ns_match(ns, comp.get("namespaces")):
            return comp
    return None


def dispatch_rules(reg: dict | None = None) -> list[dict]:
    return (reg or load())["dispatch"]


def module_rules(reg: dict | None = None) -> dict:
    return (reg or load())["modules"]


def risk_rules(reg: dict | None = None) -> list[dict]:
    return (reg or load())["risk_rules"]


# ===========================================================================
# 探测：命中证据
# ===========================================================================

def _jar_blob(project: dict) -> str:
    return " ".join(str(j.get("name", "")).lower() for j in (project.get("jars") or []))


def _import_hits(project: dict, namespaces) -> dict[str, int]:
    hits: dict[str, int] = {}
    if not namespaces:
        return hits
    for unit in project.get("java") or []:
        for imp in unit.get("imports") or []:
            base = imp[:-2] if imp.endswith(".*") else imp
            for ns in namespaces:
                if base == ns or base.startswith(ns + "."):
                    key = f"import {ns}"
                    hits[key] = hits.get(key, 0) + 1
                    break
    return hits


def _iter_texts(project: dict, exts):
    """按扩展名产出 (相对路径, 正文)。`.java` 直接用内存里的 `_body`，其他按编码降级读盘。"""
    wanted = {str(e).lower() for e in (exts or [".java"])}
    if ".java" in wanted:
        for unit in project.get("java") or []:
            body = unit.get("_body")
            if body:
                yield unit.get("file", ""), body
    others = wanted - {".java"}
    if not others:
        return
    from lib_scan import read_text  # 延迟导入，避免与 lib_scan 形成循环依赖

    root = project.get("root", "")
    count = 0
    for f in project.get("files") or []:
        if count >= MAX_SCAN_FILES:
            return
        ext = str(f.get("ext", "")).lower()
        if ext not in others:
            continue
        try:
            text, _enc = read_text(os.path.join(root, f["file"]))
        except (OSError, KeyError):
            continue
        count += 1
        yield f["file"], text


def _code_hits(project: dict, patterns, exts) -> dict[str, int]:
    hits: dict[str, int] = {}
    if not patterns:
        return hits
    compiled = []
    for p in patterns:
        try:
            compiled.append((p, re.compile(p)))
        except re.error:
            continue
    for rel, text in _iter_texts(project, exts):
        for raw, rx in compiled:
            n = len(rx.findall(text))
            if n:
                m = rx.search(text)
                sample = m.group(0).strip()[:40] if m else raw
                hits[f"`{rel}` × {n}（{sample}）"] = n
    return hits


def _file_marker_hits(project: dict, markers) -> list[str]:
    if not markers:
        return []
    found = []
    for f in project.get("files") or []:
        rel = f.get("file", "")
        base = os.path.basename(rel).lower()
        for m in markers:
            pat = str(m).lower()
            if "*" in pat:
                if fnmatch.fnmatch(base, pat):
                    found.append(f"`{rel}`")
                    break
            elif pat in base or pat in rel.lower():
                found.append(f"`{rel}`")
                break
    return sorted(set(found))


def jar_present(component: dict, jar_blob: str, fallback_name: str = "") -> bool:
    """判断组件是否已打进 war：优先用 `jar_patterns`，回落老的名称关键字启发式。"""
    for pat in component.get("jar_patterns") or []:
        if str(pat).lower() in jar_blob:
            return True
    if not fallback_name:
        return False
    token = fallback_name.split("(")[0].strip().lower().replace(" ", "-")
    return token in jar_blob or token.split("-")[0] in jar_blob


# ===========================================================================
# 探测：组件台账与平台依赖
# ===========================================================================

def detect_components(project: dict, reg: dict | None = None) -> list[dict]:
    """第三方 / 闭源组件改造台账：只列 provided_by=app 且确有使用证据的组件。"""
    reg = reg or load()
    blob = _jar_blob(project)
    rows: list[dict] = []
    for comp in app_components(reg):
        import_hits = _import_hits(project, comp.get("namespaces"))
        code_hits = _code_hits(project, comp.get("code_patterns"), [".java", ".jsp"])
        files = _file_marker_hits(project, comp.get("file_markers"))
        usage = sum(import_hits.values()) + len(code_hits) + len(files)
        if not usage:
            continue
        jars = sorted({j.get("name") for j in (project.get("jars") or [])
                       for p in (comp.get("jar_patterns") or [])
                       if str(p).lower() in str(j.get("name", "")).lower()})
        missing = [n for n in (comp.get("requires") or []) if str(n).lower() not in blob]
        migration = comp.get("migration") or {}
        rows.append({
            "id": comp["id"], "name": comp.get("name", comp["id"]),
            "category": comp.get("category", ""), "status": comp.get("status", "unknown"),
            "usage": usage, "jars": jars, "in_war": bool(jars),
            "missing_companions": missing,
            "migration_target": migration.get("target", ""),
            "breaking": migration.get("breaking", ""),
            "phase": migration.get("phase", ""),
            "notes": comp.get("notes", ""),
            "evidence": (sorted(import_hits)[:5] + sorted(code_hits)[:5] + files[:5]),
        })
    rows.sort(key=lambda r: (-r["usage"], r["id"]))
    return rows


def _version_hint(component: dict, project: dict) -> str:
    src = component.get("hint_from")
    webxml = project.get("webxml") or {}
    if src == "webxml_declared_version":
        return str(webxml.get("declared_version") or "")
    if src == "webxml_schema_version":
        return str(webxml.get("schema_version") or "")
    return str(component.get("version_hint") or "")


def detect_platform_deps(project: dict, reg: dict | None = None) -> list[dict]:
    """平台 / 容器 / JDK 提供的依赖。

    这些命名空间（`javax.*` / `sun.*`）在 `lib_scan.PLATFORM_NS` 里被过滤掉了，
    不会出现在「第三方依赖」表里——但升级容器或 JDK 时，恰恰是它们最先炸。
    """
    reg = reg or load()
    rows: list[dict] = []
    for comp in platform_components(reg):
        import_hits = _import_hits(project, comp.get("namespaces"))
        code_hits = _code_hits(project, comp.get("code_patterns"), [".java", ".jsp"])
        files = _file_marker_hits(project, comp.get("file_markers"))
        evidence = sorted(import_hits)[:5] + sorted(code_hits)[:5] + files[:5]
        if not evidence:
            continue
        migration = comp.get("migration") or {}
        rows.append({
            "id": comp["id"], "name": comp.get("name", comp["id"]),
            "provided_by": comp.get("provided_by", "unknown"),
            "status": comp.get("status", "unknown"),
            "usage": sum(import_hits.values()) + len(code_hits),
            "version_hint": _version_hint(comp, project),
            "migration_target": migration.get("target", ""),
            "phase": migration.get("phase", ""),
            "notes": comp.get("notes", ""),
            "evidence": evidence,
        })
    rows.sort(key=lambda r: (-r["usage"], r["id"]))
    return rows


# ===========================================================================
# 风险规则
# ===========================================================================

def _rule_evidence(project: dict, rule: dict) -> list[str]:
    scope = rule.get("scope") or {}
    evidence: list[str] = []
    evidence += sorted(_import_hits(project, scope.get("namespaces")))
    evidence += sorted(_code_hits(project, scope.get("code_patterns"),
                                  scope.get("file_exts") or [".java"]))
    evidence += _file_marker_hits(project, scope.get("file_markers"))
    blob = _jar_blob(project)
    for pat in scope.get("jar_patterns") or []:
        hit = [str(j.get("name")) for j in (project.get("jars") or [])
               if str(pat).lower() in str(j.get("name", "")).lower()]
        if hit:
            evidence.append(f"jar: {', '.join(sorted(set(hit))[:3])}")
    return evidence


def apply_risk_rules(project: dict, reg: dict | None = None) -> list[dict]:
    """跑声明式风险规则 + 组件状态派生规则，命中即带证据。"""
    reg = reg or load()
    out: list[dict] = []

    for rule in risk_rules(reg):
        if not rule.get("enabled", True):
            continue
        evidence = _rule_evidence(project, rule)
        if len(evidence) < int(rule.get("min_hits", 1) or 1):
            continue
        limit = int(rule.get("evidence_limit", 15) or 15)
        out.append({
            "level": rule.get("level", "中"),
            "title": rule.get("title") or rule.get("id"),
            "detail": rule.get("detail", ""),
            "evidence": evidence[:limit],
            "rule_id": rule.get("id"),
        })

    # 派生规则：仍在使用的停更 / 状态未知组件（闭源组件的 status 常是 unknown）
    eol = [r for r in detect_components(project, reg)
           if r.get("status") in ("EOL", "unknown")]
    if eol:
        names = [f"`{r['name']}`（{r['status']}）" for r in eol]
        out.append({
            "level": "中",
            "title": "仍在使用已停更或状态未知的组件",
            "detail": "这些组件无安全更新渠道；闭源组件须先确认厂商支持状态与替代方案，"
                      "再决定是升级、隔离还是替换。",
            "evidence": names[:15],
            "rule_id": "component-status",
        })
    return out


# ===========================================================================
# 装配
# ===========================================================================

def enrich(project: dict, reg: dict | None = None) -> dict:
    """把组件台账与平台依赖挂到 project 上，使其进入 `facts.json` 与各阶段产物。"""
    reg = reg or load()
    project["components"] = detect_components(project, reg)
    project["platform_deps"] = detect_platform_deps(project, reg)
    project["rules_dir"] = reg.get("dir", "")
    return project
