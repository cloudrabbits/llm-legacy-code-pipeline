#!/usr/bin/env bash
# 第三段：队列已刷新为放宽后的验收规则，直接把剩余 11 个分片跑完
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
export DEADLINE_NIGHT=9
export HARD_STOP="$(date -d '+2 hours' +%H:%M)"

rm -f "$ROOT/nightly.lock"
echo "########## RUN3 $(date '+%F %T') ##########"
db stats
timeout 7200 bash "$NIGHTLY/nightly.sh" --no-preflight 2>&1 | tail -45

echo
echo "########## 最终状态 $(date '+%F %T') ##########"
db stats
db sql --q "SELECT id,status,chars_out,seconds FROM chunk ORDER BY id;"
echo "-- 产物 --"
find "$WORK/docs" "$WORK/patches" -type f 2>/dev/null | sort | while read -r f; do
  printf "%8d  %s\n" "$(wc -c < "$f")" "${f#$WORK/}"
done
echo "-- 报告 --"; ls -1 "$REPORT" 2>/dev/null
