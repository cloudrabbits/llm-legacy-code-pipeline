#!/usr/bin/env bash
# 停掉旧进程 -> 用修好的 load-queue 刷新验收规则 -> 复位失败分片 -> 继续跑
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

systemctl stop val-night2 >/dev/null 2>&1 || true
pkill -KILL -f "opencode run" 2>/dev/null || true
pkill -KILL -f "run_chunk.sh" 2>/dev/null || true
pkill -KILL -f "nightly.sh" 2>/dev/null || true
sleep 2

echo "== 刷新队列元数据（不覆盖进度） =="
db load-queue --queue "$QUEUE" --taskdir "$TASKDIR"
echo "-- 现有验收规则 --"
db sql --q "SELECT id,check_rule FROM task ORDER BY id"

echo "== 复位失败分片 =="
db reset-running
db sql --write --q "UPDATE chunk SET status='pending', attempt=0 WHERE id IN ('T03#1','T04#1','T08#1');" >/dev/null
db sql --write --q "UPDATE task SET status='pending' WHERE id IN ('T03','T04','T08');" >/dev/null
db stats

echo "== 继续跑 =="
timeout 7200 bash "$NIGHTLY/nightly.sh" --no-preflight 2>&1 | tail -45

echo
echo "########## 最终状态 $(date '+%F %T') ##########"
db stats
db sql --q "SELECT id,status,chars_out,seconds FROM chunk ORDER BY id;"
echo "-- 产物 --"
find "$WORK/docs" "$WORK/patches" -type f 2>/dev/null | sort | while read -r f; do
  printf "%8d  %s\n" "$(wc -c < "$f")" "${f#$WORK/}"
done
