"""离线自检：用内置合成语料跑一遍全链路，**不联网、不需要 LLM**。

目的是在没有 Ollama 的机器上也能确认工具可用（Windows 上尤其重要）：
    python jlp.py --self-test

断言的都是"抽取是否准"，不是"文档是否好看"——数量与归属错一个就算失败。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lib_scan
import lib_tech
from lib_model import build_routes, derive_modules, derive_risks

# ---------------------------------------------------------------- 合成语料

JAVA = {
    "src/com/demo/util/BaseDao.java": """package com.demo.util;
import java.sql.Connection;
public class BaseDao {
  public Connection getPoolConnection() { return null; }
}
""",
    "src/com/demo/entity/User.java": """package com.demo.entity;
public class User {
  private int id;
  private String name;
  public int getId() { return id; }
  public String getName() { return name; }
}
""",
    "src/com/demo/dao/UserDao.java": """package com.demo.dao;
import java.util.List;
import com.demo.entity.User;
public interface UserDao {
  List<User> list();
  int add(User u);
}
""",
    "src/com/demo/dao/impl/UserDaoImpl.java": """package com.demo.dao.impl;
import com.demo.dao.UserDao;
import com.demo.entity.User;
import com.demo.util.BaseDao;
public class UserDaoImpl extends BaseDao implements UserDao {
  public java.util.List<User> list() {
    String sql = "select * from t_user";
    return null;
  }
  public int add(User u) {
    String sql = "insert into t_user values(?,?)";
    return 0;
  }
  public int del(int id) {
    String sql = "delete from t_user where id=?";
    return 0;
  }
}
""",
    "src/com/demo/biz/UserBiz.java": """package com.demo.biz;
public interface UserBiz { void save(); }
""",
    "src/com/demo/biz/impl/UserBizImpl.java": """package com.demo.biz.impl;
import com.demo.biz.UserBiz;
import com.demo.dao.UserDao;
import com.demo.dao.impl.UserDaoImpl;
public class UserBizImpl implements UserBiz {
  UserDao dao = new UserDaoImpl();
  public void save() { System.out.println("save"); }
}
""",
    "src/com/demo/servlet/UserServlet.java": """package com.demo.servlet;
import javax.servlet.http.HttpServlet;
import com.demo.biz.UserBiz;
import com.demo.biz.impl.UserBizImpl;
public class UserServlet extends HttpServlet {
  public void process(javax.servlet.http.HttpServletRequest request,
                      javax.servlet.http.HttpServletResponse response) {
    String action = request.getParameter("action");
    if (action == null) {
      request.getRequestDispatcher("../users/userList.jsp").forward(request, response);
    } else if (action.equals("add")) {
      response.sendRedirect("User.do");
    }
  }
}
""",
    "src/com/demo/controller/FrontServlet.java": """package com.demo.controller;
import javax.servlet.http.HttpServlet;
public class FrontServlet extends HttpServlet {
  public void process(javax.servlet.http.HttpServletRequest request,
                      javax.servlet.http.HttpServletResponse response) {
    int i = request.getRequestURI().lastIndexOf("/");
    String action = request.getRequestURI().substring(i + 1);
    if (action.equals("User.do")) {
      request.getRequestDispatcher("/servlet/UserServlet").forward(request, response);
    } else if (action.equals("login.do")) {
      response.sendRedirect("users/userList.jsp");
    }
  }
}
""",
}

JSP = {
    "WebRoot/login.jsp": """<%@ page language="java" pageEncoding="GBK"%>
<html><head><link rel="stylesheet" href="css/missing.css"/></head>
<body><h1>登录</h1>
<form action="login.do" method="post">
<input name="u"/><input type="submit"/></form></body></html>
""",
    "WebRoot/users/userList.jsp": """<%@ page language="java" pageEncoding="UTF-8"%>
<html><body>
<form action="User.do" method="get"><input name="q"/></form>
<a href="User.do?action=del&id=1">del</a>
</body></html>
""",
    "WebRoot/users/userAdd.jsp": """<%@ page language="java" pageEncoding="UTF-8"%>
<html><body>
<form action="User.do?action=add" method="post"><input name="n"/></form>
</body></html>
""",
    "WebRoot/css/style.css": "body{}\n",
}

WEB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<web-app xmlns="http://java.sun.com/xml/ns/javaee"
         xsi:schemaLocation="http://java.sun.com/xml/ns/javaee
         http://java.sun.com/xml/ns/javaee/web-app_2_5.xsd" version="2.5">
  <welcome-file-list><welcome-file>login.jsp</welcome-file></welcome-file-list>
  <servlet>
    <servlet-name>Front</servlet-name>
    <servlet-class>com.demo.controller.FrontServlet</servlet-class>
  </servlet>
  <servlet-mapping>
    <servlet-name>Front</servlet-name>
    <url-pattern>*.do</url-pattern>
  </servlet-mapping>
  <servlet>
    <servlet-name>UserServlet</servlet-name>
    <servlet-class>com.demo.servlet.UserServlet</servlet-class>
  </servlet>
  <servlet-mapping>
    <servlet-name>UserServlet</servlet-name>
    <url-pattern>/servlet/UserServlet</url-pattern>
  </servlet-mapping>
</web-app>
"""

SQL_GBK = "CREATE TABLE T_USER (ID NUMBER, NAME VARCHAR2(50));\n-- 用户表\n"


