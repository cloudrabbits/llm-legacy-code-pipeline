#!/usr/bin/env bash
# 夜间编排器统一配置。所有脚本通过 source env.sh 获取变量。
# 可被外部环境覆盖，例如：PROJECT_ROOT=~/p200 ROOT=~/nightly ./nightly.sh --resume

export TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------- 路径 ----------
export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$TOOLS_DIR/../.." && pwd)}"   # 被分析项目（Windows 挂载点）
export SRC="${SRC:-$PROJECT_ROOT}"                                       # 源码来源
export ROOT="${ROOT:-$HOME/nightly}"                                     # 运行时目录（尽量放 ext4）
export WORK="$ROOT/work"                                                 # 工作副本
export OUT="$ROOT/out"                                                   # 模型原始输出
export LOG="$ROOT/logs"
export REPORT="$ROOT/reports"
export STATE="$ROOT/run"                                                 # 运行期临时状态（pid/当前分片）
export DB="${DB:-$ROOT/state.db}"
export QUEUE="${QUEUE:-$TOOLS_DIR/queue.tsv}"
export TASKDIR="${TASKDIR:-$TOOLS_DIR/tasks}"
export CONTEXT_DIR="$WORK/ai/context"
export HANDOFF_DIR="$WORK/handoff"
export SCHEMA="$TOOLS_DIR/db/schema.sql"
export PY="${PY:-python3}"

# ---------- 模型 / OpenCode ----------
export OC="${OC:-opencode}"
# OpenCode 侧的 model ref（须与 ~/.config/opencode/opencode.json 中声明的 id 一致）
export MODEL="${MODEL:-local-ollama/qwen3.6-35B-A3B}"
# Ollama 侧的 tag（用于预热与基准；可用环境变量覆盖）
export OLLAMA_TAG="${OLLAMA_TAG:-qwen3.6-35B-A3B:latest}"
export AGENT="${AGENT:-}"                                                # 留空则用 opencode 默认 agent
export OC_FLAGS="${OC_FLAGS:---auto --print-logs --log-level WARN}"
export OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export WARM_MODEL="${WARM_MODEL:-${OLLAMA_TAG%:*}}"                      # Ollama 侧模型名（去掉 :tag）
export NUM_CTX="${NUM_CTX:-90000}"
export MAX_INPUT_TOKENS="${MAX_INPUT_TOKENS:-60000}"                     # 单会话输入硬上限
export CHARS_PER_TOKEN="${CHARS_PER_TOKEN:-3.2}"

# ---------- 时间预算 / 中断协议 ----------
export HARD_STOP="${HARD_STOP:-07:10}"          # 硬停时刻（HH:MM）
export SOFT_BEFORE_MIN="${SOFT_BEFORE_MIN:-30}" # 提前多少分钟不再启动新任务
export CKPT_BEFORE_MIN="${CKPT_BEFORE_MIN:-5}"  # 提前多少分钟进入 CHECKPOINT 级
export MAX_NIGHT_MINUTES="${MAX_NIGHT_MINUTES:-470}"
export DEFAULT_TIMEOUT_MIN="${DEFAULT_TIMEOUT_MIN:-25}"
# 分片输出静止多少分钟判定卡死。
# 实测：opencode 会缓冲 stdout，运行期 raw 文件恒为 0 字节直到结束，
# 因此该值必须大于"最长分片超时"，否则会误杀健康任务；真正的超时由 per-chunk timeout 保证。
export STALL_MIN="${STALL_MIN:-45}"
export RETRY_BACKOFF="${RETRY_BACKOFF:-30,120}" # 重试退避秒数
export DEADLINE_NIGHT="${DEADLINE_NIGHT:-4}"    # 截止夜，进入收尾档

# ---------- 同步（排除噪声） ----------
export RSYNC_EXCLUDES="${RSYNC_EXCLUDES:---exclude=assets/ --exclude=target/ --exclude=build/ --exclude=.git/ --exclude=node_modules/ --exclude=*.jar --exclude=*.class --exclude=*.png --exclude=*.gif --exclude=*.jpg}"

# ---------- 运行模式 ----------
export DRY_RUN="${DRY_RUN:-0}"       # 1=只打印不执行
# auto = 模型写文件优先（依赖工具调用能力）
# text = 正文即产物，从 stdout 的 ```markdown 块抽取（实测 qwen3.6-35B-A3B 会出现
#        "只叙述意图不发工具调用"的失败模式，这类模型必须用 text 档）
export TOOL_MODE="${TOOL_MODE:-text}"

# 调用通道：
#   direct   = 直连 Ollama /api/generate（think=false），上下文由脚本预取，实测最稳
#   opencode = 走 OpenCode agent（可用工具自主读文件，但实测该模型会"叙述意图不执行"）
export LLM_MODE="${LLM_MODE:-direct}"
export MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-3500}"
export LLM_THINK="${LLM_THINK:-false}"   # 实测开启思维链会吃掉全部输出预算

mkdir -p "$ROOT" "$WORK" "$OUT" "$LOG" "$REPORT" "$STATE" "$CONTEXT_DIR" "$HANDOFF_DIR"

db() { "$PY" "$TOOLS_DIR/lib/db.py" --db "$DB" "$@"; }
