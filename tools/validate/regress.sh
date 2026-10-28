#!/usr/bin/env bash
# 全量回归：py 编译 + sh 语法 + 冒烟 + 续跑验证
set -uo pipefail
T="/mnt/d/IdeaProjects/LibrarySystem/tools"
cd "$T" || exit 1

echo "== py_compile =="
if python3 -m py_compile $(find . -name '*.py' -not -path './validate/results/*' 2>/dev/null) 2>&1; then
  echo "  PY_OK"
else
  echo "  PY_FAIL"
fi

echo "== bash -n =="
BAD=0
for f in $(find nightly validate -name '*.sh' | sort); do
  bash -n "$f" 2>/dev/null || { echo "  BAD $f"; BAD=1; }
done
[[ $BAD -eq 0 ]] && echo "  SH_OK"

echo "== smoke =="
timeout 300 bash nightly/smoke_test.sh 2>&1 | tail -6

echo "== resume =="
timeout 180 bash nightly/test_resume.sh 2>&1 | tail -4
