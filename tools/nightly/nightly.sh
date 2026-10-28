#!/usr/bin/env bash
# 夜间主编排器（支持跨夜续跑）
#   ./nightly.sh                 # 默认 --resume：接续上次进度
#   ./nightly.sh --dry-run       # 只打印续跑清单，不调模型（排障首选）
#   ./nightly.sh --fresh         # 清空状态重跑
#   ./nightly.sh --only T03      # 只跑指定任务
#   ./nightly.sh --no-preflight  # 跳过预热与基准
#   ./nightly.sh --stop          # 请求正在运行的实例优雅停止
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$TOOLS_DIR/lib/log.sh"
source "$TOOLS_DIR/lib/lock.sh"
source "$TOOLS_DIR/lib/ollama.sh"

FRESH=0; NO_PREFLIGHT=0; ONLY=""; STOP_REQ=0; SKIP_SYNC=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --resume) shift;;
    --fresh) FRESH=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    --no-preflight) NO_PREFLIGHT=1; shift;;
    --skip-sync) SKIP_SYNC=1; shift;;
    --only) ONLY="$2"; shift 2;;
    --stop) STOP_REQ=1; shift;;
    *) shift;;
  esac
done

if (( STOP_REQ )); then
  pid="$(cat "$ROOT/nightly.lock" 2>/dev/null || echo '')"
  [[ -n "$pid" ]] && kill -TERM "$pid" 2>/dev/null && echo "已发送停止信号给 $pid"
  exit 0
fi

START_TS=$(date +%s)
acquire_lock || exit 1

if [[ -f "$ROOT/PAUSE" ]]; then
  log_warn "检测到 $ROOT/PAUSE，本夜不执行任何任务"
  exit 0
fi

# ---------------- 截止时间计算（HARD_STOP 通常是次日时刻） ----------------
END_TS=""; SOFT_TS=""; CKPT_TS=""
compute_deadlines() {
  local tod; tod=$(date -d "$HARD_STOP" +%s 2>/dev/null || echo 0)
  (( tod <= START_TS )) && tod=$(( tod + 86400 ))
  local cap=$(( START_TS + MAX_NIGHT_MINUTES * 60 ))
  END_TS=$tod; (( cap < END_TS )) && END_TS=$cap
  SOFT_TS=$(( END_TS - SOFT_BEFORE_MIN * 60 ))
  CKPT_TS=$(( END_TS - CKPT_BEFORE_MIN * 60 ))
}
compute_deadlines
log_info "本夜窗口：现在 $(date '+%F %T') → 硬停 $(date -d "@$END_TS" '+%F %T')（SOFT $(date -d "@$SOFT_TS" '+%T') / CKPT $(date -d "@$CKPT_TS" '+%T')）"

# ---------------- 初始化 ----------------
db init >/dev/null
if (( FRESH )); then
  log_info "$(db load-queue --queue "$QUEUE" --taskdir "$TASKDIR" --fresh 2>&1)"
else
  log_info "$(db load-queue --queue "$QUEUE" --taskdir "$TASKDIR" 2>&1)"
fi
NIGHT=$(( $(db last-night) + 1 ))
export NIGHT
db run-start --night "$NIGHT" --date "$(date +%F)" >/dev/null
log_info "第 $NIGHT 夜开始"

# ---------------- 同步工作副本（保护已生成产物不被 --delete 清掉） ----------------
if (( SKIP_SYNC == 0 && DRY_RUN == 0 )); then
  mkdir -p "$WORK"
  # 产物目录不参与同步：WORK 是产物唯一权威来源。
  # 否则产物回传到源项目后，次日 rsync 会把上一次（甚至失败的）产物灌回工作副本，
  # 造成"验收拿旧文件判定"的幽灵产物。源码目录仍与源项目保持一致。
  rsync -a --delete \
    --exclude=docs/ --exclude=reports/ --exclude=patches/ \
    --exclude=staging/ --exclude=ai/ --exclude=handoff/ \
    $RSYNC_EXCLUDES "$SRC/" "$WORK/" || log_warn "rsync 失败，继续使用现有工作副本"
  log_info "工作副本已同步：$SRC → $WORK"
fi

