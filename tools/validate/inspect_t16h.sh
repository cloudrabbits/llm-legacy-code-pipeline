#!/usr/bin/env bash
ROOT="/home/violet/nightly"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"
OUT="$ROOT/work/docs/patches/p0-001.md"
echo "== 分片状态 =="
python3 "$TOOLS" --db "$ROOT/state.db" sql --q "SELECT id,status,chars_out,seconds FROM chunk WHERE id='T16#1';"
echo "== 产物落盘位置 =="
ls -l "$ROOT/work/docs/patches/p0-001.md" 2>/dev/null && echo "✓ 新路径" || echo "✗ 未落到 docs/patches/"
echo "== 证据行数 (文件:行号 | ...) =="
echo "$(grep -cE '^[[:space:]]*[A-Za-z0-9_./-]+:[0-9]+[[:space:]]*\|' "$OUT" 2>/dev/null)"
echo "== 头 26 行 =="
head -26 "$OUT" 2>/dev/null
