<#
.SYNOPSIS
    注册夜间分析流水线的计划任务（非「基本任务」模式，SYSTEM 账户，最高权限）。

.DESCRIPTION
    默认行为（规格书第五节第 4 条）：
      注册任务 -> 立即 /DISABLE，保持 Enabled=false，需要跑时用 -Manual 手动触发。
    加 -Schedule 则保持每日定时启用（默认 01:00 启动，最长 8 小时）。

.EXAMPLE
    # 注册但默认禁用（推荐首夜）
    powershell -ExecutionPolicy Bypass -File ops/deploy\register_task.ps1 `
        -Project D:\IdeaProjects\supermarketmanager -Manual

.EXAMPLE
    # 注册并启用每日 01:00 定时
    ... -Project D:\IdeaProjects\supermarketmanager -Schedule -Start 01:00
#>
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Profile = "deepseek_sim_qwen38",
    [string]$TaskName = "LegacyCodeNightly",
    [switch]$Manual,
    [switch]$Schedule,
    [string]$Start = "01:00",
    [string]$Duration = "PT8H",
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)

$ErrorActionPreference = "Stop"

if ($Manual -and $Schedule) {
    throw "只能在 -Manual 与 -Schedule 之间二选一。"
}
if (-not $Manual -and -not $Schedule) {
    Write-Host "[register] 未指定 -Manual/-Schedule，默认按 -Manual 处理（注册但禁用）" -ForegroundColor Yellow
    $Manual = $true
}

$template = Join-Path $PSScriptRoot "task_definition.xml"
if (-not (Test-Path $template)) { throw "找不到任务模板: $template" }
if (-not (Test-Path (Join-Path $RepoRoot "orchestrator.py"))) {
    throw "RepoRoot 看起来不对（缺少 orchestrator.py）: $RepoRoot"
}

$xml = Get-Content -Raw -Encoding UTF8 $template
$xml = $xml.Replace("{{REPO_ROOT}}", $RepoRoot)
$xml = $xml.Replace("{{PROJECT}}", $Project)
$xml = $xml.Replace("{{PROFILE}}", $Profile)
$xml = $xml.Replace("{{START_DATE}}", (Get-Date -Format "yyyy-MM-dd"))
$xml = $xml.Replace("{{START_TIME}}", $Start)
$xml = $xml.Replace("{{DURATION}}", $Duration)

$tmp = Join-Path $env:TEMP "nightly_task_$([guid]::NewGuid().ToString('N')).xml"
# schtasks 要求 UTF-16 编码的 XML
[System.IO.File]::WriteAllText($tmp, $xml, [System.Text.Encoding]::Unicode)

try {
    Write-Host "[register] 创建任务 $TaskName ..." -ForegroundColor Cyan
    schtasks /Create /TN $TaskName /XML $tmp /F /RU SYSTEM /RL HIGHEST | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "schtasks /Create 失败，退出码 $LASTEXITCODE" }

    if ($Schedule) {
        schtasks /Change /TN $TaskName /ENABLE | Out-Host
        Write-Host "[register] 已启用每日 $Start 定时（最长 $Duration）" -ForegroundColor Green
    }
    else {
        schtasks /Change /TN $TaskName /DISABLE | Out-Host
        Write-Host "[register] 已注册但保持 Enabled=false。手动触发：schtasks /Run /TN $TaskName" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "常用命令：" -ForegroundColor Gray
    Write-Host "  查看   : schtasks /Query /TN $TaskName /V /FO LIST"
    Write-Host "  手动跑 : schtasks /Run /TN $TaskName"
    Write-Host "  停     : schtasks /End /TN $TaskName"
    Write-Host "  删除   : schtasks /Delete /TN $TaskName /F"
}
finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
}
