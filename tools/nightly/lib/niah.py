#!/usr/bin/env python3
"""长上下文检索探针（Needle-in-a-Haystack）：验证模型在指定上下文长度下是否还能取回埋入的事实。

用法：niah.py --url http://localhost:11434 --model NAME --ctx 90000 --depth 0.5 --repeat 3
输出：JSON {"ctx":90000,"depth":0.5,"hits":2,"total":3,"rate":0.67}
"""
import argparse
import json
import random
import urllib.request

FILLER = (
    "该项目是一个基于 Java Web 的图书馆管理系统，使用 Servlet 与 JSP 实现页面展示，"
    "数据访问层通过 JDBC 直接操作 MySQL 数据库，连接池采用 c3p0 管理。"
    "系统包含图书管理、分类管理与用户管理三个主要模块，前端页面使用 JSTL 与 EL 表达式渲染数据。"
)


def gen_prompt(ctx_tokens, depth, seed):
    rng = random.Random(seed)
    secret = f"SECRET-{rng.randint(1000, 9999)}"
    needle = f"（请记住这一句：{secret} 是本次检索的隐藏标记。）"
    target_chars = int(ctx_tokens * 3.2)
    body = []
    size = 0
    inserted = False
    while size < target_chars:
        para = FILLER + f"段落编号 {len(body)}。"
        body.append(para)
        size += len(para)
        if not inserted and size >= target_chars * depth:
            body.append(needle)
            inserted = True
    if not inserted:
        body.insert(len(body) // 2, needle)
    return "\n".join(body) + f"\n\n问题：上面文档中出现的隐藏标记是什么？只回答 SECRET-xxxx。", secret


def ask(url, model, prompt, num_ctx, timeout=900):
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate",
        data=json.dumps({
            "model": model, "stream": False, "prompt": prompt,
            "options": {"num_ctx": num_ctx, "num_predict": 32, "temperature": 0},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()).get("response", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--ctx", type=int, required=True)
    ap.add_argument("--depth", type=float, default=0.5)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=1200)
    a = ap.parse_args()

    hits = 0
    for i in range(a.repeat):
        prompt, secret = gen_prompt(a.ctx, a.depth, seed=1000 + i)
        try:
            resp = ask(a.url, a.model, prompt, a.ctx, a.timeout)
        except Exception as e:
            print(json.dumps({"ctx": a.ctx, "depth": a.depth, "error": str(e)}), flush=True)
            return
        if secret in resp:
            hits += 1
    print(json.dumps({"ctx": a.ctx, "depth": a.depth, "hits": hits, "total": a.repeat,
                      "rate": round(hits / a.repeat, 3)}))


if __name__ == "__main__":
    main()
