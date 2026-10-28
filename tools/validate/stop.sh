#!/usr/bin/env bash
# 现场检查 + 止损：查看卡死进程、终止 opencode/编排器、复位状态
ROOT="${ROOT:-$HOME/nightly}"
DB="$ROOT/state.db"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"

echo "=== 相关进程 ==="
ps -ef | grep -E "opencode|run_chunk|nightly|step3" | grep -v grep | head -10

echo "=== 单元 ==="
systemctl list-units --all "val-*" --no-legend 2>/dev/null | head -8

if [[ "${1:-}" == "kill" ]]; then
  echo "=== 终止 ==="
  pkill -TERM -f "opencode run" 2>/dev/null
  sleep 5
  pkill -KILL -f "opencode run" 2>/dev/null
  pkill -KILL -f "run_chunk.sh" 2>/dev/null
  pkill -KILL -f "nightly.sh" 2>/dev/null
  systemctl stop val-t01b 2>/dev/null
  echo "done"
  python3 "$TOOLS" --db "$DB" reset-running 2>&1
  python3 "$TOOLS" --db "$DB" sql --q "SELECT id,status,attempt FROM chunk WHERE id LIKE 'T01%'" 2>&1
fi
