#!/usr/bin/env bash
#
# 夜间流水线单实例启动器（由 legacy-nightly.service 调用）。
#
# 与 Windows 侧 task_definition.xml 的对应关系：
#   MultipleInstancesPolicy=IgnoreNew  ->  本脚本的 flock -n（已有实例在跑则直接退出 0）
#   WorkingDirectory={{REPO_ROOT}}     ->  cd "$REPO_ROOT"
#   >> logs/orchestrator.stdout.log    ->  unit 里的 StandardOutput=append:
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 本脚本位于 <repo>/ops/deploy/linux/，故仓库根在上三级
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

# shellcheck disable=SC1091
source "$HERE/common.sh"

# nightly.env 由 install.sh 生成，同时作为 systemd 的 EnvironmentFile。
# 外部传入优先（systemd drop-in 的 Environment=、手动 export），nightly.env 只作兜底，
# 因此先记下外部值，source 之后再回填。
_ext_project="${PROJECT:-}"
_ext_profile="${PROFILE:-}"
_ext_python="${PYTHON:-}"
_ext_args="${NIGHTLY_EXTRA_ARGS:-}"

if [[ -f "$HERE/nightly.env" ]]; then
    # shellcheck disable=SC1091
    source "$HERE/nightly.env"
fi

PROJECT="${_ext_project:-${PROJECT:-}}"
PROFILE="${_ext_profile:-${PROFILE:-ollama_qwen38}}"
PYTHON="${_ext_python:-${PYTHON:-python3}}"
NIGHTLY_EXTRA_ARGS="${_ext_args:-${NIGHTLY_EXTRA_ARGS:-}}"

: "${PROJECT:?PROJECT 未配置，请先运行 ops/deploy/linux/install.sh}"

# project_slug 的唯一实现见 pipeline/util.py；shell 侧等价实现见 common.sh
RUNTIME_SLUG="$(_project_slug "$PROJECT")"

# 单实例锁按项目隔离，避免不同项目共用同一 runtime 时互相阻塞
LOCK_FILE="${LOCK_FILE:-$REPO_ROOT/runtime/$RUNTIME_SLUG/state/nightly.lock}"
LOCK_DIR="$(dirname "$LOCK_FILE")"

mkdir -p "$LOCK_DIR" "$REPO_ROOT/logs"
cd "$REPO_ROOT"

# 单实例：以 flock 持有非阻塞锁，锁被占用说明上一夜还没跑完，本次跳过
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        printf '%s [nightly] 已有实例在跑（锁 %s），本次跳过\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$LOCK_FILE"
        exit 0
    fi
else
    # flock 来自 util-linux，主流发行版都有；真没有时宁可跑，也不要永远不跑
    printf '%s [nightly] 警告：flock 不可用，跳过单实例保护（建议安装 util-linux）\n' \
        "$(date '+%Y-%m-%d %H:%M:%S')"
fi

printf '%s [nightly] start project=%s profile=%s pid=%s\n' \
    "$(date '+%Y-%m-%d %H:%M:%S')" "$PROJECT" "$PROFILE" "$$"

# shellcheck disable=SC2086
"$PYTHON" orchestrator.py --project "$PROJECT" --profile "$PROFILE" $NIGHTLY_EXTRA_ARGS
code=$?

# 退出码语义见 orchestrator.py：0 成功 / 2 时间窗耗尽（正常收尾）/ 3 失败
printf '%s [nightly] exit=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$code"
exit "$code"
