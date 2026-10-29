"""扩展注册表：组件识别 / 闭源分派 / 模块边界 / 风险规则。

用合成的「老项目」语料离线验证：
  * 第三方 / 闭源组件台账（含 war 内缺失与配套 jar 缺失）
  * 平台 / 容器 / JDK 提供的依赖（Servlet API / JCE，升级时最易漏）
  * 声明式风险规则命中与证据
  * 四个扩展口子的合并语义（同 id 覆盖、新 id 追加、enabled=false 忽略、非法配置快速失败）
"""

from __future__ import annotations

import json
import os

import pytest

from pipeline.scan import (
    component_ledger,
    load_jlp,
    load_project_facts,
    load_registry,
    platform_deps,
)

JAVA_FILES = {
    # 订单模块：完整纵向切片（Servlet -> Biz -> Dao）
    "src/com/demo/web/OrderServlet.java": (
        "package com.demo.web;\n"
        "import javax.servlet.http.HttpServlet;\n"
        "public class OrderServlet extends HttpServlet {\n"
        "  public void service(String action) {\n"
        "    if (action.equals(\"list\")) { request.getRequestDispatcher(\"orderList.jsp\").forward(request, response); }\n"
        "  }\n"
        "}\n"
    ),
    "src/com/demo/biz/OrderBiz.java": (
        "package com.demo.biz;\n"
        "public interface OrderBiz { void list(); void add(); }\n"
    ),
    "src/com/demo/biz/OrderBizImpl.java": (
        "package com.demo.biz;\n"
        "import com.demo.dao.OrderDao;\n"
        "public class OrderBizImpl implements OrderBiz {\n"
        "  public void list() {} public void add() {}\n"
        "}\n"
    ),
    "src/com/demo/dao/OrderDao.java": (
        "package com.demo.dao;\n"
        "import com.ibatis.sqlmap.client.SqlMapClient;\n"
        "import org.dom4j.SAXReader;\n"
        "public class OrderDao {\n"
        "  private SqlMapClient client;\n"
        "  public void add() { String sql = \"insert into t_order (id) values (?)\"; }\n"
        "  public void list() { String sql = \"select * from t_order where name like ?\"; }\n"
        "}\n"
    ),
    # 上传模块
    "src/com/demo/web/UploadServlet.java": (
        "package com.demo.web;\n"
        "import javax.servlet.http.HttpServlet;\n"
        "import org.apache.commons.fileupload.servlet.ServletFileUpload;\n"
        "public class UploadServlet extends HttpServlet {\n"
        "  private ServletFileUpload upload;\n"
        "  public void service(String action) {\n"
        "    if (action.equals(\"save\")) { request.getRequestDispatcher(\"uploadForm.jsp\").forward(request, response); }\n"
        "  }\n"
        "}\n"
    ),
    "src/com/demo/biz/UploadBiz.java": (
        "package com.demo.biz;\n"
        "public interface UploadBiz { void save(); }\n"
    ),
    "src/com/demo/biz/UploadBizImpl.java": (
        "package com.demo.biz;\n"
        "import com.demo.dao.UploadDao;\n"
        "public class UploadBizImpl implements UploadBiz { public void save() {} }\n"
    ),
    "src/com/demo/dao/UploadDao.java": (
        "package com.demo.dao;\n"
        "public class UploadDao { public void save() { String sql = \"update t_file set name = ?\"; } }\n"
    ),
    # 各类组件依赖
    "src/com/demo/job/SyncJob.java": (
        "package com.demo.job;\n"
        "import org.quartz.Scheduler;\n"
        "import java.security.MessageDigest;\n"
        "public class SyncJob {\n"
        "  private Scheduler scheduler;\n"
        "  public void run() throws Exception {\n"
        "    MessageDigest.getInstance(\"MD5\");\n"
        "    sun.misc.BASE64Encoder enc = new sun.misc.BASE64Encoder();\n"
        "  }\n"
        "}\n"
    ),
    "src/com/demo/util/ExcelUtil.java": (
        "package com.demo.util;\n"
        "import org.apache.poi.hssf.usermodel.HSSFWorkbook;\n"
        "public class ExcelUtil { public void export() { new HSSFWorkbook(); } }\n"
    ),
    "src/com/demo/ws/BankClient.java": (
        "package com.demo.ws;\n"
        "import org.apache.axis.client.Service;\n"
        "public class BankClient { private Service service; }\n"
    ),
    "src/com/demo/web/BaseServlet.java": (
        "package com.demo.web;\n"
        "import javax.servlet.http.HttpServlet;\n"
        "import javax.crypto.Cipher;\n"
        "public class BaseServlet extends HttpServlet {\n"
        "  public void init() {\n"
        "    java.security.Security.addProvider(new com.sun.crypto.provider.SunJCE());\n"
        "    try { Cipher.getInstance(\"DES\"); } catch (Exception e) {}\n"
        "  }\n"
        "}\n"
    ),
    "src/com/demo/db/Pool.java": (
        "package com.demo.db;\n"
        "import org.apache.commons.dbcp.BasicDataSource;\n"
        "public class Pool { private BasicDataSource ds; }\n"
    ),
    "src/com/demo/view/MailRender.java": (
        "package com.demo.view;\n"
        "import org.apache.velocity.VelocityContext;\n"
        "public class MailRender { private VelocityContext ctx; }\n"
    ),
    "src/com/demo/vendor/VendorClient.java": (
        "package com.demo.vendor;\n"
        "import com.vendor.sdk.Client;\n"
        "public class VendorClient { private Client client; }\n"
    ),
}

