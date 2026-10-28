#!/usr/bin/env python3
"""上下文长度阶梯基准：分别测不同输入长度下的 prefill 与 decode 吞吐。

回答的问题：90K 窗口"装得下"和"处理得动"是两件事。
  prefill_tps 决定"读进来多快"，decode_tps 决定"写出去多快"，
  二者在混合卸载（GPU 8GB + RAM 15GB）下退化曲线不同。

用法：bench.py --url ... --model ... --ctx 90000 --lens 2048,8192,16384,32768 --predict 128
输出：每行一个 JSON
"""
import argparse
import json
import sys
import urllib.request

FILLER = ("该系统是一个基于 Java Web 的图书管理系统，包含图书管理、分类管理与用户管理模块，"
          "数据访问层通过 JDBC 访问 MySQL，前端页面由 JSP 与 JSTL 渲染。")


def build(target_tokens):
    # 中文约 1 token ≈ 1.5-2 字符；按 1.7 估算，宁多勿少
    target_chars = int(target_tokens * 1.7)
    parts, size = [], 0
    i = 0
    while size < target_chars:
        p = FILLER + f"（段落 {i}）"
        parts.append(p)
        size += len(p)
        i += 1
    text = "\n".join(parts)
    return text + "\n\n请用一句话总结上面文档的主题。"


def ask(url, model, prompt, num_ctx, num_predict, timeout):
    req = urllib.request.Request(
        url.rstrip("/") + "/api/generate",
        data=json.dumps({
            "model": model, "stream": False, "prompt": prompt, "keep_alive": -1,
            "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": 0},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--ctx", type=int, default=90000)
    ap.add_argument("--lens", default="2048,8192,16384,32768")
    ap.add_argument("--predict", type=int, default=128)
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args()

    for ln in [int(x) for x in a.lens.split(",") if x.strip()]:
        if ln > a.ctx:
            continue
        prompt = build(ln)
        try:
            d = ask(a.url, a.model, prompt, a.ctx, a.predict, a.timeout)
        except Exception as e:
            print(json.dumps({"target": ln, "error": str(e)[:200]}), flush=True)
            continue
        pc = d.get("prompt_eval_count", 0) or 0
        pd = (d.get("prompt_eval_duration", 0) or 0) / 1e9
        ec = d.get("eval_count", 0) or 0
        ed = (d.get("eval_duration", 0) or 0) / 1e9
        rec = {
            "target_tokens": ln,
            "prompt_tokens": pc,
            "prefill_s": round(pd, 1),
            "prefill_tps": round(pc / pd, 1) if pd else None,
            "decode_tokens": ec,
            "decode_s": round(ed, 1),
            "decode_tps": round(ec / ed, 1) if ed else None,
            "total_s": round(pd + ed, 1),
        }
        print(json.dumps(rec, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
