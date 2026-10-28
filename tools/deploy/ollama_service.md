# 把 Ollama 注册为带自动重启的 Windows 服务

内网单卡 L20 上，Ollama 必须以服务方式常驻，且崩溃能自动拉起——
否则夜里模型进程一挂，整晚的算力就白费了。

推荐两种方式，任选一种。**不要**用 `ollama serve` 手动开窗口。

## 前置：环境变量

先执行（以管理员身份）：

```powershell
powershell -ExecutionPolicy Bypass -File tools\deploy\env_ollama.ps1
```

写入的机器级变量：

| 变量 | 值 | 作用 |
|---|---|---|
| `OLLAMA_NUM_PARALLEL` | `1` | 单卡不并发，避免显存翻倍 |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | 只驻留一个模型 |
| `OLLAMA_KEEP_ALIVE` | `30m` | 任务间隙不卸载，省掉反复加载 |
| `OLLAMA_LOAD_TIMEOUT` | `900` | 27B Q4 首次加载留足 15 分钟 |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | KV cache 量化，省显存（可选） |

`num_ctx` **不在这里设**：编排器对每个请求显式下发 `options.num_ctx=92160`，
不依赖全局默认（规格书硬性要求）。

## 方式一：Servy（图形化，推荐新手）

1. 下载安装 [Servy](https://github.com/aelassas/servy)。
2. 新建服务：
   - Name: `Ollama`
   - Executable: `C:\Users\<you>\AppData\Local\Programs\Ollama\ollama.exe`
   - Arguments: `serve`
   - Startup type: **Automatic (Delayed Start)**
   - Recovery: **Restart on failure, 3 次，间隔 10 秒**
3. 启动服务，确认 `curl http://127.0.0.1:11434/api/tags` 有响应。

## 方式二：bty（命令行）

```powershell
bty install ollama --bin "C:\Users\<you>\AppData\Local\Programs\Ollama\ollama.exe" --args "serve" --restart
bty start ollama
```

## 方式三：NSSM（最通用）

```powershell
nssm install Ollama "C:\Users\<you>\AppData\Local\Programs\Ollama\ollama.exe" serve
nssm set Ollama Start SERVICE_AUTO_START
nssm set Ollama AppExit Default Restart
nssm set Ollama AppRestartDelay 10000
nssm start Ollama
```

## 验收清单

```powershell
# 1) 服务在跑
Get-Service Ollama | Select-Object Status, StartType

# 2) 模型可用（应看到 qwen3.8-27b）
curl http://127.0.0.1:11434/api/tags

# 3) 逐请求 num_ctx 生效（观察返回的 prompt_eval_count 是否与估算接近）
python tools\smoke_backend.py --profile ollama_qwen38 --effort off

# 4) 显存水位
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

## 迁移当天的一次性检查

- [ ] `models/qwen2_bpe/tokenizer.json` 已拷到内网（否则 token 估算退化为启发式 ×1.18）
- [ ] `pip install -r requirements.txt` 可在内网离线安装（或提前 pip download）
- [ ] `python -m pytest contract_tests -q` 两个画像全绿
- [ ] `python tools\smoke_backend.py --profile ollama_qwen38` 能拿到结果
- [ ] 计划任务已注册但 `Enabled=false`，先手动跑一夜
