#!/usr/bin/env bash
# 验证第 6 步：L0 脚本图层 + 关闭思维链，直连 Ollama
# 对照第 5 步（无 L0、思维链开）：验证「脚本供事实 + 抑制思考」是否让产物可用
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nightly/env.sh"
export MODEL="local-ollama/qwen3.6-35B-A3B-90k"
TAG="qwen3.6-35B-A3B-90k"

echo "== 1) 生成 L0 图层 =="
python3 "$TOOLS_DIR/lib/l0.py" --src "$WORK" --out "$CONTEXT_DIR/L0-inventory.md"
echo "  首 12 行："
head -12 "$CONTEXT_DIR/L0-inventory.md" | sed 's/^/    /'

echo
echo "== 2) 重新拼装提示词（text 模式，含 L0） =="
python3 "$TOOLS_DIR/lib/bootstrap.py" --work "$WORK" --task T01 --seq 1 --range '*' \
  --out docs/arch/01-inventory.md --prompt "$TASKDIR/T01.md" \
  --max-tokens 60000 --tool-mode text --o "$STATE/prompt-T01_1.md"
P="$STATE/prompt-T01_1.md"
echo "  $(wc -c < "$P") bytes, 含 L0: $(grep -c 'L0 确定性图层' "$P")"

echo
echo "== 3) 直连调用（think=false, predict=2500） =="
python3 - "$P" "$TAG" "$HOME/nightly/out/direct-l0-T01.md" <<'PY'
import json, sys, time, urllib.request, re
prompt_path, tag, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
prompt = open(prompt_path, encoding="utf-8").read()
body = json.dumps({
    "model": tag, "stream": False, "prompt": prompt, "keep_alive": -1,
    "think": False,
    "options": {"num_ctx": 90000, "num_predict": 2500, "temperature": 0.2},
}).encode()
req = urllib.request.Request("http://localhost:11434/api/generate", data=body,
                             headers={"Content-Type": "application/json"})
t0 = time.time()
with urllib.request.urlopen(req, timeout=3600) as r:
    d = json.loads(r.read().decode())
el = time.time() - t0
txt = d.get("response", "") or ""
th = d.get("thinking", "") or ""
open(out_path, "w", encoding="utf-8").write(txt)
pc = d.get("prompt_eval_count", 0) or 0
pd = (d.get("prompt_eval_duration", 0) or 0) / 1e9
ec = d.get("eval_count", 0) or 0
ed = (d.get("eval_duration", 0) or 0) / 1e9
print(f"  wall={el:.1f}s prefill={pc}tok/{pd:.1f}s={pc/pd if pd else 0:.0f}tps "
      f"decode={ec}tok/{ed:.1f}s={ec/ed if ed else 0:.1f}tps")
print(f"  done_reason={d.get('done_reason')} response={len(txt)}chars thinking={len(th)}chars")
print(f"  含 ```markdown 块: {txt.count('```markdown')}")
print(f"  含 JSON status: {len(re.findall(r'\"status\"', txt))}")
print("  --- 前 900 字符 ---")
print(txt[:900])
print("  --- 后 400 字符 ---")
print(txt[-400:])
PY

echo
echo "== 4) 用验收器判定 =="
python3 "$TOOLS_DIR/lib/verify.py" "$HOME/nightly/out/direct-l0-T01.md" "size>2000|heading:'^## '" ; echo "  rc=$?"
