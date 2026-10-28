#!/usr/bin/env bash
# 防重入：flock + stale lock 清理（上次崩溃残留的 pid 会被自动清除）
LOCK_FILE="${LOCK_FILE:-$ROOT/nightly.lock}"

acquire_lock() {
  exec 9>"$LOCK_FILE"
  if [[ -s "$LOCK_FILE" ]]; then
    local pid; pid="$(cat "$LOCK_FILE" 2>/dev/null || echo 0)"
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      log_warn "清理 stale lock (pid=$pid 已不存在)"
      : > "$LOCK_FILE"
    fi
  fi
  if ! flock -n 9; then
    log_err "已有实例在运行（锁 $LOCK_FILE），本次退出"
    return 1
  fi
  echo $$ > "$LOCK_FILE"
  trap 'release_lock' EXIT
  return 0
}

release_lock() {
  flock -u 9 2>/dev/null || true
  rm -f "$LOCK_FILE" 2>/dev/null || true
}
