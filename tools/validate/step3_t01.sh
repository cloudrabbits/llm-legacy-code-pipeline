#!/usr/bin/env bash
# 验证第 3 步：真实项目端到端（LibrarySystem + T01 分片）
# 验证：rsync 同步 → bootstrap 拼装 → OpenCode 调用 → 产物抽取 → 验收 → 事实入库
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIGHTLY="$HERE/../nightly"
source "$NIGHTLY/env.sh"
export MODEL="local-ollama/qwen3.6-35B-A3B-90k"
export OLLAMA_TAG="qwen3.6-35B-A3B-90k:latest"
export WARM_MODEL="qwen3.6-35B-A3B-90k"
export NUM_CTX="90000"

ts() { date '+%F %T'; }
echo "########## T01 end-to-end  $(ts) ##########"
echo "MODEL=$MODEL  ROOT=$ROOT  SRC=$SRC"
echo "WORK=$WORK"

db init >/dev/null 2>&1
db load-queue --queue "$QUEUE" --taskdir "$TASKDIR" >/dev/null 2>&1
# 复位：上次残留的 running / 半成品产物
db reset-running >/dev/null 2>&1
db sql --write --q "UPDATE chunk SET status='pending', attempt=0 WHERE id='T01#1';" >/dev/null 2>&1
db sql --write --q "UPDATE task SET status='pending' WHERE id='T01';" >/dev/null 2>&1
rm -f "$WORK/docs/arch/01-inventory.md" "$OUT/T01_1.raw.md"
echo "-- 队列状态 --"; db stats

echo
echo "-- 启动 nightly --only T01 --"
timeout 3600 bash "$NIGHTLY/nightly.sh" --only T01 --no-preflight 2>&1 | tail -40

echo
echo "########## 产物核对  $(ts) ##########"
F="$WORK/docs/arch/01-inventory.md"
if [[ -f "$F" ]]; then
  echo "OK  产物: $F"
  echo "     $(wc -c < "$F") bytes / $(wc -l < "$F") lines"
  echo "----- 前 30 行 -----"
  head -30 "$F"
  echo "----- 末尾 5 行 -----"
  tail -5 "$F"
  echo
  echo "-- 验收规则：size>2000|heading:'^## ' --"
  python3 "$NIGHTLY/lib/verify.py" "$F" "size>2000|heading:'^## '"; echo "verify_rc=$?"
else
  echo "FAIL 产物缺失: $F"
  echo "-- 工作副本 --"; ls -R "$WORK" 2>/dev/null | head -20
fi

echo
echo "-- 事实库 --"
db sql --q "SELECT COUNT(*) FROM fact;"
db sql --q "SELECT pk, substr(claim,1,60) FROM fact LIMIT 8;"

echo
echo "-- 分片与任务状态 --"
db sql --q "SELECT id,status,attempt,chars_out,seconds FROM chunk ORDER BY id;"
db sql --q "SELECT id,status,last_error FROM task WHERE id='T01';"

echo
echo "-- 原始输出（前 40 行）--"
RAW="$OUT/T01_1.raw.md"
[[ -f "$RAW" ]] && head -40 "$RAW" || echo "(no raw output)"
echo
echo "########## done  $(ts) ##########"