def _write(fixture: str):
    for rel, body in JAVA.items():
        p = os.path.join(fixture, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    for rel, body in JSP.items():
        p = os.path.join(fixture, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        enc = "gb18030" if "GBK" in body else "utf-8"
        with open(p, "w", encoding=enc, newline="\n") as f:
            f.write(body)
    p = os.path.join(fixture, "WebRoot", "WEB-INF", "web.xml")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(WEB_XML)
    p = os.path.join(fixture, "schema.sql")
    with open(p, "w", encoding="gb18030", newline="\n") as f:
        f.write(SQL_GBK)


# ---------------------------------------------------------------- 断言

def run() -> int:
    tmp = tempfile.mkdtemp(prefix="jlp-selftest-")
    fixture = os.path.join(tmp, "mini")
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    try:
        _write(fixture)
        proj = lib_scan.scan(fixture)

        check("Java 文件数 == 8", len(proj["java"]) == 8, f"实际 {len(proj['java'])}")
        check("JSP 文件数 == 3", len(proj["jsp"]) == 3, f"实际 {len(proj['jsp'])}")

        encs = {f["file"]: f["encoding"] for f in proj["files"]}
        check("GBK 的 schema.sql 被正确解码",
              "schema" in "".join(encs) and encs.get("schema.sql", "").startswith("gb"),
              f"实际 {encs.get('schema.sql')}")
        check("GBK 的 login.jsp 被正确解码",
              encs.get("WebRoot/login.jsp", "").startswith("gb"),
              f"实际 {encs.get('WebRoot/login.jsp')}")
        check("全部文本文件都成功解码",
              all(f["encoding"] for f in proj["files"]))

        sql_names = {t for s in proj["sql"] for t in s["tables"]}
        check("解析出建表对象", sql_names == {"t_user"}, f"实际 {sorted(sql_names)}")

        routes = build_routes(proj)
        check("识别前端控制器 FrontServlet",
              routes["front_controllers"] == ["com.demo.controller.FrontServlet"],
              f"实际 {routes['front_controllers']}")
        check("web.xml 路由数 == 2", len(routes["routes"]) == 2, f"实际 {len(routes['routes'])}")

        from lib_model import resolve_owner
        owner, _ = resolve_owner(routes, "User.do?action=add")
        check("User.do 经前端控制器解析到 UserServlet",
              owner == "com.demo.servlet.UserServlet", f"实际 {owner}")

        modules, unassigned, _ = derive_modules(proj, routes)
        user_mod = next((m for m in modules if m["domain"] == "User"), None)
        check("识别出 User 模块", user_mod is not None,
              f"模块列表 {[m['domain'] for m in modules]}")
        if user_mod:
            pages = {os.path.basename(p) for p in user_mod["pages"]}
            check("User 模块页面归属正确", pages == {"userList.jsp", "userAdd.jsp"},
                  f"实际 {sorted(pages)}")
            check("前端页面前缀推导正确", user_mod["page_prefix"] == "user",
                  f"实际 {user_mod['page_prefix']!r}")
            check("能力矩阵含新增/删除/查询",
                  {"新增", "删除", "查询"} <= set(user_mod["competences"]),
                  f"实际 {user_mod['competences']}")
            check("反查实体正确", user_mod["entity"] == ["com.demo.entity.User"],
                  f"实际 {user_mod['entity']}")
            check("反查数据表正确", user_mod["tables"] == ["t_user"],
                  f"实际 {user_mod['tables']}")

        login_assigned = "WebRoot/login.jsp" in unassigned
        check("login.jsp 不归属 User 模块", login_assigned,
              f"unassigned={unassigned}")

        risks = derive_risks(proj, modules, unassigned)
        titles = {r["title"] for r in risks}
        check("检出悬空资源引用", "静态资源悬空引用" in titles, f"实际 {titles}")
        check("检出遗留 System.out", "遗留 System.out 调试输出" in titles, f"实际 {titles}")
        check("检出未归属页面", "未归属到业务模块的页面" in titles, f"实际 {titles}")

        tech = lib_tech.build(proj)
        check("判定为无框架的裸 Servlet", "裸 Servlet" in dict(
            (r[0], r[1]) for r in tech["rows"]).get("MVC 框架", ""),
            str(tech["rows"]))

        # 端到端：直接跑命令行
        import subprocess
        outdir = os.path.join(tmp, "out")
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "jlp.py"),
               "--src", fixture, "--out", outdir, "--quiet"]
        proc = subprocess.run(cmd, capture_output=True)
        check("端到端命令行返回 0", proc.returncode == 0,
              proc.stderr.decode("utf-8", "replace")[-400:])
        for name in ("00-preflight.md", "01-structure.md", "02-dependencies.md",
                     "03-modules.md", "10-requirement-analysis.md",
                     "99-summary.md", "facts.json"):
            p = os.path.join(outdir, name)
            check(f"产出 {name}", os.path.exists(p) and os.path.getsize(p) > 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    width = max(len(n) for n, _, _ in results)
    passed = 0
    for name, ok, detail in results:
        if ok:
            passed += 1
            print(f"PASS  {name.ljust(width)}")
        else:
            print(f"FAIL  {name.ljust(width)}  {detail}")
    print(f"\n{'=' * (width + 6)}")
    print(f"自检结果：PASS={passed}  FAIL={len(results) - passed}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
