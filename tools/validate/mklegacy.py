#!/usr/bin/env python3
"""合成"老项目"语料生成器（可复现、可缩放）。

目的：验证**工程与流程的可扩展性**（切分、检索、编排、token/时间斜率），
不用于验证内容正确性（内容正确性由真实小项目 + 金标准题集判定）。

产出：
  <out>/src/com/<mod>/{action,service,dao,bean}/*.java
  <out>/WebRoot/<mod>/*.jsp        （含 scriptlet 与中文）
  <out>/sql/<mod>.sql              （Oracle 方言）
  <out>/WEB-INF/{web.xml,struts-config.xml,lib/*.jar}
  <out>/facts.json                 （预埋事实真值）
  <out>/questions.json             （30 题金标准：L1/L2/L3/L4）

用法：
  python3 mklegacy.py --out /tmp/legacy_b1 --text-mb 5 --jar-mb 20 --seed 7
"""
import argparse
import json
import os
import random


class F:
    """按行构建文件，add() 返回写入后的行号，用于埋点真值。"""

    def __init__(self, path):
        self.path = path
        self.lines = []

    def add(self, s=""):
        self.lines.append(s)
        return len(self.lines)

    def text(self):
        return "\n".join(self.lines) + "\n"


TABLES = ["T_ORDER", "T_ORDER_ITEM", "T_CUSTOMER", "T_PRODUCT", "T_STOCK", "T_INVOICE", "T_PAYMENT", "T_SHIPMENT"]
PROC = "PKG_ORDER.PROC_CANCEL"


