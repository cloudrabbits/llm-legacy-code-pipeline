#!/usr/bin/env bash
# 清理残留进程并复位 T16，便于后续继续或收尾
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIGHTLY="$HERE/../nightly"
source "$NIGHTLY/env.sh"

systemctl stop val-t16e val-t16d val-t16c val-t16b val-t16 >/dev/null 2>&1
pkill -KILL -f "llm_direct.py" 2>/dev/null
pkill -KILL -f "run_chunk.sh" 2>/dev/null
pkill -KILL -f "nightly.sh" 2>/dev/null
sleep 2
rm -f "$ROOT/nightly.lock"

db reset-running
db sql --write --q "UPDATE chunk SET status='pending', attempt=0 WHERE id='T16#1';" >/dev/null
db sql --write --q "UPDATE task SET status='pending' WHERE id='T16';" >/dev/null
echo "-- 状态 --"
db stats
ps -ef | grep -E "llm_direct|nightly.sh|run_chunk" | grep -v grep | wc -l
