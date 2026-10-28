#!/usr/bin/env python3
"""产物验收器：对 check 规则逐条求值，全部通过才置 done。

规则语法（用 | 分隔多条）：
  size>N            文件字节数大于 N
  lines>a-b         行数在区间内
  heading:'正则'     至少命中一个标题（默认二级标题）
  grep:'串'          必须出现
  notgrep:'串'       必须不出现
  mermaid            ```mermaid 代码块成对
  json               末尾能解析出 JSON 状态行
  gitapply           该路径能被 git apply --check 接受
  facts>=N           事实条目（文件:行号 | 结论）不少于 N 条
"""
import json
import os
import re
import subprocess
import sys


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def check_one(path, rule):
    if not os.path.exists(path):
        return False, f"missing file: {path}"
    txt = read(path)
    raw = open(path, "rb").read()
    rule = rule.strip()

    if rule.startswith("size>"):
        n = int(rule[5:])
        ok = len(raw) > n
        return ok, f"size {len(raw)} > {n}"
    if rule.startswith("lines>"):
        rng = rule[6:].split("-")
        nl = txt.count("\n") + 1
        lo = int(rng[0])
        hi = int(rng[1]) if len(rng) > 1 else 10 ** 9
        return lo <= nl <= hi, f"lines {nl} in [{lo},{hi}]"
    if rule.startswith("heading:"):
        pat = rule[len("heading:"):].strip().strip("'\"")
        return bool(re.search(pat, txt, re.M)), f"heading /{pat}/"
    if rule.startswith("grep:"):
        s = rule[5:].strip().strip("'\"")
        return s in txt, f"grep '{s}'"
    if rule.startswith("notgrep:"):
        s = rule[8:].strip().strip("'\"")
        return s not in txt, f"notgrep '{s}'"
    if rule == "mermaid":
        return txt.count("```mermaid") >= 1 and txt.count("```") % 2 == 0, "mermaid block balanced"
    if rule == "json":
        return last_json(txt) is not None, "trailing JSON status"
    if rule == "gitapply":
        # 必须在仓库根执行，否则 git apply --check 会因找不到文件而误判（实测踩到）
        cmd = ["git"]
        repo = globals().get("REPO")
        if repo:
            cmd += ["-C", repo]
        cmd += ["apply", "--check", path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode == 0, f"git apply --check rc={r.returncode} {r.stderr[:80]}"
    if rule.startswith("facts>="):
        n = int(rule[7:])
        c = len([l for l in txt.splitlines() if re.match(r"^- .+:\d+ \| ", l)])
        return c >= n, f"facts {c} >= {n}"
    return False, f"unknown rule: {rule}"


def last_json(txt):
    """取正文最后一段合法 JSON 对象"""
    cands = re.findall(r"\{[^{}]*\"status\"[^{}]*\}", txt)
    for c in reversed(cands):
        try:
            return json.loads(c)
        except Exception:
            continue
    return None


REPO = ""


def main():
    global REPO
    path = sys.argv[1]
    rules = sys.argv[2] if len(sys.argv) > 2 else ""
    if "--repo" in sys.argv:
        i = sys.argv.index("--repo")
        REPO = sys.argv[i + 1]
        sys.argv.pop(i)
        sys.argv.pop(i)
    if not rules or rules == "-":
        print(json.dumps({"ok": os.path.exists(path) and os.path.getsize(path) > 0, "results": []}))
        sys.exit(0 if os.path.exists(path) else 1)
    results = []
    ok_all = True
    for r in rules.split("|"):
        r = r.strip()
        if not r:
            continue
        ok, msg = check_one(path, r)
        results.append({"rule": r, "ok": ok, "msg": msg})
        ok_all = ok_all and ok
    print(json.dumps({"ok": ok_all, "results": results}, ensure_ascii=False))
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
