#!/usr/bin/env bash
# 可行性验证驱动：分阶段执行，可后台跑 + 轮询日志
#   ./run_validation.sh preflight   # 预热 + 吞吐基准 + 工具调用探测（加载 22GB 模型，数分钟）
#   ./run_validation.sh t01         # 真实项目端到端：跑 T01 一个分片
#   ./run_validation.sh corpus      # 生成 5MB 合成老项目语料 + 30 题金标准
#   ./run_validation.sh armA        # 裸 LLM 对照臂
#   ./run_validation.sh armB        # 工具图辅助对照臂
#   ./run_validation.sh niah        # 90K 长上下文检索探针
#   ./run_validation.sh score       # 评分 + 指标汇总
#   ./run_validation.sh all         # 依次全部执行
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIGHTLY="$HERE/../nightly"
source "$NIGHTLY/env.sh"

# 验证使用 90K 上下文别名（强制覆盖，env.sh 的默认值是"开箱即用"档）
export MODEL="local-ollama/qwen3.6-35B-A3B-90k"
export OLLAMA_TAG="qwen3.6-35B-A3B-90k:latest"
export WARM_MODEL="qwen3.6-35B-A3B-90k"
export NUM_CTX="90000"

export ROOT="${ROOT:-$HOME/nightly}"
export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$HERE/../.." && pwd)}"
export SRC="$PROJECT_ROOT"
export CORPUS="${CORPUS:-$HOME/legacy/b1}"
export RESULTS="${RESULTS:-$HERE/results}"

ts() { date '+%F %T'; }
phase() { echo; echo "########## $1  $(ts) ##########"; }

do_preflight() {
  phase "PREFLIGHT"
  bash "$NIGHTLY/preflight.sh" --night 1 2>&1 | tail -20
}

do_bench() {
  phase "上下文长度阶梯基准（prefill/decode）"
  python3 "$NIGHTLY/lib/bench.py" --url "$OLLAMA_URL" --model "$WARM_MODEL" --ctx "$NUM_CTX" \
    --lens "${LENS:-2048,8192,16384,32768}" --predict 128 2>&1
}

do_t01() {
  phase "真实项目端到端：T01"
  db init >/dev/null
  db load-queue --queue "$QUEUE" --taskdir "$TASKDIR" >/dev/null
  bash "$NIGHTLY/nightly.sh" --only T01 2>&1 | tail -40
  phase "T01 产物核对"
  F="$WORK/docs/arch/01-inventory.md"
  if [[ -f "$F" ]]; then
    echo "产物: $F  $(wc -c < "$F") 字节 / $(wc -l < "$F") 行"
    head -25 "$F"
  else
    echo "!! 产物缺失: $F"
  fi
  echo "-- 入库事实 --"
  db sql --q "SELECT COUNT(*) FROM fact;"
  db sql --q "SELECT pk, claim FROM fact LIMIT 5;"
  echo "-- 分片状态 --"
  db sql --q "SELECT id,status,chars_out,seconds FROM chunk WHERE id LIKE 'T01%';"
}

do_corpus() {
  phase "合成语料"
  mkdir -p "$(dirname "$CORPUS")"
  python3 "$HERE/mklegacy.py" --out "$CORPUS" --text-mb 5 --jar-mb 20 --seed 7 2>&1 | tail -3
  python3 - <<PY
import json, os
q = json.load(open(os.path.join("$CORPUS", "questions.json"), encoding="utf-8"))
from collections import Counter
print("题目分布:", dict(Counter(x["tier"] for x in q)))
for x in q[:2]:
    print(" 样例:", x["id"], x["question"][:80])
PY
}

do_arm() {
  local arm="$1"
  phase "对照臂 arm $arm"
  bash "$HERE/run_experiment.sh" --corpus "$CORPUS" --arm "$arm" --out "$RESULTS/arm$arm" 2>&1 | tail -12
}

do_niah() {
  phase "NIAH 长上下文探针（ctx=8000/32000/90000）"
  for ctx in 8000 32000 90000; do
    for d in 0.2 0.5 0.9; do
      R=$(python3 "$NIGHTLY/lib/niah.py" --url "$OLLAMA_URL" --model "$WARM_MODEL" --ctx "$ctx" --depth "$d" --repeat 3)
      echo "  ctx=$ctx depth=$d -> $R"
    done
  done
}

do_score() {
  phase "评分与指标"
  python3 "$HERE/grade.py" --questions "$CORPUS/questions.json" --answers "$RESULTS/armA" \
    --corpus "$CORPUS" --out "$RESULTS/armA.score.json" 2>&1 | head -14
  python3 "$HERE/grade.py" --questions "$CORPUS/questions.json" --answers "$RESULTS/armB" \
    --corpus "$CORPUS" --out "$RESULTS/armB.score.json" 2>&1 | head -14
  python3 "$HERE/metrics.py" --score "armA=$RESULTS/armA.score.json" --score "armB=$RESULTS/armB.score.json" \
    --out "$REPORT/feasibility.json" 2>&1 | head -30
}

case "${1:-all}" in
  preflight) do_preflight;;
  bench) do_bench;;
  t01) do_t01;;
  corpus) do_corpus;;
  armA) do_arm A;;
  armB) do_arm B;;
  niah) do_niah;;
  score) do_score;;
  all) do_preflight; do_t01; do_corpus; do_arm A; do_arm B; do_score;;
  *) echo "用法: $0 {preflight|t01|corpus|armA|armB|niah|score|all}";;
esac
phase "阶段结束"
