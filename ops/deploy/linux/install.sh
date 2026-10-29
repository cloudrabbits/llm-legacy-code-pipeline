#!/usr/bin/env bash
#
# 注册夜间分析流水线（ops/deploy/register_task.ps1 的 Linux 版）。
#
# 与 Windows 侧的对应关系：
#   schtasks /Create /XML task_definition.xml  ->  渲染单元模板到 systemd 单元目录
#   注册后 /DISABLE（-Manual）                 ->  只安装，不 enable timer（手动 systemctl start）
#   /ENABLE + 每日 01:00（-Schedule）          ->  systemctl enable --now legacy-nightly.timer
#
# 用法：
#   sudo ops/deploy/linux/install.sh --project /data/supermarketmanager \
#        --profile ollama_qwen38 --manual
#
#   sudo ops/deploy/linux/install.sh --project /data/supermarketmanager \
#        --profile ollama_qwen38 --schedule --start 01:00 --duration 8h
#
#   ops/deploy/linux/install.sh --project /data/supermarketmanager --user   # 无 root 时
#   sudo ops/deploy/linux/install.sh --uninstall
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 本脚本位于 <repo>/ops/deploy/linux/，故仓库根在上三级
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

# shellcheck disable=SC1091
source "$HERE/common.sh"

PROJECT=""
PROFILE="ollama_qwen38"
PYTHON_BIN="python3"
MODE="manual"
START_TIME="01:00"
DURATION="8h"
RUN_AS=""
USER_MODE=0
WANT_WATCHDOG=0
WITH_OLLAMA=0
OLLAMA_BIN="/usr/local/bin/ollama"
OLLAMA_USER="ollama"
UNINSTALL=0

die() { printf '[install] 错误：%s\n' "$*" >&2; exit 1; }

# _project_slug 见 common.sh（shell 侧唯一实现）
info() { printf '[install] %s\n' "$*"; }

usage() {
    sed -n '2,20p' "$0"
    cat <<'TXT'

必选：
  --project PATH        被分析项目根目录（写入 nightly.env 的 PROJECT）
可选：
  --profile NAME        后端画像名，默认 ollama_qwen38
  --manual              只安装不启用定时器（默认，推荐首夜）
  --schedule            安装并启用每日定时
  --start HH:MM         每日启动时刻，默认 01:00
  --duration SPAN       最长运行时长，默认 8h（systemd 时间跨度：8h / 480m / infinity）
  --run-as USER         以该用户运行（系统级单元，默认 root）
  --user                安装为 systemd --user 单元（~/.config/systemd/user，无需 root）
  --watchdog            同时启用看门狗定时器（--schedule 时自动启用）
  --with-ollama         同时安装 Ollama 服务单元
  --ollama-bin PATH     ollama 可执行文件，默认 /usr/local/bin/ollama
  --ollama-user NAME    运行 ollama 的用户，默认 ollama
  --python PATH         python 解释器，默认 python3
  --uninstall           卸载已安装的单元
  -h, --help            显示本帮助
TXT
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)     PROJECT="${2:?--project 需要一个路径}"; shift 2 ;;
        --profile)     PROFILE="$2"; shift 2 ;;
        --python)      PYTHON_BIN="$2"; shift 2 ;;
        --manual)      MODE="manual"; shift ;;
        --schedule)    MODE="schedule"; shift ;;
        --start)       START_TIME="$2"; shift 2 ;;
        --duration)    DURATION="$2"; shift 2 ;;
        --run-as)      RUN_AS="$2"; shift 2 ;;
        --user)        USER_MODE=1; shift ;;
        --watchdog)    WANT_WATCHDOG=1; shift ;;
        --with-ollama) WITH_OLLAMA=1; shift ;;
        --ollama-bin)  OLLAMA_BIN="$2"; shift 2 ;;
        --ollama-user) OLLAMA_USER="$2"; shift 2 ;;
        --uninstall)   UNINSTALL=1; shift ;;
        -h|--help)     usage; exit 0 ;;
        *) die "未知参数: $1（用 --help 看用法）" ;;
    esac
