#!/usr/bin/env bash
# 分片合并（纯脚本，不消耗模型、可无限次重跑）：
#   任务全部分片完成后，把 *.partNN.md 合并成队列里声明的最终产物，并补上目录与分片来源说明。
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$TOOLS_DIR/lib/log.sh"

TASK=""
while [[ $# -gt 0 ]]; do case "$1" in --task) TASK="$2"; shift 2;; *) shift;; esac; done
[[ -n "$TASK" ]] || { log_err "merge.sh: 需要 --task"; exit 2; }

OUT=$(db sql --q "SELECT output FROM task WHERE id='$TASK';")
STATUS=$(db sql --q "SELECT status FROM task WHERE id='$TASK';")
[[ -n "$OUT" && "$STATUS" == "done" ]] || exit 0

mapfile -t PARTS < <(db sql --q "SELECT output_part FROM chunk WHERE task_id='$TASK' AND status='done' ORDER BY seq;")
(( ${#PARTS[@]} <= 1 )) && exit 0

TARGET="$WORK/$OUT"
TMP="$TARGET.merge.tmp"
mkdir -p "$(dirname "$TARGET")"
{
  echo "# $(basename "$OUT" .md)（由 ${#PARTS[@]} 个分片合并生成，勿手工编辑分片内容）"
  echo
  echo "> 本文件由 \`merge.sh\` 自动合并生成；分片原文见："
  for p in "${PARTS[@]}"; do echo "> - \`$p\`"; done
  echo
  for p in "${PARTS[@]}"; do
    echo "<!-- part: $p -->"
    [[ -f "$WORK/$p" ]] && cat "$WORK/$p"
    echo
  done
} > "$TMP"
mv -f "$TMP" "$TARGET"
log_info "已合并 ${#PARTS[@]} 个分片 → $OUT"
