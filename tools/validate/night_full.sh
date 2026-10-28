#!/usr/bin/env bash
# 完整夜间跑：把剩余分片一次跑完（模拟"一个夜晚的完整队列"）
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
export DEADLINE_NIGHT=9          # 本次验证不触发收尾档
export HARD_STOP="$(date -d '+3 hours' +%H:%M)"

echo "########## FULL NIGHT $(date '+%F %T') ##########"
# 把因收尾档被跳过的两个分片恢复为 pending（它们其实从未尝试）
db sql --write --q "UPDATE chunk SET status='pending', attempt=0 WHERE id IN ('T09#1','T16#1');" >/dev/null 2>&1
db sql --write --q "UPDATE task SET status='pending' WHERE id IN ('T09','T16');" >/dev/null 2>&1

db stats

timeout 10800 bash "$NIGHTLY/nightly.sh" --no-preflight 2>&1 | tail -60

echo
echo "########## 结果核对 $(date '+%F %T') ##########"
db stats
echo "-- 分片 --"
db sql --q "SELECT id,status,chars_out,seconds FROM chunk ORDER BY id;"
echo "-- 产物 --"
find "$WORK/docs" "$WORK/patches" -type f 2>/dev/null | sort | while read -r f; do
  printf "%8d  %s\n" "$(wc -c < "$f")" "${f#$WORK/}"
done
echo "-- 报告 --"
ls -1 "$REPORT" 2>/dev/null
echo "-- 事实 --"
db sql --q "SELECT COUNT(*) FROM fact;"
