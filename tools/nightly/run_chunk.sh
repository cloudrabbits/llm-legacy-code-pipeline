#!/usr/bin/env bash
# 单分片执行器：拼装提示词 → 调 OpenCode → 抽取产物 → 验收 → 落状态/交接卡/事实库
# 用法：run_chunk.sh --chunk T01#1 --task T01 --seq 1 --range 'src/**' --out docs/x.md
#                    --prompt tasks/T01.md --timeout 20 --check "size>2000" --night 1 [--attempt 0]
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$TOOLS_DIR/lib/log.sh"
source "$TOOLS_DIR/lib/atomic.sh"

CHUNK=""; TASK=""; SEQ=1; RANGE="*"; OUTP=""; PROMPT=""; TMO="$DEFAULT_TIMEOUT_MIN"; CHECK=""; NIGHT=0; ATTEMPT=0
PREDICT="$MAX_OUTPUT_TOKENS"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --chunk) CHUNK="$2"; shift 2;;
    --task) TASK="$2"; shift 2;;
    --seq) SEQ="$2"; shift 2;;
    --range) RANGE="$2"; shift 2;;
    --out) OUTP="$2"; shift 2;;
    --prompt) PROMPT="$2"; shift 2;;
    --timeout) TMO="$2"; shift 2;;
    --check) CHECK="$2"; shift 2;;
    --night) NIGHT="$2"; shift 2;;
    --attempt) ATTEMPT="$2"; shift 2;;
    --max-out) PREDICT="$2"; shift 2;;
    *) shift;;
  esac
done

