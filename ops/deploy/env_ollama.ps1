<#
.SYNOPSIS
    配置 Ollama 的资源稳定性环境变量（规格书第五节第 5 条）。

.DESCRIPTION
    以「机器级」写入，Ollama 服务重启后生效。改动前请确认 L20 为独占使用。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File ops/deploy\env_ollama.ps1
    powershell -ExecutionPolicy Bypass -File ops/deploy\env_ollama.ps1 -KvCache ""   # 关闭 KV cache 量化
#>
param(
    [string]$KvCache = "q8_0",
    [switch]$DryRun
)

$vars = [ordered]@{
    OLLAMA_NUM_PARALLEL       = "1"
    OLLAMA_MAX_LOADED_MODELS  = "1"
    OLLAMA_KEEP_ALIVE         = "30m"
    OLLAMA_LOAD_TIMEOUT       = "900"
    # 单卡 L20 上显存优先；如需更高吞吐可改为 f16（显存占用约翻倍）
    OLLAMA_FLASH_ATTENTION    = "1"
}
if ($KvCache) { $vars["OLLAMA_KV_CACHE_TYPE"] = $KvCache }

foreach ($k in $vars.Keys) {
    $v = $vars[$k]
    if ($DryRun) {
        Write-Host "[dry-run] setx /M $k $v"
        continue
    }
    [Environment]::SetEnvironmentVariable($k, $v, "Machine")
    Write-Host ("[env] {0}={1}" -f $k, $v) -ForegroundColor Green
}

Write-Host ""
Write-Host "注意：机器级环境变量对已运行的服务不生效，需重启 Ollama 服务：" -ForegroundColor Yellow
Write-Host "  Restart-Service Ollama          # 若以 Windows 服务方式安装（Servy/bty）"
Write-Host "  # 或：任务管理器结束 ollama.exe 后重新启动"
Write-Host ""
Write-Host "验证：curl http://127.0.0.1:11434/api/tags"
Write-Host "自检：python ops/smoke_backend.py --profile ollama_qwen38 --effort off"
