#!/usr/bin/env bash
TSV="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/queue.tsv"
DB="/home/violet/nightly/state.db"
TOOLS="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly/lib/db.py"
echo "=== queue.tsv T16 行 ==="
grep -P '^T16\t' "$TSV"
echo "=== DB T16 ==="
python3 "$TOOLS" --db "$DB" sql --q "SELECT id,output,check_rule FROM task WHERE id='T16'"
