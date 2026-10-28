#!/usr/bin/env python3
"""不调用模型：从原始输出里剥离 ```diff 围栏，检验补丁能否通过 git apply --check。

用途：判断"模型产出的 diff 不可用"到底是
  (a) 只是被 Markdown 围栏包住（脚本剥离即可解决），还是
  (b) 内容本身伪造（hunk 上下文/行号与真实文件对不上，必须人工）。
"""
import argparse
import os
import re
import subprocess
import sys

FENCE = re.compile(r"```diff\n(.*?)\n```", re.S)


def diff_of(txt):
    m = FENCE.findall(txt)
    if m:
        return max(m, key=len)
    return txt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    txt = open(a.raw, encoding="utf-8", errors="replace").read()
    d = diff_of(txt)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(d)

    print(f"raw={len(txt)} chars -> diff={len(d)} chars  围栏={'有' if FENCE.search(txt) else '无'}")
    r = subprocess.run(["git", "-C", a.repo, "apply", "--check", "--recount", "-"],
                       input=d, capture_output=True, text=True)
    print(f"git apply --check --recount: rc={r.returncode}")
    if r.stderr:
        print("  stderr:", r.stderr.strip()[:300])

    # 再试带 3 行容错（模型常把行号写错）
    if r.returncode != 0:
        r2 = subprocess.run(["git", "-C", a.repo, "apply", "--check", "-C1", "--recount", "--unidiff-zero", "-"],
                            input=d, capture_output=True, text=True)
        print(f"  容错重试(-C1 --unidiff-zero): rc={r2.returncode}")
        if r2.stderr:
            print("  stderr:", r2.stderr.strip()[:200])

    # 检查 hunk 头声明的行号是否与真实文件匹配
    for m in re.finditer(r"^--- a/(\S+)\n\+\+\+ b/(\S+)", d, re.M):
        f = m.group(1)
        p = os.path.join(a.repo, f)
        print(f"  目标文件 {f}: {'存在' if os.path.exists(p) else '*** 不存在 ***'}")


if __name__ == "__main__":
    main()
