#!/usr/bin/env bash
# 跨夜可靠性混沌测试（验证目标 V7 的自动化部分）
#   ./chaos.sh kill9    启动一小段运行后 kill -9，检查状态是否被正确修复
#   ./chaos.sh term     发送 SIGTERM，检查是否优雅收尾（exit 0，任务标 partial）
#   ./chaos.sh change   修改工作副本源文件后，检查精确失效（stale）
#   ./chaos.sh crash    模拟断电：直接清空 current.* 并置 running，检查启动期修复
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$TOOLS_DIR/lib/log.sh"

S="${1:-kill9}"
case "$S" in
  kill9)
    log_info "场景1：启动运行后 40s 强杀（模拟崩溃）"
    HARD_STOP="$(date -d '+3 minutes' +%H:%M)" bash "$TOOLS_DIR/nightly.sh" --no-preflight &
    NP=$!
    sleep 40
    kill -9 "$NP" 2>/dev/null
    pkill -9 -f "run_chunk.sh" 2>/dev/null
    sleep 2
    log_info "残留状态：$(db sql --q "SELECT COUNT(*) FROM chunk WHERE status='running';") 个 running"
    db reset-running
    db ghosts --work "$WORK"
    log_info "修复后：$(db stats)"
    ;;
  term)
    log_info "场景2：SIGTERM 优雅停止"
    HARD_STOP="$(date -d '+5 minutes' +%H:%M)" bash "$TOOLS_DIR/nightly.sh" --no-preflight &
    NP=$!
    sleep 30
    kill -TERM "$NP" 2>/dev/null
    wait "$NP" 2>/dev/null
    RC=$?
    log_info "nightly 退出码=$RC（期望 0）"
    db sql --q "SELECT night_id,stop_reason FROM run ORDER BY night_id DESC LIMIT 1;"
    ;;
  change)
    log_info "场景3：白天源码变更 → 精确失效"
    F=$(find "$SRC/src" -name '*.java' 2>/dev/null | head -3)
    [[ -z "$F" ]] && { log_warn "未找到源文件，跳过"; exit 0; }
    for f in $F; do printf '\n// touched %s\n' "$(date +%s)" >> "$f"; done
    N=$(( $(db last-night) + 1 ))
    CHANGED=$(db snap-diff --src "$SRC" --night "$N" | "$PY" -c 'import sys,json;print(",".join(json.load(sys.stdin).get("changed",[])))')
    log_info "检测到变更：${CHANGED:0:200}"
    [[ -n "$CHANGED" ]] && db mark-stale --files "$CHANGED"
    db sql --q "SELECT id,status FROM chunk WHERE status='stale' LIMIT 10;"
    ;;
  crash)
    log_info "场景5：模拟断电（置 running 后重启修复）"
    db sql --write --q "UPDATE chunk SET status='running' WHERE status='pending' LIMIT 1;" >/dev/null
    db sql --write --q "UPDATE task SET status='running' WHERE id=(SELECT task_id FROM chunk WHERE status='running' LIMIT 1);" >/dev/null
    log_info "制造 running 状态：$(db sql --q "SELECT COUNT(*) FROM chunk WHERE status='running';")"
    db reset-running
    log_info "修复后：$(db stats)"
    ;;
  *) echo "用法: chaos.sh {kill9|term|change|crash}";;
esac
