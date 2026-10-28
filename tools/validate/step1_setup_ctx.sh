#!/usr/bin/env bash
# 验证第 1 步：确认模型默认上下文长度，并按方案创建 90K 上下文别名（仅元数据，不重新量化）
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/nightly/env.sh"

TAG="${OLLAMA_TAG}"
echo "== /api/show: $TAG =="
curl -s -m 10 "$OLLAMA_URL/api/show" -d "{\"name\":\"$TAG\"}" > /tmp/show.json
python3 - <<'PY'
import json
d = json.load(open("/tmp/show.json"))
mi = d.get("model_info", {}) or {}
print("  context_length :", mi.get("general.context_length", "?") or
      d.get("details", {}).get("context_length", "?"))
for k in ("general.architecture", "general.parameter_count", "qwen35moe.context_length",
          "qwen35moe.block_count", "qwen35moe.attention.head_count_kv"):
    if k in mi:
        print("  %-40s %s" % (k, mi[k]))
print("  parameters     :", (d.get("parameters") or "-")[:200])
PY

# ---- 创建 90K 上下文别名 ----
ALIAS="qwen3.6-35B-A3B-90k"
if curl -s -m 8 "$OLLAMA_URL/api/tags" | grep -q "\"$ALIAS"; then
  echo "== 别名 $ALIAS 已存在，跳过创建 =="
else
  echo "== 创建别名 $ALIAS（num_ctx=90000，仅元数据）=="
  MFD=$(mktemp -d)
  printf 'FROM %s\nPARAMETER num_ctx 90000\nPARAMETER num_predict 4096\n' "$TAG" > "$MFD/Modelfile"
  cat "$MFD/Modelfile"
  curl -s -m 900 "$OLLAMA_URL/api/create" -d "{\"name\":\"$ALIAS\",\"from\":\"$TAG\",\"files\":{}}" \
    > /tmp/create.json 2>&1
  head -c 300 /tmp/create.json; echo
  rm -rf "$MFD"
fi

# ---- 把别名登记进 OpenCode 配置（先备份） ----
OCJSON="$HOME/.config/opencode/opencode.json"
if [[ -f "$OCJSON" ]]; then
  cp -n "$OCJSON" "$OCJSON.bak.$(date +%F-%H%M%S)"
  python3 - "$OCJSON" "$ALIAS" <<'PY'
import json, sys
p, alias = sys.argv[1], sys.argv[2]
d = json.load(open(p, encoding="utf-8"))
prov = (d.get("provider") or {}).get("local-ollama")
if prov is None:
    print("  未找到 local-ollama provider，跳过")
    sys.exit(0)
models = prov.setdefault("models", {})
if alias in models:
    print("  配置已含", alias)
else:
    models[alias] = {"name": "Qwen3.6 35B A3B (90K ctx)"}
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("  已登记 model ref: local-ollama/" + alias)
PY
fi
echo
echo "== 结果 =="
curl -s -m 8 "$OLLAMA_URL/api/tags" | python3 -c '
import sys,json
d=json.load(sys.stdin)
for m in d.get("models",[]):
    if "35B" in m.get("name",""): print("  ", m.get("name"), round(m.get("size",0)/1e9,1),"GB")
'
