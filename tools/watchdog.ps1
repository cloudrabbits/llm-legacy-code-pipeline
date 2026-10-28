<#
.SYNOPSIS
    编排器看门狗：心跳超过阈值即杀掉僵死进程并重启。

.DESCRIPTION
    * 心跳文件由 orchestrator.py 每 30s 原子写一次（runtime\state\heartbeat.json）。
    * 本脚本默认只检查一次（由每 5 分钟的计划任务调起，避免自己变成常驻进程）。
    * 心跳文件不存在 = 从未启动过，不做处理，避免无限重启。

.EXAMPLE
    # 手动检查一次
    powershell -ExecutionPolicy Bypass -File tools\watchdog.ps1 -Project D:\IdeaProjects\supermarketmanager

.EXAMPLE
    # 注册为每 5 分钟运行一次的守护任务
    schtasks /Create /TN "LegacyCodeNightlyWatchdog" /SC MINUTE /MO 5 /RU SYSTEM /RL HIGHEST ^
      /TR "powershell -ExecutionPolicy Bypass -File D:\IdeaProjects\llm-legacy-code-pipeline\tools\watchdog.ps1 -Project D:\IdeaProjects\supermarketmanager" /F
#>
param(
    [string]$Project,
    [string]$Profile = "deepseek_sim_qwen38",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$ThresholdSeconds = 600,
    [string]$HeartbeatPath = ""
)

$ErrorActionPreference = "Stop"
$logDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logFile = Join-Path $logDir "watchdog.log"

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

if (-not $HeartbeatPath) { $HeartbeatPath = Join-Path $RepoRoot "runtime\state\heartbeat.json" }

if (-not (Test-Path $HeartbeatPath)) {
    Write-Log "心跳文件不存在（$HeartbeatPath），视为从未启动，跳过。"
    exit 0
}

try {
    $hb = Get-Content -Raw -Encoding UTF8 $HeartbeatPath | ConvertFrom-Json
    $age = [int]((Get-Date).ToUniversalTime() - [DateTimeOffset]::FromUnixTimeSeconds([int64]$hb.epoch).UtcDateTime).TotalSeconds
}
catch {
    Write-Log "心跳文件不可解析，按超时处理：$($_.Exception.Message)"
    $age = $ThresholdSeconds + 1
}

if ($age -le $ThresholdSeconds) {
    Write-Log ("心跳正常（{0}s < {1}s），pid={2}" -f $age, $ThresholdSeconds, $hb.pid)
    exit 0
}

Write-Log ("心跳超时 {0}s > {1}s，准备重启编排器。" -f $age, $ThresholdSeconds)

$procs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*orchestrator.py*" }

foreach ($p in $procs) {
    Write-Log ("停止僵死进程 pid={0}" -f $p.ProcessId)
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop } catch { Write-Log "停止失败：$($_.Exception.Message)" }
}
if ($procs) { Start-Sleep -Seconds 5 }

if (-not $Project) {
    Write-Log "未提供 -Project，无法自动重启；请带 -Project 参数重新注册守护任务。"
    exit 1
}

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { Write-Log "找不到 python.exe，无法重启。"; exit 1 }

$args = @("orchestrator.py", "--project", $Project, "--profile", $Profile)
Write-Log ("重启：{0} {1}" -f $py, ($args -join " "))
Start-Process -FilePath $py -ArgumentList $args -WorkingDirectory $RepoRoot -WindowStyle Hidden
exit 0
