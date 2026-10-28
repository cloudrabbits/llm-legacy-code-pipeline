#!/usr/bin/env bash
# 跨夜续跑与分片合并的非模型验证（V7 的一部分，秒级完成）
#   1) 造出"第 1 夜已完成 T01 与 T06 两个分片"的状态
#   2) 第 2 夜干跑：已完成分片必须被跳过，依赖 T01 的任务变为可执行
#   3) 分片合并：T06 的 part1/part2 合并为最终产物，且可重复执行（幂等）
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROOT="${ROOT:-/tmp/nightly_resume}"
export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$HERE/../.." && pwd)}"
export SRC="$PROJECT_ROOT"
source "$HERE/env.sh"

rm -rf "$ROOT"
db init >/dev/null
db load-queue --queue "$QUEUE" --taskdir "$TASKDIR" --fresh >/dev/null

# --- 第 1 夜：造出已完成状态 ---
mkdir -p "$WORK/docs/arch"
printf '# 清单\n\n- BookDao.java:1 | 示例结论\n' > "$WORK/docs/arch/01-inventory.md"
db chunk-done --id "T01#1" --night 1 --chars 1200 --seconds 300 >/dev/null
printf 'part1 内容\n' > "$WORK/docs/arch/06-view-layer.part1.md"
printf 'part2 内容\n' > "$WORK/docs/arch/06-view-layer.part2.md"
db chunk-done --id "T06#1" --night 1 >/dev/null
db chunk-done --id "T06#2" --night 1 >/dev/null
echo "第1夜后：$(db stats)"

# --- 合并（可执行两次，验证幂等） ---
bash "$HERE/merge.sh" --task T06
bash "$HERE/merge.sh" --task T06
echo "合并产物大小：$(wc -c < "$WORK/docs/arch/06-view-layer.md") 字节"

# --- 第 2 夜干跑 ---
echo "--- 第2夜干跑清单（T01/T06 应被跳过）---"
DRY_RUN=1 bash "$HERE/nightly.sh" --dry-run --no-preflight --skip-sync 2>&1 \
  | grep -a "dry-run" | sed 's/.*\[dry-run\] //' | head -20
echo "第2夜后：$(db stats)"

# --- 幽灵进度修复 ---
rm -f "$WORK/docs/arch/01-inventory.md"
db ghosts --work "$WORK"
echo "删除产物后（幽灵进度已回退）：$(db sql --q "SELECT status FROM chunk WHERE id='T01#1';")"

# --- 变更失效 ---
printf '\n// touched\n' >> "$PROJECT_ROOT/src/main/java/com/zy/dao/BookDao.java"
N=$(( $(db last-night) + 1 ))
CH=$(db snap-diff --src "$SRC" --night "$N" | "$PY" -c 'import sys,json;print(",".join(json.load(sys.stdin).get("changed",[])))')
echo "检测到的变更：${CH:-无}"
if [[ -n "$CH" ]]; then db mark-stale --files "$CH"; fi
git -C "$PROJECT_ROOT" checkout -- src/main/java/com/zy/dao/BookDao.java 2>/dev/null \
  || sed -i '$ d' "$PROJECT_ROOT/src/main/java/com/zy/dao/BookDao.java"
echo "完成"
