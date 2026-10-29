#!/usr/bin/env bash
#
# Linux 部署脚本的公共片段：由 watchdog.sh 与 run_nightly.sh 共同 source。
#
# 存在的唯一目的：让「项目 slug 派生」在 shell 侧只有一份实现。
# 派生规则必须与 pipeline/util.py 的 project_slug、以及 ops/watchdog.ps1
# 的 Get-ProjectSlug 完全一致，由 tests/test_slug_consistency.py 用同一组样例比对。
#
# 一旦漂移，看门狗会读到错误的心跳路径（runtime/<slug>/state/heartbeat.json），
# 进而判定「心跳超时」并重启一个**正在正常运行**的编排器。
#
# 本文件只被 source，不直接执行。

# 项目路径 -> runtime slug（仅 ASCII 字母数字、点、下划线、连字符）
#
# 注意：这里必须写成显式的 ASCII 区间 `[^A-Za-z0-9._-]`，**不能**用 `[:alnum:]`。
# `[:alnum:]` 受 locale 影响：在 UTF-8 locale 下 GNU sed 会认为「商城」也是字母数字，
# 从而原样保留，得到 `supermarket_商城`；而 Python 侧（`re` 的 `[^A-Za-z0-9._-]`）
# 与 PowerShell 侧得到的是 `supermarket_`。slug 一旦不一致，看门狗就会读错
# runtime/state/heartbeat.json，进而误杀正在正常运行的编排器。
_project_slug() {
    local name safe
    name="$(basename "${1%/}")"
    name="${name:-project}"
    safe="$(printf '%s' "$name" | sed -E 's/[^A-Za-z0-9._-]+/_/g')"
    printf '%s' "${safe:-project}"
}
