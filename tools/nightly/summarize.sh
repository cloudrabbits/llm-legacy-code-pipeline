#!/usr/bin/env bash
# 汇总：--night N 生成当夜报告；--final 生成跨夜最终报告
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$TOOLS_DIR/lib/log.sh"
NIGHT=0; MODE=night
while [[ $# -gt 0 ]]; do
  case "$1" in --night) NIGHT="$2"; shift 2;; --final) MODE=final; shift;; *) shift;; esac
done
OUT=$("$PY" "$TOOLS_DIR/lib/report.py" --mode "$MODE" --db "$DB" --work "$WORK" --report "$REPORT" --night "$NIGHT")
log_info "报告已生成：$OUT"
