#!/usr/bin/env bash
# 重跑 T16（补丁草稿），并验证 git apply --check 是否在正确的仓库根执行
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIGHTLY="$HERE/../nightly"
source "$NIGHTLY/env.sh"
export MODEL="local-ollama/qwen3.6-35B-A3B-90k"
export OLLAMA_TAG="qwen3.6-35B-A3B-90k:latest"
export WARM_MODEL="qwen3.6-35B-A3B-90k"
export NUM_CTX="90000"
export LLM_MODE="direct"
export TOOL_MODE="text"
export DEADLINE_NIGHT=99
export HARD_STOP="$(date -d '+3 hours' +%H:%M)"

rm -f "$ROOT/nightly.lock"
db sql --write --q "UPDATE chunk SET status='pending', attempt=0 WHERE id='T16#1';" >/dev/null
db sql --write --q "UPDATE task SET status='pending' WHERE id='T16';" >/dev/null

timeout 1800 bash "$NIGHTLY/nightly.sh" --only T16 --no-preflight 2>&1 | tail -20

echo
echo "== 结果 =="
db sql --q "SELECT id,status,characters FROM chunk WHERE id='T16#1';" 2>/dev/null
db sql --q "SELECT id,status,chars_out FROM chunk WHERE id='T16#1';"
echo "-- 直接判定（在仓库根）--"
python3 "$NIGHTLY/lib/verify.py" "$WORK/patches/p0-001.diff" "size>200|gitapply" --repo "$WORK"; echo "rc=$?"
echo "-- 补丁头 --"
head -14 "$WORK/patches/p0-001.diff" 2>/dev/null
