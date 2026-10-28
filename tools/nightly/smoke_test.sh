#!/usr/bin/env bash
# 冒烟自检：语法 + 状态库 + 干跑续跑清单 + 验收器 + 合成语料 + 评分器
# 用法：./smoke_test.sh   （不调用模型，秒级完成）
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ROOT="${ROOT:-/tmp/nightly_smoke}"
export PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$HERE/../.." && pwd)}"
export SRC="$PROJECT_ROOT"
source "$HERE/env.sh"

PASS=0; FAIL=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

echo "== 1) shell 语法 =="
while IFS= read -r f; do
  if bash -n "$f" 2>/dev/null; then ok "$(basename "$f")"; else bad "语法错误: $f"; fi
done < <(find "$HERE" -name '*.sh' | sort)

echo "== 2) python 语法 =="
if python3 -m py_compile $(find "$HERE/../" -name '*.py' | sort) 2>/dev/null; then ok "全部 py 编译通过"; else bad "py 编译失败"; fi

echo "== 3) 状态库 =="
rm -rf "$ROOT"; db init >/dev/null 2>&1 && ok "init" || bad "init"
db load-queue --queue "$QUEUE" --taskdir "$TASKDIR" --fresh 2>/dev/null | sed 's/^/    /'
N=$(db sql --q "SELECT COUNT(*) FROM chunk;")
[[ "$N" -ge 17 ]] && ok "分片数=$N（含 T06 的 2 个分片）" || bad "分片数异常=$N"
ROW=$(db next-chunk --night 1)
[[ -n "$ROW" ]] && ok "首个可执行分片: $(echo "$ROW" | cut -f1)" || bad "取不到可执行分片"

echo "== 4) 干跑（--dry-run，不调模型） =="
if DRY_RUN=1 timeout 120 bash "$HERE/nightly.sh" --dry-run --no-preflight --skip-sync >/tmp/smoke_dry.log 2>&1; then
  ok "nightly --dry-run 退出 0（$(grep -c 'dry-run' /tmp/smoke_dry.log 2>/dev/null) 条干跑记录）"
else
  bad "nightly --dry-run 失败，日志: /tmp/smoke_dry.log"
fi

echo "== 5) 验收器 =="
T=$(mktemp)
printf '# 标题\n\n- BookDao.java:42 | 使用字符串拼接SQL\n\n{"status":"ok","output":"x"}\n' > "$T"
if python3 "$HERE/lib/verify.py" "$T" "size>10|heading:'^##?'|facts>=1|json" >/dev/null 2>&1; then ok "正向规则通过"; else bad "正向规则误判"; fi
if python3 "$HERE/lib/verify.py" "$T" "notgrep:'TODO'|size>99999" >/dev/null 2>&1; then bad "反向规则误判"; else ok "反向规则正确拒绝"; fi
rm -f "$T"

echo "== 6) 合成语料与金标准 =="
C=/tmp/smoke_legacy
rm -rf "$C"
timeout 120 python3 "$HERE/../validate/mklegacy.py" --out "$C" --text-mb 0.3 --jar-mb 2 --seed 7 2>&1 | sed 's/^/    /'
if [[ -f "$C/questions.json" ]]; then
  Q=$(python3 -c 'import json;print(len(json.load(open("'"$C"'/questions.json"))))')
  ok "金标准题数=$Q"
else
  bad "questions.json 未生成"
fi
mkdir -p /tmp/smoke_answers
python3 "$HERE/../validate/grade.py" --questions "$C/questions.json" --answers /tmp/smoke_answers --corpus "$C" 2>&1 | head -12 | sed 's/^/    /'
ok "评分器可执行（空答案 → 准确率应为 0）"

echo
echo "== 结果：PASS=$PASS FAIL=$FAIL =="
exit $(( FAIL > 0 ))