#: 页面与后端靠表单 action 建立归属
JSP_FILES = {
    "WebRoot/orderList.jsp": "<form action=\"Order.do?action=list\" method=\"post\"></form>\n",
    "WebRoot/uploadForm.jsp": "<form action=\"Upload.do?action=save\" method=\"post\"></form>\n",
}

JARS = ["ibatis-2.3.4.jar", "quartz-1.8.6.jar", "poi-3.9.jar", "dom4j-1.6.1.jar"]

WEB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<web-app xmlns="http://java.sun.com/xml/ns/javaee" version="2.5">
  <servlet>
    <servlet-name>OrderServlet</servlet-name>
    <servlet-class>com.demo.web.OrderServlet</servlet-class>
  </servlet>
  <servlet-mapping>
    <servlet-name>OrderServlet</servlet-name>
    <url-pattern>/Order.do</url-pattern>
  </servlet-mapping>
  <servlet>
    <servlet-name>UploadServlet</servlet-name>
    <servlet-class>com.demo.web.UploadServlet</servlet-class>
  </servlet>
  <servlet-mapping>
    <servlet-name>UploadServlet</servlet-name>
    <url-pattern>/Upload.do</url-pattern>
  </servlet-mapping>
  <servlet>
    <servlet-name>BaseServlet</servlet-name>
    <servlet-class>com.demo.web.BaseServlet</servlet-class>
  </servlet>
  <servlet-mapping>
    <servlet-name>BaseServlet</servlet-name>
    <url-pattern>*.do</url-pattern>
  </servlet-mapping>