# ---------------- 预检与预热 ----------------
TPS=0
if (( NO_PREFLIGHT == 0 )); then
  if ! ollama_alive; then log_err "Ollama 不可达（$OLLAMA_URL），本夜中止"; db run-end --night "$NIGHT" --reason crash --done 0 --failed 0 >/dev/null; exit 1; fi
  TPS=$(bash "$TOOLS_DIR/preflight.sh" --night "$NIGHT" | tail -1)
  [[ "$TPS" =~ ^[0-9.]+$ ]] || TPS=0
  log_info "实测吞吐 decode=${TPS} tok/s"
else
  log_warn "跳过预检（--no-preflight）"
fi

# ---------------- 续跑清单重建 ----------------
log_info "$(db reset-running 2>&1)"
log_info "$(db ghosts --work "$WORK" 2>&1)"
CHANGED_JSON=$(db snap-diff --src "$SRC" --night "$NIGHT" 2>/dev/null || echo '{"changed":[]}')
CHANGED=$(echo "$CHANGED_JSON" | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print(",".join(d.get("changed",[])))')
if [[ -n "$CHANGED" ]]; then
  log_warn "检测到源码变更（$(echo "$CHANGED" | tr ',' '\n' | wc -l) 个文件），执行精确失效"
  log_info "$(db mark-stale --files "$CHANGED" 2>&1)"
else
  log_info "源码未变更，无需失效重算"
fi
db snap-save --src "$SRC" --night "$NIGHT" >/dev/null
# L0 确定性图层：行数/方法数/依赖边必须由脚本给出，否则模型会编造（实测）
"$PY" "$TOOLS_DIR/lib/l0.py" --src "$WORK" --out "$CONTEXT_DIR/L0-inventory.md" 2>&1 | while read -r l; do log_info "$l"; done
db fact-export --file "$CONTEXT_DIR/FACTS.md" >/dev/null
bash "$TOOLS_DIR/resume_brief.sh" --night "$NIGHT" >/dev/null

# ---------------- 截止夜：收尾档 ----------------
WRAPUP_SKIP="${WRAPUP_SKIP:-T09,T16}"
if (( NIGHT >= DEADLINE_NIGHT )); then
  log_warn "到达截止夜（$NIGHT ≥ $DEADLINE_NIGHT）：启用收尾档，跳过低价值任务 $WRAPUP_SKIP"
  IFS=',' read -ra SKIP_ARR <<< "$WRAPUP_SKIP"
  for t in "${SKIP_ARR[@]}"; do
    db task-status --id "$t" --status dropped >/dev/null 2>&1 || true
  done
fi

# ---------------- 看门狗（stall 检测） ----------------
watchdog() {
  while true; do
    sleep 60
    [[ -f "$STATE/current.chunk" ]] || continue
    f="$(cat "$STATE/current.raw" 2>/dev/null || echo '')"
    [[ -n "$f" && -f "$f" ]] || continue
    mt=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    now=$(date +%s)
    if (( now - mt > STALL_MIN * 60 )); then
      pid=$(cat "$STATE/current.pid" 2>/dev/null || echo '')
      log_warn "stall：$f 静止超过 ${STALL_MIN} 分钟，终止 pid=${pid:-未知}"
      [[ -n "$pid" ]] && { kill -TERM "$pid" 2>/dev/null; sleep 5; kill -KILL "$pid" 2>/dev/null; }
      rm -f "$STATE/current.chunk" "$STATE/current.raw" "$STATE/current.pid"
    fi
  done
}
if (( DRY_RUN == 0 )); then watchdog & WD_PID=$!; else WD_PID=""; fi

# ---------------- 中断协议（三级停止） ----------------
STOP_LEVEL=0
on_stop() { STOP_LEVEL=$(( STOP_LEVEL + 1 )); log_warn "收到停止信号，级别=$STOP_LEVEL"; }
trap on_stop TERM INT

# ---------------- 主循环 ----------------
DONE=0; FAILED=0; CHARS=0; ITER=0
VISITED="$STATE/visited.$NIGHT"; : > "$VISITED"
MAX_ITERS=$(( $(db sql --q "SELECT COUNT(*) FROM chunk;") * 3 + 5 ))
while true; do
  (( ITER++ > MAX_ITERS )) && { log_warn "达到迭代上限，停止（防死循环）"; break; }
  now=$(date +%s)
  (( now >= END_TS )) && { log_warn "到达硬停时刻，停止"; break; }
  if (( STOP_LEVEL >= 1 )) || (( now >= CKPT_TS )); then
    log_warn "CHECKPOINT 级：不再启动新分片（剩余任务留待下一夜）"; break
  fi

  # 干跑时状态不变，用 --exclude-file 逐个跳过已列过的分片，保证能列出完整清单
  EXCL_ARGS=()
  (( DRY_RUN )) && EXCL_ARGS=(--exclude-file "$VISITED" --no-dep)
  ROW=$(db next-chunk --night "$NIGHT" --only-task "$ONLY" "${EXCL_ARGS[@]}") \
    || { log_info "队列已清空（无可执行分片）"; break; }
  IFS=$'\t' read -r CID TID SEQ RANGEP OUTP PROMPT TMO CHK TITLE PHASE MAXOUT <<< "$ROW"
  # 按任务覆盖输出预算（实测：3500 写不完 2 个文件的完整 diff，会被截断成 corrupt patch）
  PREDICT="$MAX_OUTPUT_TOKENS"
  [[ "$MAXOUT" =~ ^[0-9]+$ ]] && (( MAXOUT > 0 )) && PREDICT="$MAXOUT"
  echo "$CID" >> "$VISITED"

  # 时间预算：本分片耗时 + 10 分钟缓冲必须落在 CKPT 之前
  if (( now + TMO * 60 + 600 > CKPT_TS )); then
    log_warn "时间预算不足，停止排新分片（待跑：$CID）"; break
  fi
  ATTEMPT=$(db sql --q "SELECT COALESCE(attempt,0) FROM chunk WHERE id='$CID';")
  log_info "→ 执行 $CID [$PHASE] $TITLE（attempt=$ATTEMPT，超时 ${TMO}min）"
  bash "$TOOLS_DIR/run_chunk.sh" --chunk "$CID" --task "$TID" --seq "$SEQ" --range "$RANGEP" \
       --out "$OUTP" --prompt "$PROMPT" --timeout "$TMO" --check "$CHK" --night "$NIGHT" \
       --attempt "$ATTEMPT" --max-out "$PREDICT"
  RC=$?
  if (( RC == 0 )); then
    DONE=$(( DONE + 1 ))
    RAWF="$OUT/$(echo "$CID" | tr '#' '_').raw.md"
    (( CHARS += $( [[ -f "$RAWF" ]] && wc -c < "$RAWF" || echo 0 ) ))
    bash "$TOOLS_DIR/merge.sh" --task "$TID" >/dev/null 2>&1
  else
    FAILED=$(( FAILED + 1 ))
    B="${RETRY_BACKOFF%%,*}"
    if (( DRY_RUN == 0 )); then
      log_warn "分片失败，退避 ${B}s 后继续下一个"
      sleep "$B"
    else
      log_warn "分片失败（干跑不退避）"
    fi
  fi
  (( STOP_LEVEL >= 2 )) && { log_warn "HARD 级：立即停止"; break; }
done

[[ -n "$WD_PID" ]] && kill "$WD_PID" 2>/dev/null

# ---------------- 收尾 ----------------
REASON=schedule
(( STOP_LEVEL >= 2 )) && REASON=hard
(( STOP_LEVEL == 1 )) && REASON=soft
CARRY=$(db sql --q "SELECT COUNT(*) FROM chunk WHERE status IN ('pending','stale','failed');")
db run-end --night "$NIGHT" --reason "$REASON" --tps "$TPS" --chars "$CHARS" --done "$DONE" --failed "$FAILED" --carry "$CARRY" >/dev/null
log_info "第 $NIGHT 夜结束：done=$DONE failed=$FAILED 结转=$CARRY 原因=$REASON"

log_info "$(bash "$TOOLS_DIR/summarize.sh" --night "$NIGHT" 2>&1 | tail -1)"

# 回传产物到源项目
if (( DRY_RUN == 0 )); then
  for d in docs reports patches staging; do
    [[ -d "$WORK/$d" ]] && rsync -a "$WORK/$d/" "$SRC/$d/" 2>/dev/null
  done
  log_info "产物已回传至 $SRC"
fi