[[ -n "$CHUNK" && -n "$OUTP" ]] || { log_err "run_chunk: 缺少 --chunk/--out"; exit 2; }
# 提示词路径解析：兼容 "T01.md" / "tasks/T01.md" / 绝对路径 三种写法
resolve_prompt() {
  local p="$1"
  [[ -z "$p" ]] && return 1
  [[ -f "$p" ]] && { echo "$p"; return 0; }
  local c
  for c in "$TASKDIR/$(basename "$p")" "$TASKDIR/$p" "$TOOLS_DIR/$p"; do
    [[ -f "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}
PROMPT_PATH="$(resolve_prompt "$PROMPT")" || {
  log_err "找不到任务书: $PROMPT（TASKDIR=$TASKDIR）"
  exit 2
}

TARGET="$WORK/$OUTP"
RAW="$OUT/$(echo "$CHUNK" | tr '#' '_').raw.md"
mkdir -p "$(dirname "$TARGET")" "$(dirname "$RAW")" "$HANDOFF_DIR/$TASK"
echo "$CHUNK" > "$STATE/current.chunk"; echo "$RAW" > "$STATE/current.raw"; echo $$ > "$STATE/current.pid"

# 1) 拼装提示词（输入预算受 MAX_INPUT_TOKENS 约束）
PR="$STATE/prompt-$(echo "$CHUNK" | tr '#' '_').md"
INC_ARGS=()
[[ "$LLM_MODE" == "direct" ]] && INC_ARGS=(--include-globs "$RANGE")
"$PY" "$TOOLS_DIR/lib/bootstrap.py" --work "$WORK" --task "$TASK" --seq "$SEQ" \
  --range "$RANGE" --out "$OUTP" --prompt "$PROMPT_PATH" --max-tokens "$MAX_INPUT_TOKENS" \
  --tool-mode "$TOOL_MODE" "${INC_ARGS[@]}" --o "$PR" || exit 2

if (( DRY_RUN )); then
  log_info "[dry-run] 将执行分片 $CHUNK → $OUTP（提示词 $PR，$(wc -c < "$PR") 字符）"
  exit 0
fi

# 重试时追加失败提示
EXTRA=""
if (( ATTEMPT > 0 )); then
  EXTRA=$'\n\n【上次执行未通过验收】请缩短篇幅、先保证结构与证据完整，若内容较多请在 status 中写 partial 并先落盘已完成部分。'
fi

log_info "开始分片 $CHUNK（$TASK seq=$SEQ，超时 ${TMO}min）→ $OUTP"
db chunk-start --id "$CHUNK" --night "$NIGHT" >/dev/null
T0=$(date +%s)
export CHUNK_START_TS="$T0"

# 2) 调用 OpenCode（工作目录 = 工作副本）
AGENT_ARGS=(); [[ -n "$AGENT" ]] && AGENT_ARGS=(--agent "$AGENT")
ERRF="$LOG/$LOG_DATE/$(echo "$CHUNK" | tr '#' '_').err"
if [[ "$LLM_MODE" == "direct" ]]; then
  # 直连补全：无工具、think 可关、上下文由提示词预取
  timeout -k 30 "${TMO}m" "$PY" "$TOOLS_DIR/lib/llm_direct.py" \
    --url "$OLLAMA_URL" --model "$WARM_MODEL" --prompt "$PR" \
    --ctx "$NUM_CTX" --predict "$PREDICT" --think "$LLM_THINK" \
    > "$RAW" 2> "$ERRF"
  RC=$?
  # 统计行单独存一份，便于核对吞吐
  grep -o '{"wall_s".*}' "$ERRF" > "$LOG/$LOG_DATE/$(echo "$CHUNK" | tr '#' '_').stats.json" 2>/dev/null || true
else
  # -k 30：opencode 不响应 SIGTERM（实测卡死 24 分钟未退出），必须 TERM 后 30s 补 SIGKILL
  ( cd "$WORK" && timeout -k 30 "${TMO}m" "$OC" run "${AGENT_ARGS[@]}" -m "$MODEL" $OC_FLAGS "$(cat "$PR")$EXTRA" ) \
    > "$RAW" 2> "$ERRF"
  RC=$?
fi
T1=$(date +%s); SEC=$((T1 - T0))
log_info "分片 $CHUNK 结束 rc=$RC 用时 ${SEC}s 原始输出 $(wc -c < "$RAW") 字节"

# 3) 抽取产物（工具写文件优先；否则从 stdout 的 ```markdown 块抽取）
if (( RC == 124 )); then
  log_warn "分片 $CHUNK 超时（rc=124）"
fi
# extract 自己判断：模型本次新写的文件优先，否则从 stdout 抽取（text 模式强制抽取）
FORCE=()
[[ "$TOOL_MODE" == "text" ]] && FORCE=(--force)
"$PY" "$TOOLS_DIR/lib/extract.py" --mode file --raw "$RAW" --out "$TARGET" \
  --since "${CHUNK_START_TS:-0}" "${FORCE[@]}" || log_warn "抽取正文失败"

# 4) 验收（注意：verify.py 失败时也会输出合法 JSON，不要用 || 追加，否则 JSON 粘连）
VFILE="$LOG/$LOG_DATE/$(echo "$CHUNK" | tr '#' '_').verify.json"
"$PY" "$TOOLS_DIR/lib/verify.py" "$TARGET" "$CHECK" --repo "$WORK" > "$VFILE" 2>/dev/null
VRC=$?
VJSON="$(cat "$VFILE" 2>/dev/null)"
VOK=$(printf '%s' "$VJSON" | "$PY" -c 'import sys,json
try:
    print("1" if json.load(sys.stdin).get("ok") else "0")
except Exception:
    print("0")')

if [[ "$VOK" == "1" ]]; then
  # 5a) 交接卡
  "$PY" "$TOOLS_DIR/lib/extract.py" --mode summary --raw "$RAW" --handoff "$HANDOFF_DIR/$TASK/$SEQ.md" >/dev/null 2>&1
  # 5b) 事实入库
  "$PY" "$TOOLS_DIR/lib/facts_import.py" --db "$DB" --raw "$RAW" --task "$TASK" --night "$NIGHT" >/dev/null 2>&1
  db chunk-done --id "$CHUNK" --night "$NIGHT" --chars "$(wc -c < "$RAW")" --seconds "$SEC" --handoff "$HANDOFF_DIR/$TASK/$SEQ.md" >/dev/null
  log_info "分片 $CHUNK 完成 ✓（验收通过）"
  rm -f "$STATE/current.chunk" "$STATE/current.raw" "$STATE/current.pid"
  exit 0
fi

REASON="rc=$RC; verify=$(printf '%s' "$VJSON" | tr -d '\n' | cut -c1-200)"
db chunk-fail --id "$CHUNK" --error "$REASON" >/dev/null
log_err "分片 $CHUNK 失败：$REASON"
rm -f "$STATE/current.chunk" "$STATE/current.raw" "$STATE/current.pid"
exit 1