</web-app>
"""


@pytest.fixture(scope="module")
def legacy_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("legacy")
    for rel, body in JAVA_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (root / "build.xml").write_text("<project name=\"old\" default=\"war\"/>\n", encoding="utf-8")
    (root / "src" / "sqlmap-config.xml").write_text("<sqlMapConfig/>\n", encoding="utf-8")
    (root / "src" / "mail.vm").write_text("hello $name\n", encoding="utf-8")
    lib = root / "WebRoot" / "WEB-INF" / "lib"
    lib.mkdir(parents=True)
    for name in JARS:
        (lib / name).write_bytes(b"")
    (root / "WebRoot" / "WEB-INF" / "web.xml").write_text(WEB_XML, encoding="utf-8")
    for rel, body in JSP_FILES.items():
        (root / rel).write_text(body, encoding="utf-8")
    return str(root)


@pytest.fixture(scope="module")
def project(legacy_root):
    lib_scan, _ = load_jlp()
    return lib_scan.scan(legacy_root)


def _by_id(rows):
    return {r["id"]: r for r in rows}


# --------------------------------------------------------------------------- 组件台账

def test_components_detected(project):
    rows = _by_id(load_registry().detect_components(project))
    for cid in ("ibatis2", "quartz", "poi", "dom4j", "axis", "velocity",
                "commons-dbcp", "commons-fileupload"):
        assert cid in rows, f"未识别出组件 {cid}，实际 {sorted(rows)}"

    # iBATIS 已停更、迁移到 MyBatis，属 S3 阶段的高破坏性替换
    assert rows["ibatis2"]["status"] == "EOL"
    assert "MyBatis" in rows["ibatis2"]["migration_target"]
    assert rows["ibatis2"]["phase"] == "S3"

    # war 里打了 ibatis / quartz / poi / dom4j，但没有 axis
    assert rows["ibatis2"]["in_war"] is True
    assert rows["axis"]["in_war"] is False
    # dbcp 需要 commons-pool、fileupload 需要 commons-io，都没打进 war
    assert "commons-pool" in rows["commons-dbcp"]["missing_companions"]
    assert "commons-io" in rows["commons-fileupload"]["missing_companions"]


def test_ant_detected_by_build_script(project):
    rows = _by_id(load_registry().detect_components(project))
    # Ant 通常没有 import，靠 build.xml 这个「物证」识别
    assert "ant" in rows
    assert any("build.xml" in e for e in rows["ant"]["evidence"])


def test_platform_deps_detected(project):
    rows = _by_id(load_registry().detect_platform_deps(project))
    assert "servlet-api" in rows
    assert rows["servlet-api"]["provided_by"] == "container"
    assert rows["servlet-api"]["version_hint"] == "2.5"   # 来自 web.xml 声明
    assert "jce-sunjce" in rows
    assert rows["jce-sunjce"]["provided_by"] == "jdk"
    # 平台依赖不进「第三方依赖」表，但必须出现在台账里
    assert rows["servlet-api"]["phase"] == "S4"


# --------------------------------------------------------------------------- 风险规则

def test_risk_rules_fired(project):
    risks = {r["rule_id"]: r for r in load_registry().apply_risk_rules(project)}
    assert "weak-crypto-algorithm" in risks      # MD5 / DES
    assert "javax-to-jakarta" in risks           # javax.servlet
    assert "jdk-internal-api" in risks           # sun.misc.BASE64Encoder / SunJCE
    assert "component-status" in risks           # iBATIS / Axis 已停更
    for r in risks.values():
        assert r["evidence"], f"规则 {r['rule_id']} 命中但无证据"


def test_risk_rules_are_disabled_by_default(project):
    """配置里的示例规则 enabled=false，不应出现在结果里。"""
    titles = [r["title"] for r in load_registry().apply_risk_rules(project)]
    assert not any("【示例】" in t for t in titles)


# --------------------------------------------------------------------------- 扩展口子语义

def _write_rules(tmp_path, filename, payload):
    d = tmp_path / "rules"
    d.mkdir(exist_ok=True)
    (d / filename).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(d)


def test_override_by_id_and_append_new(tmp_path, project):
    d = _write_rules(tmp_path, "components.json", {"components": [
        {"id": "ibatis2", "name": "iBATIS 2.x（自研分支）", "namespaces": ["com.ibatis"],
         "migration": {"target": "MyBatis 3.5.13", "breaking": "high", "phase": "S1"}},
        {"id": "vendor-sdk", "name": "某闭源 SDK", "category": "闭源组件", "status": "unknown",
         "namespaces": ["com.vendor.sdk"], "jar_patterns": ["vendor"],
         "migration": {"target": "防腐层隔离", "breaking": "high", "phase": "S5"}},
    ]})
    reg = load_registry().load(d)

    builtin = {c["id"]: c for c in load_registry().BUILTIN_COMPONENTS}
    merged = {c["id"]: c for c in reg["components"]}
    # 同 id 覆盖
    assert merged["ibatis2"]["name"] == "iBATIS 2.x（自研分支）"
    assert merged["ibatis2"]["migration"]["phase"] == "S1"
    # 新 id 追加，且内置基线保留
    assert "vendor-sdk" in merged
    assert "quartz" in merged and merged["quartz"] == builtin["quartz"]

    # 闭源组件登记后即可被识别（否则这类依赖在报告里是隐形的）
    rows = _by_id(load_registry().detect_components(project, reg))
    assert "vendor-sdk" in rows
    assert rows["vendor-sdk"]["status"] == "unknown"
    assert rows["vendor-sdk"]["phase"] == "S5"


def test_disabled_entry_is_ignored(tmp_path, project):
    d = _write_rules(tmp_path, "components.json", {"components": [
        {"id": "closed-x", "enabled": False, "name": "占位", "namespaces": ["com.vendor.sdk"]},
    ]})
    reg = load_registry().load(d)
    assert "closed-x" not in {c["id"] for c in reg["components"]}
    assert "closed-x" not in _by_id(load_registry().detect_components(project, reg))


def test_malformed_config_fails_fast(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    (d / "components.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry().load(str(d))

    d2 = tmp_path / "bad2"
    d2.mkdir()
    (d2 / "components.json").write_text(json.dumps({"components": {"a": 1}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_registry().load(str(d2))


def test_missing_dir_keeps_builtin(tmp_path):
    reg = load_registry().load(str(tmp_path / "nope"))
    assert reg["exists"] is False
    assert {c["id"] for c in reg["components"]} == {
        c["id"] for c in load_registry().BUILTIN_COMPONENTS}
    assert reg["dispatch"] == [] and reg["modules"] == {}


# --------------------------------------------------------------------------- 闭源分派

def test_dispatch_rule_extends_branches():
    _, lib_model = load_jlp()
    body = (
        'if ("query".equals(method)) { forward("/a.jsp"); }\n'
        'if ("save".equals(method)) { forward("/b.jsp"); }\n'
    )
    # 默认只认 action.equals —— 闭源框架用 method 参数时全部分支都丢了
    assert [b["action"] for b in lib_model.parse_dispatch_branches(body, [])] == []

    rules = [{"id": "vendor", "branch_pattern": r'"(\w+)"\.equals\(\s*method\s*\)',
              "action_group": 1}]
    actions = [b["action"] for b in lib_model.parse_dispatch_branches(body, rules)]
    assert actions == ["query", "save"]


def test_front_controller_detected_by_custom_rule(legacy_root):
    lib_scan, lib_model = load_jlp()
    proj = lib_scan.scan(legacy_root)
    rules = [{"id": "vendor", "branch_pattern": r'"(\w+)"\.equals\(\s*method\s*\)',
              "front_controller_pattern": r"extends\s+HttpServlet"}]
    routes = lib_model.build_routes(proj, rules)
    assert "com.demo.web.BaseServlet" in routes["front_controllers"]


# --------------------------------------------------------------------------- 模块边界

def test_module_rules_override_and_merge(legacy_root):
    lib_scan, lib_model = load_jlp()
    proj = lib_scan.scan(legacy_root)
    routes = lib_model.build_routes(proj)

    default_modules, _, _ = lib_model.derive_modules(proj, routes, {})
    default_domains = {m["domain"] for m in default_modules}
    assert "Order" in default_domains and "Upload" in default_domains

    # 按包强制归一成一个模块（闭源平台按包分层时常用）
    merged, _, _ = lib_model.derive_modules(proj, routes,
                                            {"package_modules": {"com.demo": "Demo"}})
    assert [m["domain"] for m in merged] == ["Demo"]

    # force_merge：把 Upload 并入 Order
    after, _, _ = lib_model.derive_modules(proj, routes, {"force_merge": [["Order", "Upload"]]})
    domains = {m["domain"] for m in after}
    assert "Upload" not in domains
    order = next(m for m in after if m["domain"] == "Order")
    assert any("UploadServlet" in s for s in order["servlet"])

    # exclude_types：基础设施类不作为模块种子
    trimmed, _, _ = lib_model.derive_modules(proj, routes, {"exclude_types": ["BaseServlet"]})
    assert "Base" not in {m["domain"] for m in trimmed}


# --------------------------------------------------------------------------- 流水线接入

def test_project_facts_are_enriched(legacy_root):
    facts = load_project_facts(legacy_root)
    ledger = component_ledger(facts)
    plat = platform_deps(facts)
    assert {c["id"] for c in ledger} >= {"ibatis2", "quartz", "poi", "dom4j"}
    assert {d["id"] for d in plat} >= {"servlet-api", "jce-sunjce"}
    # enrich 的结果随 project 一起走，最终落进 P0/P3 的事实与产物
    assert facts["project"]["components"] == ledger


def test_jar_present():
    reg = load_registry()
    blob = "commons-beanutils-1.7.0.jar commons-logging-1.1.jar"
    assert reg.jar_present({"jar_patterns": ["commons-beanutils"]}, blob) is True
    assert reg.jar_present({"jar_patterns": ["commons-io"]}, blob) is False
    # 没有 jar_patterns 时回落到名称关键字启发式
    assert reg.jar_present({}, "json-lib-2.2.3.jar", "json-lib") is True
    assert reg.jar_present({}, "nothing-here.jar", "json-lib") is False


def test_repo_config_dir_is_valid():
    """仓库自带的 `config/legacy` 必须能被正常加载（它就是给人工补充的模板）。"""
    reg = load_registry().load()
    assert reg["exists"] is True
    assert os.path.isdir(reg["dir"])
    assert reg["modules"] == {} or isinstance(reg["modules"], dict)
