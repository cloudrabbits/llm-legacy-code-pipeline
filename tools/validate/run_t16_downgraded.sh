#!/usr/bin/env bash
# 验证 T16 降级档：刷新队列元数据 → 复位 T16 → 用编排器跑 → 核对产物与验收
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
# 1) 用最新 queue.tsv 刷新（含 T16 的 output/check 降级）
db load-queue --queue "$QUEUE" --taskdir "$TASKDIR" >/dev/null
# 2) 复位 T16 为可重跑
db sql --write --q "UPDATE chunk SET status='pending', attempt=0 WHERE id='T16#1';" >/dev/null
db sql --write --q "UPDATE task SET status='pending' WHERE id='T16';" >/dev/null
echo "== T16 元数据 =="
db sql --q "SELECT id,output,check_rule FROM task WHERE id='T16'"

# 3) 跑 T16（不预检，直达模型）
timeout 1200 bash "$NIGHTLY/nightly.sh" --only T16 --no-preflight --skip-sync 2>&1 | tail -8

echo
echo "== 结果 =="
db sql --q "SELECT id,status,chars_out,seconds FROM chunk WHERE id='T16#1';"
echo "-- 产物头（应为 Markdown 文档，含 文件:行号 证据行）--"
OUT="$WORK/docs/patches/p0-001.md"
ls -l "$OUT" 2>/dev/null
echo "  证据行数: $(grep -cE '^[[:space:]]*[A-Za-z0-9_./-]+:[0-9]+[[:space:]]*\|' "$OUT" 2>/dev/null)"
head -16 "$OUT" 2>/dev/null
