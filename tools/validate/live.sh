#!/usr/bin/env bash
# 运行期实时检查（不依赖日志缓冲）：分片状态 / 原始输出增长 / 产物
ROOT="${ROOT:-$HOME/nightly}"
DB="$ROOT/state.db"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"
echo "=== out/ ==="
ls -l "$ROOT/out" 2>/dev/null || echo "(empty)"
echo "=== run/ ==="
ls -l "$ROOT/run" 2>/dev/null || echo "(empty)"
if [[ -f "$ROOT/run/current.chunk" ]]; then
  echo "current chunk: $(cat "$ROOT/run/current.chunk")"
  R=$(cat "$ROOT/run/current.raw" 2>/dev/null)
  [[ -n "$R" && -f "$R" ]] && echo "raw size: $(wc -c < "$R") bytes  mtime=$(stat -c %y "$R" | cut -c1-19)"
fi
echo "=== chunk status ==="
python3 "$TOOLS" --db "$DB" sql --q "SELECT id,status,attempt,chars_out,seconds FROM chunk ORDER BY id" 2>&1 | head -20
echo "=== work/docs ==="
find "$ROOT/work/docs" "$ROOT/work/patches" -type f 2>/dev/null | head -10
echo "=== work size ==="
du -sh "$ROOT/work" 2>/dev/null