done

[[ -f "$REPO_ROOT/orchestrator.py" ]] || die "RepoRoot 看起来不对（缺少 orchestrator.py）: $REPO_ROOT"

# ---------------------------------------------------------------- 单元目录 / systemctl
if (( USER_MODE )); then
    UNIT_DIR="$HOME/.config/systemd/user"
    SYSCTL="systemctl --user"
    SYSTEMD_MODE="user"
    [[ -z "$RUN_AS" ]] || die "--user 模式下不能再指定 --run-as（user 单元以登录用户运行）"
else
    UNIT_DIR="/etc/systemd/system"
    SYSCTL="systemctl"
    SYSTEMD_MODE="system"
    (( EUID == 0 )) || die "系统级安装需要 root，请加 sudo；或改用 --user 安装为用户单元"
fi

units_disable_stop() {
    for u in legacy-nightly.timer legacy-watchdog.timer legacy-nightly.service ollama.service; do
        [[ -f "$UNIT_DIR/$u" ]] || continue
        $SYSCTL disable --now "$u" >/dev/null 2>&1 || true
        rm -f "$UNIT_DIR/$u"
        info "已移除 $UNIT_DIR/$u"
    done
}

if (( UNINSTALL )); then
    units_disable_stop
    $SYSCTL daemon-reload
    info "卸载完成。配置 $HERE/nightly.env 已保留，可手动删除。"
    exit 0
fi

