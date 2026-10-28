#!/usr/bin/env bash
# 一次性跑完金标准实验：生成语料 -> armA -> armB -> 评分 -> 指标
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../nightly/env.sh"
export MODEL="local-ollama/qwen3.6-35B-A3B-90k"
export OLLAMA_TAG="qwen3.6-35B-A3B-90k:latest"
export WARM_MODEL="qwen3.6-35B-A3B-90k"
export NUM_CTX="90000"
CORPUS="${CORPUS:-$HOME/legacy/b1}"
RESULTS="$HERE/results"

echo "===== 1) 语料 ====="
if [[ ! -f "$CORPUS/questions.json" ]]; then
  mkdir -p "$(dirname "$CORPUS")"
  python3 "$HERE/mklegacy.py" --out "$CORPUS" --text-mb 5 --jar-mb 20 --seed 7
fi
python3 - "$CORPUS" <<'PY'
import json, os, sys
from collections import Counter
c = sys.argv[1]
q = json.load(open(os.path.join(c, "questions.json"), encoding="utf-8"))
print("  题目:", dict(Counter(x["tier"] for x in q)))
print("  语料大小: %.1f MB" % (sum(os.path.getsize(os.path.join(r, f))
      for r, _, fs in os.walk(c) for f in fs) / 1e6))
PY

for arm in A B; do
  echo
  echo "===== 2) arm $arm ====="
  rm -rf "$RESULTS/arm$arm"; mkdir -p "$RESULTS/arm$arm"
  bash "$HERE/run_experiment.sh" --corpus "$CORPUS" --arm "$arm" --out "$RESULTS/arm$arm" 2>&1 | tail -6
done

echo
echo "===== 3) 评分 ====="
for arm in A B; do
  python3 "$HERE/grade.py" --questions "$CORPUS/questions.json" --answers "$RESULTS/arm$arm" \
    --corpus "$CORPUS" --out "$RESULTS/arm$arm.score.json" > /dev/null 2>&1
  echo "-- arm $arm --"
  python3 - "$RESULTS/arm$arm.score.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("  accuracy:", d["accuracy"])
print("  counts  :", d["counts"])
print("  citation_valid_rate:", d["citation_valid_rate"], " citations:", d["citations"])
PY
done

echo
echo "===== 4) 指标 ====="
python3 "$HERE/metrics.py" --score "armA=$RESULTS/armA.score.json" --score "armB=$RESULTS/armB.score.json" \
  --out "$REPORT/feasibility.json" 2>&1 | head -40
echo "===== done ====="
