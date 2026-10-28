#!/usr/bin/env bash
#
# jlp - JSP 遗留项目分析器（Linux 入口，jlp.ps1 的对应物）
#
# 对一个 JSP 老项目做只读静态扫描，产出人类可读的需求分析文档到 out/<项目名>。
# 默认不联网、不调用任何模型。
#
# 用法：
#   ./jlp.sh --src /data/supermarketmanager
#   ./jlp.sh --src ./someapp --out ./out/someapp --stages structure,deps
#   ./jlp.sh --self-test
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JLP_PY="$HERE/tools/jlp/jlp.py"

[[ -f "$JLP_PY" ]] || { printf '[jlp] not found: %s（请在仓库根目录运行）\n' "$JLP_PY" >&2; exit 2; }

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    printf '[jlp] 找不到 python3，请先安装 Python 3.8+\n' >&2
    exit 2
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
    printf '[jlp] python 版本过低：%s，jlp 需要 >= 3.8\n' "$("$PY" --version 2>&1)" >&2
    exit 2
fi

# 等价 jlp.ps1 里的 chcp 65001 + PYTHONUTF8=1：保证中文报表不打成问号
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
: "${LANG:=C.UTF-8}"
: "${LC_ALL:=C.UTF-8}"
export LANG LC_ALL

exec "$PY" "$JLP_PY" "$@"
