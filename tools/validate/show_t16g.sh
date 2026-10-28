#!/usr/bin/env bash
LOG="/home/violet/nightly/logs/val-t16g.log"
echo "=== run.log (T16 相关) ==="
grep -a -E "T16|patches|docs/patches" /home/violet/nightly/logs/2026-10-28/run.log | tail -10
echo "=== val-t16g.log 尾部 ==="
tail -20 "$LOG"
echo "=== 实际存在的产品文件 mtime ==="
ls -l --time-style=+%H:%M /home/violet/nightly/work/patches/p0-001.diff /home/violet/nightly/work/docs/patches/p0-001.md 2>/dev/null
