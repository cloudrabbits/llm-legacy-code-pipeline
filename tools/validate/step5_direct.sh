#!/usr/bin/env bash
# 验证第 5 步：绕开 OpenCode agent，直连 Ollama /api/generate，用同一份提示词
# 目的：把「模型能力」与「agent 外壳的指令干扰」分离
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nightly/env.sh"
TAG="qwen3.6-35B-A3B-90k"
PROMPT="${1:-$STATE/prompt-T01_1.md}"
OUTF="$HOME/nightly/out/direct-T01.md"
PREDICT="${2:-3000}"

echo "== 提示词 =="
echo "  $PROMPT  $(wc -c < "$PROMPT") bytes"
echo "  含任务书: $(grep -c '代码清单与模块地图' "$PROMPT")"

python3 - "$PROMPT" "$TAG" "$OUTF" "$PREDICT" <<'PY'
import json, sys, time, urllib.request

prompt_path, tag, out_path, predict = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
prompt = open(prompt_path, encoding="utf-8").read()

body = json.dumps({
    "model": tag, "stream": False, "prompt": prompt, "keep_alive": -1,
    "options": {"num_ctx": 90000, "num_predict": predict, "temperature": 0.2},
}).encode()

req = urllib.request.Request("http://localhost:11434/api/generate", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=3600) as r:
        d = json.loads(r.read().decode())
except Exception as e:
    print("FAILED:", e)
    sys.exit(1)
el = time.time() - t0
txt = d.get("response", "") or ""
open(out_path, "w", encoding="utf-8").write(txt)

pc = d.get("prompt_eval_count", 0) or 0
pd = (d.get("prompt_eval_duration", 0) or 0) / 1e9
ec = d.get("eval_count", 0) or 0
ed = (d.get("eval_duration", 0) or 0) / 1e9
print("== 结果 ==")
print(f"  wall={el:.1f}s  prefill={pc}tok/{pd:.1f}s={pc/pd if pd else 0:.0f}tps  "
      f"decode={ec}tok/{ed:.1f}s={ec/ed if ed else 0:.1f}tps")
print(f"  done_reason={d.get('done_reason')}  out={len(txt)} chars")
print("  --- 前 600 字符 ---")
print(txt[:600])
print("  --- 后 300 字符 ---")
print(txt[-300:])
PY
