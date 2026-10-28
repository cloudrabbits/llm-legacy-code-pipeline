#!/usr/bin/env python3
"""直连 Ollama 的补全通道（不经过 OpenCode agent）。

为什么需要它（实测依据，2026-10-27）：
  * qwen3.6-35B-A3B 在 OpenCode 的 build agent 下会"叙述意图但不执行"：
    只回一句 "Now let me create the output directory and write the deliverable." 就结束会话；
  * 该模型会输出思维链，占用大量输出预算（直连时 3000 token 全被思考吃掉）；
  * 关掉 think 后直连可稳定产出合规 Markdown（53-75s / 1300-1700 token）。

因此：direct 模式 = 脚本预取事实（L0 + 指定文件原文） + 模型只写叙述。
stdout 输出模型正文，stderr 输出统计 JSON（供编排器记录）。
"""
import argparse
import json
import sys
import time
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--ctx", type=int, default=90000)
    ap.add_argument("--predict", type=int, default=3500)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--think", default="false")
    a = ap.parse_args()

    prompt = open(a.prompt, encoding="utf-8").read()
    body = json.dumps({
        "model": a.model,
        "stream": False,
        "prompt": prompt,
        "keep_alive": -1,
        "think": a.think.lower() == "true",
        "options": {"num_ctx": a.ctx, "num_predict": a.predict, "temperature": a.temperature},
    }).encode()

    req = urllib.request.Request(a.url.rstrip("/") + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=a.timeout) as r:
            d = json.loads(r.read().decode())
    except Exception as e:
        print(json.dumps({"error": str(e)[:300]}), file=sys.stderr)
        sys.exit(3)

    el = time.time() - t0
    txt = d.get("response", "") or ""
    pc = d.get("prompt_eval_count", 0) or 0
    pd = (d.get("prompt_eval_duration", 0) or 0) / 1e9
    ec = d.get("eval_count", 0) or 0
    ed = (d.get("eval_duration", 0) or 0) / 1e9
    print(json.dumps({
        "wall_s": round(el, 1),
        "prompt_tokens": pc,
        "prefill_tps": round(pc / pd, 1) if pd else None,
        "decode_tokens": ec,
        "decode_tps": round(ec / ed, 1) if ed else None,
        "done_reason": d.get("done_reason"),
        "chars": len(txt),
        "thinking_chars": len(d.get("thinking", "") or ""),
    }), file=sys.stderr)

    sys.stdout.write(txt)
    if txt and not txt.endswith("\n"):
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
