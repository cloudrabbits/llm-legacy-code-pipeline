#!/usr/bin/env bash
ROOT="${ROOT:-$HOME/nightly}"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"
echo "=== 判定 ==="
grep -a "直接判定" -A2 "$HOME/nightly/logs/val-t16d.log" | head -5
echo "=== 分片状态 ==="
python3 "$TOOLS" --db "$ROOT/state.db" sql --q "SELECT id,status,chars_out,seconds FROM chunk WHERE id='T16#1'"
echo "=== 补丁文件 ==="
ls -l "$ROOT/work/patches/" 2>/dev/null
wc -lc "$ROOT/work/patches/p0-001.diff" 2>/dev/null
echo "=== 行尾与结构 ==="
head -12 "$ROOT/work/patches/p0-001.diff" 2>/dev/null | cat -A | cut -c1-90
