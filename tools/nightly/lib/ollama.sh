#!/usr/bin/env bash
# Ollama 健康检查 / 预热 / 吞吐基准（JSON 用 python3 解析，避免依赖 jq）

ollama_alive() {
  curl -s -m 5 "$OLLAMA_URL/api/version" >/dev/null 2>&1
}

ollama_model_ready() {
  curl -s -m 8 "$OLLAMA_URL/api/tags" | "$PY" -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
names = [m.get("name","") for m in d.get("models",[])]
want = "'"$WARM_MODEL"'"
sys.exit(0 if any(want == n or n.startswith(want + ":") for n in names) else 1)
'
}

# 预热：keep_alive=-1 常驻，避免每个分片都冷启动（22GB 模型冷启动可达数分钟）
ollama_warm() {
  log_info "预热模型 $WARM_MODEL（num_ctx=$NUM_CTX，首次加载可能数分钟）"
  curl -s -m 1200 "$OLLAMA_URL/api/generate" \
    -d "{\"model\":\"$WARM_MODEL\",\"keep_alive\":-1,\"prompt\":\"ok\",\"options\":{\"num_ctx\":$NUM_CTX,\"num_predict\":1}}" \
    >/dev/null 2>&1
  ollama_alive
}

# 吞吐基准：输出 "decode_tps prefill_tps"
# 注意：prompt 必须足够长且带随机 nonce，否则会命中 prompt cache，
# 导致 prompt_eval_count 极小、算出的 prefill_tps 严重失真（实测出现过 60 与 1448 两种值）。
ollama_bench() {
  local n="${1:-256}"
  local nonce; nonce=$(date +%s%N)
  local filler=""
  local i
  for i in $(seq 1 40); do
    filler="${filler}第${i}段：该系统是一个基于 Java Web 的图书管理系统，包含图书、分类与用户管理模块，数据访问层通过 JDBC 访问 MySQL。"
  done
  local json
  json=$(curl -s -m 900 "$OLLAMA_URL/api/generate" -d "{
    \"model\":\"$WARM_MODEL\",\"stream\":false,\"keep_alive\":-1,
    \"options\":{\"num_ctx\":$NUM_CTX,\"num_predict\":$n,\"temperature\":0},
    \"prompt\":\"nonce=${nonce}\n${filler}\n请用一句话总结上面文档的主题。\"}")
  echo "$json" | "$PY" -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print("0 0"); sys.exit(0)
ec = d.get("eval_count", 0) or 0
ed = d.get("eval_duration", 1) or 1
pc = d.get("prompt_eval_count", 0) or 0
pd = d.get("prompt_eval_duration", 1) or 1
print(f"{ec/(ed/1e9):.2f} {pc/(pd/1e9):.1f}")
'
}

# 工具调用能力探测：返回 SUPPORTED / NOT_SUPPORTED
ollama_tool_probe() {
  local json
  json=$(curl -s -m 300 "$OLLAMA_URL/api/chat" -d "{
    \"model\":\"$WARM_MODEL\",\"stream\":false,
    \"messages\":[{\"role\":\"user\",\"content\":\"用 read_file 工具读取 pom.xml\"}],
    \"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"read_file\",\"description\":\"读取文件\",
      \"parameters\":{\"type\":\"object\",\"properties\":{\"path\":{\"type\":\"string\"}}}}}]}")
  if echo "$json" | grep -q 'tool_calls'; then echo SUPPORTED; else echo NOT_SUPPORTED; fi
}

ollama_ps() { curl -s -m 8 "$OLLAMA_URL/api/ps"; }