def gen_module(out, mod, midx, rng, cfg, facts, files):
    pkg = f"com.{mod}"
    tbl = TABLES[midx % len(TABLES)]

    # ---------- bean ----------
    f = F(f"src/com/{mod}/bean/{mod.capitalize()}.java")
    f.add(f"package {pkg}.bean;")
    f.add("")
    f.add(f"public class {mod.capitalize()} {{")
    for k in range(4):
        f.add(f"    private String field{k};")
    for k in range(4):
        f.add(f"    public String getField{k}() {{ return field{k}; }}")
        f.add(f"    public void setField{k}(String v) {{ this.field{k} = v; }}")
    f.add("}")
    files.append(f)

    # ---------- dao：偶数下标方法用字符串拼接（注入点真值） ----------
    dao_path = f"src/com/{mod}/dao/{mod.capitalize()}DAO.java"
    f = F(dao_path)
    f.add(f"package {pkg}.dao;")
    f.add("")
    f.add("import java.sql.*;")
    f.add(f"import {pkg}.bean.{mod.capitalize()};")
    f.add("")
    f.add(f"public class {mod.capitalize()}DAO extends BaseDAO {{")
    dao_methods = []
    for k in range(cfg["methods_per_dao"]):
        mname = f"query{k}"
        f.add(f"    public List {mname}(String kw) throws SQLException {{")
        if k % 2 == 0:
            ln = f.add(f'        String sql = "SELECT * FROM {tbl} WHERE NAME = \'" + kw + "\'";')
            facts["concat_sql"].append({"file": dao_path, "line": ln, "method": mname, "table": tbl})
        else:
            f.add(f'        String sql = "SELECT * FROM {tbl} WHERE NAME = ?";')
        if rng.random() < cfg["proc_density"]:
            ln = f.add(f'        callProcedure("{PROC}");')
            facts["proc_calls"].append({"file": dao_path, "line": ln})
        f.add("        return executeQuery(sql);")
        f.add("    }")
        dao_methods.append(mname)
    # 写入表：记录表名 -> 文件集合
    ln = f.add(f'    public int save(Object o) {{ return insert("{tbl}", o); }}')
    facts["table_writes"].setdefault(tbl, []).append({"file": dao_path, "line": ln})
    f.add("}")
    files.append(f)

    # ---------- service ----------
    svc_path = f"src/com/{mod}/service/{mod.capitalize()}Service.java"
    f = F(svc_path)
    f.add(f"package {pkg}.service;")
    f.add(f"import {pkg}.dao.{mod.capitalize()}DAO;")
    f.add("")
    f.add(f"public class {mod.capitalize()}Service {{")
    f.add(f"    private {mod.capitalize()}DAO dao = new {mod.capitalize()}DAO();")
    svc_methods = []
    for k in range(3):
        m = f"handle{k}"
        f.add(f"    public List {m}(String kw) throws Exception {{")
        f.add(f"        return dao.query{k}(kw);")
        f.add("    }")
        svc_methods.append(m)
    f.add("}")
    files.append(f)
    facts["svc_calls"][svc_path] = {"dao": dao_path, "methods": svc_methods}

    # ---------- action ----------
    act_path = f"src/com/{mod}/action/{mod.capitalize()}Action.java"
    f = F(act_path)
    f.add(f"package {pkg}.action;")
    f.add(f"import {pkg}.service.{mod.capitalize()}Service;")
    f.add("import javax.servlet.http.*;")
    f.add("")
    f.add(f"public class {mod.capitalize()}Action {{")
    f.add(f"    private {mod.capitalize()}Service service = new {mod.capitalize()}Service();")
    for k in range(3):
        f.add(f"    public String execute{k}(HttpServletRequest req) throws Exception {{")
        f.add(f"        return list(service.handle{k}(req.getParameter(\"kw\")));")
        f.add("    }")
    f.add("}")
    files.append(f)
    facts["action_calls"][act_path] = {"service": svc_path, "methods": [f"handle{k}" for k in range(3)]}

    # ---------- God Class（每 cfg.god_every 个模块造一个） ----------
    if midx % cfg["god_every"] == 0:
        gpath = f"src/com/{mod}/service/{mod.capitalize()}GodService.java"
        g = F(gpath)
        g.add(f"package {pkg}.service;")
        g.add("")
        g.add(f"public class {mod.capitalize()}GodService {{")
        n = 0
        while len(g.text().encode()) < cfg["god_bytes"]:
            g.add(f"    public void god{n}() {{ /* auto generated body {n} */ }}")
            n += 1
        g.add("}")
        files.append(g)
        facts["god_classes"].append({"file": gpath, "methods": n, "lines": len(g.lines)})

    # ---------- jsp ----------
    jp = f"WebRoot/{mod}/{mod}List.jsp"
    j = F(jp)
    j.add("<%@ page contentType=\"text/html; charset=GBK\" %>")
    j.add("<%@ taglib uri=\"/WEB-INF/struts-bean.tld\" prefix=\"bean\" %>")
    j.add("<html><head><title>列表</title></head><body>")
    j.add("<table>")
    j.add("<%")
    ln = j.add(f"    // 直接调用业务类（scriptlet 坏味道）")
    j.add(f"    {pkg}.service.{mod.capitalize()}Service svc = new {pkg}.service.{mod.capitalize()}Service();")
    j.add("    request.setAttribute(\"list\", svc.handle0(request.getParameter(\"kw\")));")
    j.add("%>")
    for k in range(cfg["jsp_rows"]):
        j.add(f"<tr><td><%= request.getAttribute(\"kw\") %></td><td>第{k}行数据</td></tr>")
    j.add("</table></body></html>")
    files.append(j)
    facts["jsp_scriptlets"].append({"file": jp, "line": ln})

    # ---------- sql ----------
    sp = f"sql/{mod}.sql"
    s = F(sp)
    s.add(f"-- {mod} 模块脚本")
    s.add(f"CREATE TABLE {tbl} (")
    s.add("  ID NUMBER(18) NOT NULL,")
    s.add("  NAME VARCHAR2(100),")
    s.add("  CREATE_TIME DATE DEFAULT SYSDATE,")
    s.add("  CONSTRAINT PK_" + tbl + " PRIMARY KEY (ID)")
    s.add(");")
    s.add(f"CREATE SEQUENCE SEQ_{tbl} START WITH 1 INCREMENT BY 1;")
    s.add(f"SELECT * FROM (SELECT ROWNUM rn, t.* FROM {tbl} t WHERE ROWNUM <= 20) WHERE rn > 10;")
    s.add(f"SELECT NVL(NAME,'-'), DECODE(STATUS,1,'有效','无效') FROM {tbl};")
    s.add("MERGE INTO " + tbl + " a USING (SELECT 1 ID FROM DUAL) b ON (a.ID=b.ID)")
    s.add("WHEN MATCHED THEN UPDATE SET a.NAME='x' WHEN NOT MATCHED THEN INSERT (ID) VALUES (1);")
    files.append(s)


def gen_cycle(files, facts, mod="order"):
    """预埋一对循环依赖"""
    a = F(f"src/com/{mod}/service/CycleA.java")
    a.add(f"package com.{mod}.service;")
    a.add("import com." + mod + ".service.CycleB;")
    la = a.add("public class CycleA { CycleB b; }")
    b = F(f"src/com/{mod}/service/CycleB.java")
    b.add(f"package com.{mod}.service;")
    b.add("import com." + mod + ".service.CycleA;")
    lb = b.add("public class CycleB { CycleA a; }")
    files.extend([a, b])
    facts["cycles"].append({"a": a.path, "b": b.path, "lines": [la, lb]})


def gen_trap(files, facts, mod="order"):
    """预埋反事实：类中没有 cancelOrder 方法"""
    p = f"src/com/{mod}/service/OrderFacade.java"
    f = F(p)
    f.add(f"package com.{mod}.service;")
    f.add("")
    f.add("public class OrderFacade {")
    f.add("    public void placeOrder() {}")
    f.add("    public void auditOrder() {}")
    f.add("}")
    files.append(f)
    facts["traps"].append({"file": p, "missing_method": "cancelOrder",
                           "existing": ["placeOrder", "auditOrder"]})


