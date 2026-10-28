#!/usr/bin/env bash
# 验证第 2 步：探通 OpenCode -> Ollama 调用链（极小 prompt，秒级）
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nightly/env.sh"
export MODEL="local-ollama/qwen3.6-35B-A3B-90k"

cd "$WORK" || exit 1
echo "== opencode run --help (关键参数) =="
opencode run --help 2>&1 | sed -n '1,40p'

echo
echo "== 探测 1：最小调用（无额外 flag） =="
T0=$(date +%s)
timeout 300 opencode run -m "$MODEL" "只回复两个字：收到" > /tmp/probe1.out 2>/tmp/probe1.err
RC=$?
echo "rc=$RC  elapsed=$(( $(date +%s) - T0 ))s"
echo "--- stdout ---"; head -c 500 /tmp/probe1.out
echo; echo "--- stderr(tail) ---"; tail -5 /tmp/probe1.err

echo
echo "== 探测 2：带 OC_FLAGS = $OC_FLAGS =="
T0=$(date +%s)
timeout 300 opencode run -m "$MODEL" $OC_FLAGS "只回复两个字：收到" > /tmp/probe2.out 2>/tmp/probe2.err
RC=$?
echo "rc=$RC  elapsed=$(( $(date +%s) - T0 ))s"
echo "--- stdout ---"; head -c 500 /tmp/probe2.out
echo; echo "--- stderr(tail) ---"; tail -5 /tmp/probe2.err

echo
echo "== 模型驻留 =="
curl -s -m 5 "$OLLAMA_URL/api/ps" | head -c 300