# ---------------------------------------------------------------- 参数校验
[[ -n "$PROJECT" ]] || die "缺少 --project（被分析项目根目录）"
[[ -d "$PROJECT" ]] || info "警告：$PROJECT 当前不存在或不是目录，仍会写入配置，请确认路径"
[[ "$START_TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || die "--start 必须是 HH:MM（24 小时制），当前：$START_TIME"
[[ "$DURATION" =~ ^(infinity|[0-9]+(s|m|h|d|w)?)$ ]] || die "--duration 必须是 systemd 时间跨度（如 8h / 480m / infinity），当前：$DURATION"
# systemd EnvironmentFile 不支持带空格的值（会静默截断）
if [[ "$PROJECT" == *" "* || "$REPO_ROOT" == *" "* ]]; then
    die "路径不能含空格（systemd EnvironmentFile 不支持）：PROJECT=$PROJECT REPO_ROOT=$REPO_ROOT"
fi

mkdir -p "$UNIT_DIR"

# ---------------------------------------------------------------- 生成 nightly.env
# 同时作为 systemd EnvironmentFile 与两个脚本的 source 目标
cat >"$HERE/nightly.env" <<EOF
# 由 ops/deploy/linux/install.sh 生成（$(date '+%Y-%m-%d %H:%M:%S')）
REPO_ROOT=$REPO_ROOT
PROJECT=$PROJECT
PROFILE=$PROFILE
PYTHON=$PYTHON_BIN
LOCK_FILE=$REPO_ROOT/runtime/$(_project_slug "$PROJECT")/state/nightly.lock
HEARTBEAT_PATH=$REPO_ROOT/runtime/$(_project_slug "$PROJECT")/state/heartbeat.json
WATCHDOG_THRESHOLD_SEC=600
WATCHDOG_SERVICE=legacy-nightly.service
SYSTEMD_MODE=$SYSTEMD_MODE
# 额外参数（如 --verbose / --max-tasks 3），按需取消注释
# NIGHTLY_EXTRA_ARGS=--verbose
EOF
info "已写入 $HERE/nightly.env（PROJECT=$PROJECT PROFILE=$PROFILE）"

# ---------------------------------------------------------------- 渲染并安装单元
render() {
    local src="$HERE/$1" dst="$UNIT_DIR/$2"
    sed -e "s|{{REPO_ROOT}}|${REPO_ROOT}|g" \
        -e "s|{{DURATION_SEC}}|${DURATION}|g" \
        -e "s|{{START_TIME}}|${START_TIME}|g" \
        -e "s|{{RUN_AS}}|${RUN_AS}|g" \
        -e "s|{{OLLAMA_BIN}}|${OLLAMA_BIN}|g" \
        -e "s|{{OLLAMA_USER}}|${OLLAMA_USER}|g" \
        "$src" >"$dst"
    # 未指定 --run-as 时删掉空的 User= 行
    if [[ -z "$RUN_AS" ]]; then
        sed -i '/^User=$/d' "$dst"
    fi
    chmod 0644 "$dst"
    info "已安装 $dst"
}

# 仓库若从 Windows 侧 clone 过来，可执行位可能没带着，这里统一补一次
chmod 0755 "$HERE/run_nightly.sh" "$HERE/watchdog.sh" "$HERE/install.sh"
if [[ -f "$REPO_ROOT/jlp.sh" ]]; then
    chmod 0755 "$REPO_ROOT/jlp.sh"
fi

render legacy-nightly.service  legacy-nightly.service
render legacy-nightly.timer    legacy-nightly.timer
render legacy-watchdog.service legacy-watchdog.service
render legacy-watchdog.timer   legacy-watchdog.timer
if (( WITH_OLLAMA )); then
    render ollama.service ollama.service
fi

$SYSCTL daemon-reload

# ---------------------------------------------------------------- 启用策略
if [[ "$MODE" == "schedule" ]]; then
    $SYSCTL enable --now legacy-nightly.timer
    info "已启用每日 ${START_TIME} 定时（最长 ${DURATION}）"
    WANT_WATCHDOG=1
else
    $SYSCTL disable --now legacy-nightly.timer >/dev/null 2>&1 || true
    info "已安装但定时器保持 disabled（等价 Windows 的 Enabled=false）"
fi

if (( WANT_WATCHDOG )); then
    $SYSCTL enable --now legacy-watchdog.timer
    info "已启用看门狗定时器（每 5 分钟检查心跳）"
else
    $SYSCTL disable --now legacy-watchdog.timer >/dev/null 2>&1 || true
fi

if (( WITH_OLLAMA )); then
    $SYSCTL enable --now ollama.service
    info "已启用 Ollama 服务（${OLLAMA_BIN} serve，用户 ${OLLAMA_USER}）"
fi

# ---------------------------------------------------------------- 版本提示
if command -v systemctl >/dev/null 2>&1; then
    ver="$(systemctl --version 2>/dev/null | head -1 | awk '{print $2}')"
    # 只在能解析出纯数字版本号时才比较，避免 $(( )) 吃到非数字
    if [[ "$ver" =~ ^[0-9]+$ ]] && (( ver < 240 )); then
        info "警告：systemd ${ver} < 240，不支持 StandardOutput=append:，日志重定向会失效。"
        info "      请把 legacy-nightly.service 里的 append: 改成 >> 形式的 wrapper。"
    fi
fi

if (( USER_MODE )); then
    info "提示：用户单元默认随会话退出而停止，服务器场景请执行：sudo loginctl enable-linger ${USER:-$(id -un)}"
fi

JOURNAL_USER=""
UNINSTALL_SUFFIX=""
if [[ "$SYSTEMD_MODE" == "user" ]]; then
    JOURNAL_USER="--user "
    UNINSTALL_SUFFIX=" --user"
fi

cat <<TXT

常用命令（${SYSCTL}）：
  手动跑   : ${SYSCTL} start legacy-nightly
  停       : ${SYSCTL} stop legacy-nightly
  看状态   : ${SYSCTL} status legacy-nightly
  看日志   : journalctl ${JOURNAL_USER}-u legacy-nightly -f
  看定时器 : ${SYSCTL} list-timers 'legacy-*'
  看门狗   : ${SYSCTL} start legacy-watchdog        # 手动检查一次心跳
  卸载     : sudo $HERE/install.sh --uninstall${UNINSTALL_SUFFIX}

顺带确认：
  tail -f $REPO_ROOT/logs/orchestrator.stdout.log
  cat $REPO_ROOT/runtime/$(_project_slug "$PROJECT")/state/heartbeat.json
TXT
