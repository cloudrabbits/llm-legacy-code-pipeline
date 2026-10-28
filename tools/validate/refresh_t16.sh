#!/usr/bin/env bash
PY="/usr/bin/python3"
DB="/home/violet/nightly/state.db"
NIGHTLY="/mnt/d/IdeaProjects/LibrarySystem/tools/nightly"
"$PY" -m py_compile "$NIGHTLY/lib/db.py" && echo PY_OK
"$PY" "$NIGHTLY/lib/db.py" --db "$DB" load-queue --queue "$NIGHTLY/queue.tsv" --taskdir "$NIGHTLY/tasks"
echo "== chunk 输出路径 =="
"$PY" "$NIGHTLY/lib/db.py" --db "$DB" sql --q "SELECT id,output_part FROM chunk WHERE id='T16#1'"
