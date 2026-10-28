#!/usr/bin/env bash
#
# 编排器看门狗（tools/watchdog.ps1 的 Linux 版）。
#
# 行为与 Windows 版一致：
#   * 心跳由 orchestrator.py 每 30s 原子写一次 runtime/state/heartbeat.json；
#   * 默认只检查一次，由 systemd timer（等价 Windows 的「每 5 分钟计划任务」）调起，
#     避免自己变成常驻进程；加 --loop 可常驻（容器/无 systemd 场景）；
#   * 心跳文件不存在 = 从未启动过，不做处理，避免无限重启；
#   * 心跳不可解析 = 按超时处理。
#
# 用法：
#   tools/deploy/linux/watchdog.sh                 # 检查一次
#   tools/deploy/linux/watchdog.sh --loop          # 常驻，每 300s 检查一次
#   tools/deploy/linux/watchdog.sh --loop --interval 60
#   tools/deploy/linux/watchdog.sh --dry-run       # 只打印判断，不杀不重启
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 本脚本位于 <repo>/tools/deploy/linux/，故仓库根在上三级
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

if [[ -f "$HERE/nightly.env" ]]; then
    # shellcheck disable=SC1091
    source "$HERE/nightly.env"
fi

HEARTBEAT_PATH="${HEARTBEAT_PATH:-$REPO_ROOT/runtime/state/heartbeat.json}"
THRESHOLD="${WATCHDOG_THRESHOLD_SEC:-600}"
SERVICE="${WATCHDOG_SERVICE:-legacy-nightly.service}"
PYTHON="${PYTHON:-python3}"
# nightly.env 里写死的 python3 在个别发行版/容器里叫 python，这里做一次兜底
if ! command -v "$PYTHON" >/dev/null 2>&1 && command -v python >/dev/null 2>&1; then
    PYTHON=python
fi
LOG_FILE="$REPO_ROOT/logs/watchdog.log"
LOG_DIR="$(dirname "$LOG_FILE")"

LOOP=0
INTERVAL=300
DRY_RUN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --loop)      LOOP=1; shift ;;
        --interval)  INTERVAL="${2:?--interval 需要一个秒数}"; shift 2 ;;
        --dry-run)   DRY_RUN=1; shift ;;
        -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
        *) printf '未知参数: %s\n' "$1" >&2; exit 2 ;;
    esac
done

mkdir -p "$LOG_DIR"

log() {
    local line
    line="$(printf '%s %s' "$(date '+%Y-%m-%d %H:%M:%S')" "$*")"
    printf '%s\n' "$line" >>"$LOG_FILE"
    printf '%s\n' "$line"
}

check_once() {
    if [[ ! -f "$HEARTBEAT_PATH" ]]; then
        log "心跳文件不存在（$HEARTBEAT_PATH），视为从未启动，跳过。"
        return 0
    fi

    # 心跳是 JSON：{"ts":..., "epoch": <unix 秒, float>, "pid": ...}
    # 用 python3 解析（仓库本来就依赖 Python，避免额外引入 jq 依赖）
    local parsed epoch pid age
    parsed="$("$PYTHON" -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        d = json.load(fh)
    print("%d %d" % (float(d.get("epoch", 0)), int(d.get("pid", 0))))
except Exception:
    print("0 0")
' "$HEARTBEAT_PATH" 2>/dev/null)" || parsed="0 0"
    epoch="${parsed%% *}"
    pid="${parsed##* }"

    if [[ -z "$epoch" || "$epoch" == "0" ]]; then
        log "心跳文件不可解析，按超时处理：$HEARTBEAT_PATH"
        age=$(( THRESHOLD + 1 ))
    else
        age=$(( $(date +%s) - epoch ))
    fi

    if (( age <= THRESHOLD )); then
        log "心跳正常（${age}s <= ${THRESHOLD}s），pid=${pid}"
        return 0
    fi

    log "心跳超时 ${age}s > ${THRESHOLD}s，准备重启编排器。"

    if (( DRY_RUN )); then
        log "[dry-run] 将终止 orchestrator.py 并重启 $SERVICE"
        return 0
    fi

    # 1) 先按心跳里记录的 pid 精确停，再兜底 pkill 清掉所有残留
    if [[ -n "$pid" && "$pid" != "0" ]] && kill -0 "$pid" 2>/dev/null; then
        log "停止僵死进程 pid=${pid}"
        kill -TERM "$pid" 2>/dev/null || true
    fi
    if command -v pkill >/dev/null 2>&1; then
        pkill -f 'orchestrator\.py' 2>/dev/null && log "已 pkill 残留 orchestrator.py 进程" || true
    fi
    sleep 5

    # 2) 重启：优先交给 systemd（与 Windows 侧 Start-Process 等价，且能复用同一套参数）
    local sysctl="systemctl"
    if [[ "${SYSTEMD_MODE:-system}" == "user" ]]; then
        sysctl="systemctl --user"
    fi

    if command -v systemctl >/dev/null 2>&1 && \
       $sysctl list-unit-files "$SERVICE" >/dev/null 2>&1; then
        log "重启：$sysctl start $SERVICE"
        $sysctl start "$SERVICE" || log "systemctl start 失败，退出码 $?"
        return 0
    fi

    # 3) 无 systemd 时直接拉起（容器 / 手动值守场景）
    : "${PROJECT:?PROJECT 未配置，无法重启，请检查 nightly.env}"
    log "重启（无 systemd）：$PYTHON orchestrator.py --project $PROJECT --profile ${PROFILE:-ollama_qwen38}"
    cd "$REPO_ROOT"
    setsid nohup "$PYTHON" orchestrator.py \
        --project "$PROJECT" \
        --profile "${PROFILE:-ollama_qwen38}" \
        >>"$REPO_ROOT/logs/orchestrator.stdout.log" 2>&1 &
    return 0
}

if (( LOOP )); then
    log "看门狗常驻模式启动，每 ${INTERVAL}s 检查一次（pid=$$）"
    while true; do
        check_once || true
        sleep "$INTERVAL"
    done
else
    check_once
fi
