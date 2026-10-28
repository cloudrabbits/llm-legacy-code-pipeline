#!/usr/bin/env bash
# 原子写：先写 .tmp → sync → rename，保证中断时不会留下半截文件
# 用法：atomic_write <目标文件> <临时文件>
atomic_write() {
  local final="$1" tmp="$2"
  [[ -s "$tmp" ]] || { log_err "atomic_write: 临时文件为空 $tmp"; return 1; }
  mv -f "$tmp" "$final.tmp" || return 1
  sync "$final.tmp" 2>/dev/null || true
  mv -f "$final.tmp" "$final" || return 1
  return 0
}

# 估算 token（字符数 / CHARS_PER_TOKEN），中文偏保守
est_tokens() {
  local file="$1"
  local chars; chars=$(wc -c < "$file" 2>/dev/null || echo 0)
  echo $(( chars / ${CHARS_PER_TOKEN%.*} ))
}
