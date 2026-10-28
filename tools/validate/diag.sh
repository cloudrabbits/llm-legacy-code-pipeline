#!/usr/bin/env bash
# 诊断：任务错误、分片错误、最近日志
ROOT="${ROOT:-$HOME/nightly}"
DB="$ROOT/state.db"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"

echo "=== task ==="
python3 "$TOOLS" --db "$DB" sql --q "SELECT id,status,substr(COALESCE(last_error,''),1,120) FROM task ORDER BY id"
echo "=== chunk (failed) ==="
python3 "$TOOLS" --db "$DB" sql --q "SELECT id,status,attempt,substr(COALESCE(last_error,''),1,120) FROM chunk WHERE status IN ('failed')"
echo "=== err 文件 ==="
for f in "$ROOT"/logs/2026-10-28/T03_1.err "$ROOT"/logs/2026-10-28/T04_1.err; do
  [[ -f "$f" ]] && { echo "-- $f --"; tail -c 500 "$f"; echo; }
done
echo "=== 夜间日志尾部 ==="
ls -t "$ROOT"/logs/2026-10-28/ | head -5
tail -12 "$ROOT"/logs/2026-10-28/run.log
