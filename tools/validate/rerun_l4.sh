#!/usr/bin/env bash
# 补跑上次因索引文件缺换行而漏掉的陷阱题（L4-01），并重新评分
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../nightly/env.sh"
CORPUS="${CORPUS:-$HOME/legacy/b1}"
RESULTS="$HERE/results"
export ONLY_IDS="${ONLY_IDS:-L4-01}"

for arm in A B; do
  echo "== arm $arm : $ONLY_IDS =="
  bash "$HERE/run_experiment.sh" --corpus "$CORPUS" --arm "$arm" --out "$RESULTS/arm$arm" 2>&1 | tail -3
done

echo
echo "== armA / L4-01 回答 =="; head -10 "$RESULTS/armA/L4-01.md" 2>/dev/null
echo
echo "== armB / L4-01 回答 =="; head -10 "$RESULTS/armB/L4-01.md" 2>/dev/null

echo
echo "== 重新评分 =="
for arm in A B; do
  python3 "$HERE/grade.py" --questions "$CORPUS/questions.json" --answers "$RESULTS/arm$arm" \
    --corpus "$CORPUS" --out "$RESULTS/arm$arm.score.json" > /dev/null 2>&1
  echo "-- arm $arm --"
  python3 - "$RESULTS/arm$arm.score.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print("  accuracy:", d["accuracy"])
print("  counts  :", d["counts"])
print("  citation_valid_rate:", d["citation_valid_rate"], "citations:", d["citations"])
PY
done

echo
echo "== 指标 =="
python3 "$HERE/metrics.py" --score "armA=$RESULTS/armA.score.json" --score "armB=$RESULTS/armB.score.json" \
  --out "$REPORT/feasibility.json"
