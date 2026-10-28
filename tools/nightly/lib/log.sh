#!/usr/bin/env bash
# 日志：统一写 $LOG/$NIGHT_DATE/run.log，便于跨夜对齐时间点
LOG_DATE="${LOG_DATE:-$(date +%F)}"
mkdir -p "$LOG/$LOG_DATE"

log() {
  printf '%s [%s] %s\n' "$(date '+%F %T')" "${1^^}" "${2:-}" | tee -a "$LOG/$LOG_DATE/run.log" >&2
}
log_info() { log info "$*"; }
log_warn() { log warn "$*"; }
log_err()  { log error "$*"; }

# 分片专用日志（模型原始输出之外的编排信息）
chunk_log() {
  printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG/$LOG_DATE/${CURRENT_CHUNK:-none}.log" 2>/dev/null || true
}
