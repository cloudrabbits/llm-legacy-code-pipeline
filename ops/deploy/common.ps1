# Windows 部署/守护脚本的公共片段：由 ops/watchdog.ps1 等 dot-source。
#
# 存在的唯一目的：让「项目 slug 派生」在 PowerShell 侧只有一份实现，
# 并且能被 tests/test_slug_consistency.py **单独**加载来校验一致性
# （若去 dot-source 整个 watchdog.ps1，会连带执行看门狗的杀进程逻辑）。
#
# 派生规则必须与下面两处完全一致：
#   pipeline/util.py                project_slug()   <- 唯一真源（Python）
#   ops/deploy\linux\common.sh    _project_slug()  <- bash
#
# 一旦漂移，看门狗会读到错误的心跳路径（runtime\<slug>\state\heartbeat.json），
# 进而判定「心跳超时」并杀掉一个**正在正常运行**的编排器。

function Get-ProjectSlug {
    param([string]$Project)

    # 等价于 Python 侧的 os.path.basename(os.path.normpath(project))：
    # 先去掉结尾的路径分隔符，再取最后一段。
    $raw = $Project.TrimEnd('\', '/')
    $name = Split-Path -Leaf $raw
    if (-not $name) { $name = 'project' }
    $safe = $name -replace '[^A-Za-z0-9._-]+', '_'
    if (-not $safe) { $safe = 'project' }
    return $safe
}
