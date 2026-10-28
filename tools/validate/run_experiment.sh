#!/usr/bin/env bash
# 金标准实验：对合成语料的 30 道题逐题询问模型，分两条对照臂
#   arm A（裸 LLM）：只注入题目声明范围内的文件原文
#   arm B（工具图辅助）：额外注入由脚本算出的证据（模拟 L0 符号图层）
#
# 用法：
#   ./run_experiment.sh --corpus /tmp/legacy_b1 --arm A --out results/armA
#   ./run_experiment.sh --corpus /tmp/legacy_b1 --arm B --out results/armB --model local-ollama/qwen3.6-35B-A3B-90k
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/../nightly/env.sh"
export LOG_DATE="${LOG_DATE:-$(date +%F)}"
mkdir -p "$LOG/$LOG_DATE"

CORPUS=""; ARM="A"; OUTDIR=""; LIMIT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --corpus) CORPUS="$2"; shift 2;;
    --arm) ARM="$2"; shift 2;;
    --out) OUTDIR="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --limit) LIMIT="$2"; shift 2;;
    *) shift;;
  esac
done
[[ -n "$CORPUS" && -n "$OUTDIR" ]] || { echo "需要 --corpus 与 --out"; exit 2; }
mkdir -p "$OUTDIR"

# 1) 生成逐题提示词（python 负责读 questions.json 与拼装 scope 文件）
"$PY" - "$CORPUS" "$ARM" "$OUTDIR" "$LIMIT" <<'PY'
import json, os, sys
corpus, arm, outdir, limit = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
qs = json.load(open(os.path.join(corpus, "questions.json"), encoding="utf-8"))
if limit:
    qs = qs[:limit]
only = os.environ.get("ONLY_IDS", "").strip()
if only:
    keep = {x.strip() for x in only.split(",")}
    qs = [q for q in qs if q["id"] in keep]
idx = []
for q in qs:
    body = []
    for rel in q.get("scope", [])[:6]:
        p = os.path.join(corpus, rel)
        if os.path.exists(p):
            txt = open(p, encoding="utf-8", errors="replace").read()
            if len(txt) > 24000:      # 大文件截断，模拟切分注入
                txt = txt[:24000] + "\n...（截断）"
            body.append(f"### 文件 {rel}\n\n```\n{txt}\n```\n")
    ev = ""
    if arm.upper() == "B":
        ev = "【脚本算出的证据（请以此为判断依据，不要重新统计）】\n" + str(q.get("tool_evidence", "")) + "\n"
    prompt = f"""你是代码分析助手。{ev}
【上下文文件】
{chr(10).join(body)}

【问题】{q['question']}

【要求】
1) 只依据上面的上下文与证据回答；不确定就回答"未确认"。
2) 每条结论附 文件:行号 证据。
3) 若问题中的对象不存在，直接回答"不存在"，不要编造。
4) 回答控制在 200 字以内。"""
    pf = os.path.join(outdir, f"{q['id']}.prompt.md")
    open(pf, "w", encoding="utf-8").write(prompt)
    idx.append(f"{q['id']}\t{pf}")
# 末尾必须补换行，否则 bash 的 `while read` 会吞掉最后一行（实测丢了 L4-01）
open(os.path.join(outdir, "_index.tsv"), "w", encoding="utf-8").write("\n".join(idx) + "\n")
print(f"prompts: {len(idx)} -> {outdir}")
PY

# 2) 逐题调用 OpenCode
N=0
while IFS=$'\t' read -r QID PF; do
  [[ -n "$QID" ]] || continue
  N=$((N+1))
  if (( DRY_RUN )); then echo "[dry-run] $QID"; continue; fi
  echo "---- $QID (arm $ARM) $(date '+%T')"
  # 统一走直连通道（实测 agent 模式对该模型不可靠）
  timeout -k 20 8m python3 "$HERE/../nightly/lib/llm_direct.py" \
    --model "$WARM_MODEL" --prompt "$PF" --ctx "$NUM_CTX" --predict 600 --think false \
    > "$OUTDIR/$QID.md" 2> "$LOG/$LOG_DATE/exp-$ARM-$QID.err"
  echo "$QID rc=$?"
done < "$OUTDIR/_index.tsv"
echo "实验完成：arm=$ARM 题数=$N 输出=$OUTDIR"
