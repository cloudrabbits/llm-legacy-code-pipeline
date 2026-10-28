#!/usr/bin/env bash
# 验证第 0 步：确认 Ollama / 模型 / OpenCode 三者对齐（秒级，不加载模型）
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nightly/env.sh"

echo "== Ollama =="
curl -s -m 8 "$OLLAMA_URL/api/version"; echo
echo "-- 已加载模型 --"
curl -s -m 8 "$OLLAMA_URL/api/tags" > /tmp/tags.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/tags.json"))
for m in d.get("models", []):
    det = m.get("details", {}) or {}
    print("  %-34s %6.1fGB  family=%s  params=%s" % (
        m.get("name"), m.get("size", 0) / 1e9,
        det.get("family", "?"), det.get("parameter_size", "?")))
PY
echo "-- 当前驻留 --"
curl -s -m 8 "$OLLAMA_URL/api/ps" > /tmp/ps.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/ps.json"))
ms = d.get("models", [])
if not ms:
    print("  (无驻留模型)")
for m in ms:
    print("  %-34s VRAM=%.1fGB RAM=%.1fGB" % (
        m.get("name"), m.get("size_vram", 0) / 1e9, m.get("size", 0) / 1e9))
PY

echo
echo "== OpenCode =="
echo "  路径: $(command -v opencode)"
opencode --version 2>&1 | head -2
echo "-- provider/model 配置 --"
python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.config/opencode/opencode.json")
try:
    d = json.load(open(p, encoding="utf-8"))
    for prov, cfg in (d.get("provider") or {}).items():
        for mid in (cfg.get("models") or {}):
            print("  可用 model ref: %s/%s" % (prov, mid))
except OSError as e:
    print("  读取失败:", e)
PY

echo
echo "== 目标变量 =="
echo "  MODEL=$MODEL"
echo "  WARM_MODEL=$WARM_MODEL"
echo "  ROOT=$ROOT"
echo "  SRC=$SRC"
