#!/usr/bin/env bash
# 校验提示词装配是否正确（任务书必须非空），不调用模型
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nightly/env.sh"
export MODEL="local-ollama/qwen3.6-35B-A3B-90k"

cd "$WORK" 2>/dev/null || { mkdir -p "$WORK"; cd "$WORK"; }
mkdir -p "$HANDOFF_DIR/T01" "$CONTEXT_DIR"
python3 "$TOOLS_DIR/lib/db.py" --db "$DB" init >/dev/null 2>&1
python3 "$TOOLS_DIR/lib/db.py" --db "$DB" load-queue --queue "$QUEUE" --taskdir "$TASKDIR" >/dev/null 2>&1

echo "== 解析任务书路径 =="
for p in "tasks/T01.md" "T01.md"; do
  for c in "$TASKDIR/$(basename "$p")" "$TASKDIR/$p" "$TOOLS_DIR/$p"; do
    [[ -f "$c" ]] && echo "  $p -> $c (OK)" && break
  done
done

echo "== 生成提示词（dry-run） =="
DRY_RUN=1 bash "$TOOLS_DIR/run_chunk.sh" --chunk "T01#1" --task T01 --seq 1 \
  --range '*' --out docs/arch/01-inventory.md --prompt "tasks/T01.md" \
  --timeout 20 --check "size>2000" --night 1 2>&1 | tail -3

P="$STATE/prompt-T01_1.md"
if [[ -f "$P" ]]; then
  echo "== 提示词统计 =="
  echo "  大小: $(wc -c < "$P") 字节  约 $(($(wc -c < "$P")/3)) tokens"
  echo "  含任务书标题: $(grep -c '代码清单与模块地图' "$P")"
  echo "  含【本次任务书】: $(grep -c '本次任务书' "$P")"
  echo "== 任务书片段（【本次任务书】之后 12 行） =="
  sed -n '/【本次任务书】/,+12p' "$P"
else
  echo "!! 提示词未生成"
fi
