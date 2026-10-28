#!/usr/bin/env bash
# 查 T16 为什么没被调度
ROOT="${ROOT:-$HOME/nightly}"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"
echo "=== 日志关键点 ==="
grep -E "执行|完成 ✓|失败|清空|收尾" "$HOME/nightly/logs/val-t16b.log" | tail -8
echo "=== task T15/T16 ==="
python3 "$TOOLS" --db "$ROOT/state.db" sql --q "SELECT id,status,depends,priority FROM task WHERE id IN ('T15','T16')"
echo "=== chunk T16 ==="
python3 "$TOOLS" --db "$ROOT/state.db" sql --q "SELECT id,status,attempt FROM chunk WHERE id='T16#1'"
echo "=== next-chunk (only T16) ==="
python3 "$TOOLS" --db "$ROOT/state.db" next-chunk --night 10 --only-task T16
echo "rc=$?"
