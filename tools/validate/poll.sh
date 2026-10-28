#!/usr/bin/env bash
# 轮询验证进度：日志尾部 + 模型驻留 + 单元状态
# 用法：poll.sh [日志名]   （默认 val-preflight）
LOG="${1:-val-preflight}"
F="$HOME/nightly/logs/$LOG.log"
echo "=== unit: $LOG ==="
systemctl is-active "$LOG" 2>/dev/null || true
echo "=== log (tail 25) ==="
if [[ -f "$F" ]]; then
  wc -c < "$F" | tr -d '\n'; echo " bytes"
  tail -25 "$F"
else
  echo "(no log: $F)"
fi
echo "=== ollama ps ==="
curl -s -m 5 http://localhost:11434/api/ps > /tmp/ps.json 2>/dev/null
python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/ps.json"))
except Exception:
    print("  (ollama not reachable)")
    raise SystemExit
ms = d.get("models", [])
if not ms:
    print("  (no resident model)")
for m in ms:
    print("  %s  vram=%.1fGB  total=%.1fGB" % (
        m.get("name"), m.get("size_vram", 0) / 1e9, m.get("size", 0) / 1e9))
PY
