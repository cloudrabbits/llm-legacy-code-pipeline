#!/usr/bin/env bash
# 生成跨夜恢复摘要（注入次夜首个任务的提示词）
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
NIGHT=0
while [[ $# -gt 0 ]]; do case "$1" in --night) NIGHT="$2"; shift 2;; *) shift;; esac; done
"$PY" "$TOOLS_DIR/lib/report.py" --mode resume --db "$DB" --work "$WORK" --report "$REPORT" --night "$NIGHT"