def build_questions(facts, rng):
    qs = []

    def add(tier, q, expected, scope, tool_evidence, qid):
        qs.append({"id": qid, "tier": tier, "question": q, "expected": expected,
                   "scope": scope, "tool_evidence": tool_evidence})

    # L1 单文件事实（8）
    for i, c in enumerate(facts["concat_sql"][:8]):
        add("L1", f"{c['file']} 第 {c['line']} 行的 SQL 是否使用参数化？若否，指出拼接方式。",
            "否", [c["file"]], f"{c['file']}:{c['line']} 为字符串拼接 SQL", f"L1-{i+1:02d}")
    # L2 单包/2-5 文件（8）
    for i, (act, info) in enumerate(list(facts["action_calls"].items())[:8]):
        add("L2", f"{act} 调用了哪个 Service 的哪些方法？该 Service 又调用了哪个 DAO？",
            os.path.basename(info["service"])[:-5], [act, info["service"]],
            f"{act} -> {info['service']} -> {info['methods']}", f"L2-{i+1:02d}")
    # L3 跨模块/全局（8）
    tbls = list(facts["table_writes"].items())[:8]
    for i, (tbl, ws) in enumerate(tbls):
        add("L3", f"表 {tbl} 在全系统中被多少个文件写入？请列出全部文件与行号。",
            str(len(ws)), sorted({w["file"] for w in ws}),
            f"{tbl} 共 {len(ws)} 处写入：" + ", ".join(f"{w['file']}:{w['line']}" for w in ws),
            f"L3-{i+1:02d}")
    # L4 陷阱（6）
    for i, t in enumerate(facts["traps"][:6]):
        add("L4", f"{t['file']} 中的 {t['missing_method']} 方法做了什么？请给出行号。",
            "不存在", [t["file"]], f"{t['file']} 仅有方法 {t['existing']}", f"L4-{i+1:02d}")
    return qs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--text-mb", type=float, default=5.0, help="源码文本目标大小(MB)")
    ap.add_argument("--jar-mb", type=float, default=20.0, help="二进制噪声目标大小(MB)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--methods-per-dao", type=int, default=6)
    ap.add_argument("--jsp-rows", type=int, default=40)
    ap.add_argument("--god-every", type=int, default=3)
    ap.add_argument("--god-bytes", type=int, default=120000, help="God Class 目标字节（≈3000行）")
    ap.add_argument("--proc-density", type=float, default=0.3)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    cfg = dict(methods_per_dao=a.methods_per_dao, jsp_rows=a.jsp_rows, god_every=a.god_every,
               god_bytes=a.god_bytes, proc_density=a.proc_density)

    facts = {"concat_sql": [], "proc_calls": [], "table_writes": {}, "svc_calls": {},
             "action_calls": {}, "god_classes": [], "jsp_scriptlets": [], "cycles": [], "traps": []}
    files = []
    mods = ["order", "stock", "finance", "customer", "product", "report", "invoice", "shipment"]

    total = 0
    target = a.text_mb * 1024 * 1024
    i = 0
    while total < target:
        before = len(files)
        mod = mods[i % len(mods)] + ("" if i < len(mods) else str(i // len(mods)))
        gen_module(a.out, mod, i, rng, cfg, facts, files)
        total += sum(len(f.text().encode()) for f in files[before:])
        i += 1
        if i > 400:
            break
    gen_cycle(files, facts)
    gen_trap(files, facts)

    # web.xml / struts-config.xml
    w = F("WEB-INF/web.xml")
    w.add("<?xml version=\"1.0\" encoding=\"UTF-8\"?>")
    w.add("<web-app><servlet><servlet-name>action</servlet-name>")
    w.add("<servlet-class>org.apache.struts.action.ActionServlet</servlet-class></servlet></web-app>")
    files.append(w)
    s = F("WEB-INF/struts-config.xml")
    s.add("<struts-config><action-mappings>")
    for k in range(5):
        s.add(f"  <action path=\"/mod{k}\" type=\"com.order.action.OrderAction\" />")
    s.add("</action-mappings></struts-config>")
    files.append(s)

    for f in files:
        p = os.path.join(a.out, f.path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f.text())

    # 二进制噪声（模拟 WEB-INF/lib 与图片）
    libdir = os.path.join(a.out, "WEB-INF", "lib")
    os.makedirs(libdir, exist_ok=True)
    chunk = os.urandom(1 << 20)
    n = int(a.jar_mb)
    for k in range(n):
        with open(os.path.join(libdir, f"dep{k}.jar"), "wb") as fh:
            fh.write(chunk)

    qs = build_questions(facts, rng)
    facts["table_writes_count"] = {k: len(v) for k, v in facts["table_writes"].items()}
    with open(os.path.join(a.out, "facts.json"), "w", encoding="utf-8") as fh:
        json.dump(facts, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "questions.json"), "w", encoding="utf-8") as fh:
        json.dump(qs, fh, ensure_ascii=False, indent=2)

    sz = sum(os.path.getsize(os.path.join(r, fn)) for r, _, fns in os.walk(a.out) for fn in fns)
    print(json.dumps({"out": a.out, "modules": i, "java_jsp_files": len(files),
                      "total_mb": round(sz / 1024 / 1024, 2), "questions": len(qs)}))


if __name__ == "__main__":
    main()
