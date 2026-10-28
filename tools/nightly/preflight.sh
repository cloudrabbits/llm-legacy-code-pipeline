#!/usr/bin/env bash
# 环境预检：连通性 → 模型就绪 → 预热 → 吞吐基准 → 工具调用能力 →（可选）长上下文探针
# 最后一行输出 decode tok/s，供 nightly.sh 采集
#   ./preflight.sh --night 1 [--niah] [--no-warm]
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
source "$TOOLS_DIR/lib/log.sh"
source "$TOOLS_DIR/lib/ollama.sh"

NIGHT=0; DO_NIAH=0; DO_WARM=1
while [[ $# -gt 0 ]]; do
  case "$1" in --night) NIGHT="$2"; shift 2;; --niah) DO_NIAH=1; shift;; --no-warm) DO_WARM=0; shift;; *) shift;; esac
done

DATE=$(date +%F)
REP="$REPORT/preflight-$DATE.md"
mkdir -p "$REPORT"

ollama_alive || { log_err "Ollama 不可达：$OLLAMA_URL"; echo 0; exit 1; }
VER=$(curl -s -m 5 "$OLLAMA_URL/api/version")
ollama_model_ready || log_warn "模型 $WARM_MODEL 未在 /api/tags 中出现，请确认已创建别名"

if (( DO_WARM )); then ollama_warm || log_warn "预热失败"; fi

read -r TPS PPS <<<"$(ollama_bench 512)"
TOOL=$(ollama_tool_probe)
PS_JSON=$(ollama_ps)
log_info "preflight: ollama=$VER decode=${TPS}tok/s prefill=${PPS}tok/s tools=$TOOL"

{
  echo "# 预检 $DATE"
  echo
  echo "- ollama: \`$VER\` @ \`$OLLAMA_URL\`"
  echo "- 模型: \`$WARM_MODEL\` num_ctx=$NUM_CTX"
  echo "- **decode = $TPS tok/s**，prefill = $PPS tok/s（采样 512 tokens）"
  echo "- 工具调用能力: **$TOOL**"
  echo
  echo '```json'
  echo "$PS_JSON"
  echo '```'
} > "$REP"

db metric --night "$NIGHT" --kind preflight --key decode_tps --value "${TPS:-0}" --detail "$WARM_MODEL" >/dev/null 2>&1
db metric --night "$NIGHT" --kind preflight --key prefill_tps --value "${PPS:-0}" >/dev/null 2>&1
[[ "$TOOL" == SUPPORTED ]] && TV=1 || TV=0
db metric --night "$NIGHT" --kind preflight --key tool_supported --value "$TV" >/dev/null 2>&1

if (( DO_NIAH )); then
  {
    echo
    echo "## 长上下文检索探针（NIAH）"
    echo
    echo "| ctx | depth | hits | rate |"
    echo "|---|---|---|---|"
  } >> "$REP"
  for ctx in 8000 32000 64000 "$NUM_CTX"; do
    for d in 0.2 0.5 0.9; do
      R=$("$PY" "$TOOLS_DIR/lib/niah.py" --url "$OLLAMA_URL" --model "$WARM_MODEL" --ctx "$ctx" --depth "$d" --repeat 3)
      RATE=$(echo "$R" | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print(d.get("rate","ERR"))')
      HITS=$(echo "$R" | "$PY" -c 'import sys,json;d=json.load(sys.stdin);print(f"{d.get(\"hits\",\"?\")}/{d.get(\"total\",\"?\")}")')
      echo "| $ctx | $d | $HITS | $RATE |" >> "$REP"
      db metric --night "$NIGHT" --kind niah --key "ctx${ctx}_d${d}" --value "${RATE:-0}" >/dev/null 2>&1
    done
  done
fi

echo "${TPS:-0}"
