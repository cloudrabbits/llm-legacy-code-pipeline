#!/usr/bin/env bash
# 仅检查 T16 产物与状态（不重跑）
ROOT="${ROOT:-$HOME/nightly}"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"
OUT="$ROOT/work/docs/patches/p0-001.md"
echo "== 分片状态 =="
python3 "$TOOLS" --db "$ROOT/state.db" sql --q "SELECT id,status,chars_out,seconds FROM chunk WHERE id='T16#1';"
echo "== 产物 =="
ls -l "$OUT" 2>/dev/null
echo "证据行数: $(grep -cE '^[[:space:]]*[A-Za-z0-9_./-]+:[0-9]+[[:space:]]*\|' "$OUT" 2>/dev/null)"
echo "--- 头 22 行 ---"
head -22 "$OUT" 2>/dev/null
