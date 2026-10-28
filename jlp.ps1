<#
.SYNOPSIS
    jlp - JSP 遗留项目分析器（Windows 入口）

.DESCRIPTION
    对一个 JSP 老项目做只读静态扫描，产出人类可读的需求分析文档到 out\<项目名>。
    默认不联网、不调用任何模型。

.EXAMPLE
    .\jlp.ps1 -ProjectPath D:\IdeaProjects\supermarketmanager
    .\jlp.ps1 -ProjectPath .\someapp -OutDir .\out\someapp -Stages structure,deps
    .\jlp.ps1 -SelfTest
#>

#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectPath,
    [string]$OutDir,
    [string]$Stages,
    [string[]]$ExcludeDir,
    [switch]$FactsOnly,
    [switch]$SelfTest,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

# ---- Windows 控制台统一 UTF-8，避免中文报表被打成问号 ----
try {
    chcp 65001 | Out-Null
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
} catch { }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$JlpPy     = Join-Path $ScriptDir 'tools\jlp\jlp.py'

if (-not (Test-Path -LiteralPath $JlpPy)) {
    Write-Host "[jlp] not found: $JlpPy (run from repo root)" -ForegroundColor Red
    exit 2
}

# ---- locate python ----
$py = $null
foreach ($cand in @('python', 'py', 'python3')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
    Write-Host "[jlp] Python not found. Install Python 3.8+ :" -ForegroundColor Red
    Write-Host "      winget install -e --id Python.Python.3.12" -ForegroundColor Yellow
    exit 2
}

$verRaw = (& $py --version 2>&1 | Out-String).Trim()
if ($verRaw -notmatch 'Python\s+(\d+\.\d+)') {
    Write-Host "[jlp] cannot read python version: $verRaw" -ForegroundColor Red
    exit 2
}
$ver = [version]$Matches[1]
if ($ver -lt [version]'3.8') {
    Write-Host "[jlp] python too old: $verRaw, jlp needs >= 3.8" -ForegroundColor Red
    exit 2
}
Write-Host "[jlp] python $verRaw" -ForegroundColor DarkGray

$argv = @()
if ($SelfTest) {
    $argv += '--self-test'
} else {
    if (-not $ProjectPath) {
        Write-Host "[jlp] missing -ProjectPath, e.g. .\jlp.ps1 -ProjectPath D:\IdeaProjects\supermarketmanager" -ForegroundColor Red
        exit 2
    }
    $full = (Resolve-Path -LiteralPath $ProjectPath -ErrorAction SilentlyContinue).Path
    if (-not $full) {
        Write-Host "[jlp] path not found: $ProjectPath" -ForegroundColor Red
        exit 2
    }
    $argv += '--src', $full
    if ($OutDir)      { $argv += '--out', $OutDir }
    if ($Stages)      { $argv += '--stages', $Stages }
    if ($ExcludeDir)  { foreach ($d in $ExcludeDir) { $argv += '--exclude-dir', $d } }
    if ($FactsOnly)   { $argv += '--facts-only' }
    if ($Quiet)       { $argv += '--quiet' }
}

Write-Host "[jlp] jlp.py $($argv -join ' ')" -ForegroundColor DarkGray
Write-Host ''

& $py $JlpPy @argv
$code = $LASTEXITCODE

Write-Host ''
if ($code -eq 0) {
    Write-Host '[jlp] done.' -ForegroundColor Green
} else {
    Write-Host "[jlp] failed, exit=$code" -ForegroundColor Red
}
exit $code
