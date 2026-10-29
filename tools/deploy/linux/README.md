# Linux 部署（systemd）

Windows 侧 `tools/deploy/*.ps1` + `tools/watchdog.ps1` 的 Linux 对应物。
流水线核心（`orchestrator.py` / `pipeline/` / `tools/jlp`）本身跨平台，本目录只补**外围运维**。

## 文件对照

| Linux | Windows 对应 | 作用 |
|---|---|---|
| `install.sh` | `tools/deploy/register_task.ps1` + `task_definition.xml` | 渲染单元模板、安装、启用/禁用定时器 |
| `run_nightly.sh` | `task_definition.xml` 的 `<Exec>` | 单实例（flock）启动编排器 |
| `watchdog.sh` | `tools/watchdog.ps1` | 心跳超时则杀僵死进程并重启 |
| `legacy-nightly.service/.timer` | 计划任务 `LegacyCodeNightly` | 每日定时 + 8 小时上限 + 失败重试 |
| `legacy-watchdog.service/.timer` | 计划任务 `LegacyCodeNightlyWatchdog` | 每 5 分钟做一次心跳检查 |
| `ollama.env` | `tools/deploy/env_ollama.ps1` | Ollama 资源稳定性环境变量 |
| `ollama.service` | `ollama_service.md` 的方式二/三 | Ollama 常驻 + 崩溃自动拉起 |
| `nightly.env` | （由 install.sh 生成） | PROJECT / PROFILE / 心跳路径等，兼作 systemd `EnvironmentFile` |
| `../../jlp.sh` | `jlp.ps1` | 事实层分析器入口 |

---

## 0. 前置

```bash
# Python 3.11+（requirements.txt 注明）
python3 -V

# UTF-8 locale：cron / systemd 环境下默认是 C，中文日志与报表会出问题
sudo localectl set-locale LANG=C.UTF-8
# 或仅对服务生效：unit 里已可加 Environment=LANG=C.UTF-8，见下文「排障」

sudo git clone <repo> /opt/llm-legacy-code-pipeline
cd /opt/llm-legacy-code-pipeline
python3 -m pip install -r requirements.txt
python3 tools/fetch_tokenizer.py            # Qwen 词表，只需一次

# 自检（应与 Windows 上同样是 116 passed）
python3 -m pytest contract_tests tests -q
```

`orchestrator.py` 的 `--config` 默认是相对路径 `config/pipeline.yaml`，
因此**必须在仓库根目录执行**；`run_nightly.sh` 已经 `cd "$REPO_ROOT"`。

若 clone 后脚本没有可执行位（`bash: ./install.sh: Permission denied`）：

```bash
chmod +x tools/deploy/linux/*.sh jlp.sh
```

（`install.sh` 本身也会给这几个脚本补一次 `chmod 0755`。）

---

## 1. 注册流水线（等价 register_task.ps1）

### 方式 A：注册但保持定时器 disabled（推荐首夜，等价 `-Manual`）

```bash
sudo tools/deploy/linux/install.sh \
    --project /data/supermarketmanager \
    --profile ollama_qwen38 \
    --manual

sudo systemctl start legacy-nightly         # 手动跑（等价 schtasks /Run）
sudo systemctl stop legacy-nightly          # 停（等价 schtasks /End）
sudo systemctl status legacy-nightly
```

### 方式 B：每日 01:00 自动启动，最长 8 小时（等价 `-Schedule -Start 01:00`）

```bash
sudo tools/deploy/linux/install.sh \
    --project /data/supermarketmanager \
    --profile ollama_qwen38 \
    --schedule --start 01:00 --duration 8h
```

`--schedule` 会顺带启用看门狗定时器；`--manual` 时看门狗单元也会安装，
但保持 disabled，需要自检时可手动 `systemctl start legacy-watchdog`，
或安装时显式加 `--watchdog`。

### 其它常用开关

```bash
--run-as USER      # 以指定用户运行（默认 root）
--user             # 安装为 ~/.config/systemd/user 下的用户单元，无需 root
--duration 480m    # 改动时长上限（systemd 时间跨度）
--python /usr/bin/python3.11
sudo tools/deploy/linux/install.sh --uninstall        # 卸载（--user 模式加 --user）
```

用户单元在会话退出后会停，服务器场景需要：

```bash
sudo loginctl enable-linger "$USER"
```

### 语义对齐说明

| Windows 计划任务 | systemd 实现 |
|---|---|
| `ExecutionTimeLimit=PT8H` | `TimeoutStartSec=8h` + `RuntimeMaxSec=8h`（编排器自己也守窗口，这里是硬兜底） |
| `RestartOnFailure` 3 × 10min | `Restart=on-failure` + `RestartSec=600` + `StartLimitBurst=3` / `StartLimitIntervalSec=86400` |
| `MultipleInstancesPolicy=IgnoreNew` | `run_nightly.sh` 里的 `flock -n`（已有实例在跑则退出 0） |
| `StartWhenAvailable=true` | timer 的 `Persistent=true`（错过执行点后补跑） |
| `/RU SYSTEM /RL HIGHEST` | 系统级单元，默认 root |
| `>> logs\orchestrator.stdout.log 2>&1` | `StandardOutput=append:` / `StandardError=append:`（需 systemd ≥ 240） |

**退出码 2 是正常收尾**（时间窗耗尽，见主 README 4.3），因此 unit 里写了
`SuccessExitStatus=0 2`，否则 systemd 会把正常收尾当成失败并触发重试。

---

## 2. 看门狗

心跳文件 `runtime/<项目slug>/state/heartbeat.json` 由编排器每 30s 原子写一次
（`slug` 由 `--project` 目录名派生，与编排器运行时隔离一致；看门狗按同一 `slug` 读取）。
`legacy-watchdog.timer` 每 5 分钟调起一次 `watchdog.sh` 做**单次**检查
（与 Windows 版一致：不做常驻进程）。

判定逻辑与 `tools/watchdog.ps1` 完全相同：

- 心跳文件不存在 → 视为从未启动，跳过（避免无限重启）；
- 心跳不可解析 → 按超时处理；
- 心跳年龄 > 600s（`WATCHDOG_THRESHOLD_SEC`）→ 先按心跳里记录的 pid 发 `TERM`，
  再兜底 `pkill -f 'orchestrator\.py'`，等 5s，然后 `systemctl start legacy-nightly`；
- 没有 systemd 时（容器/手动值守）→ 用 `setsid nohup` 直接拉起编排器。

```bash
sudo systemctl start legacy-watchdog              # 手动检查一次
tail -f logs/watchdog.log
./tools/deploy/linux/watchdog.sh --dry-run        # 只判断不动作
```

---

## 3. Ollama 服务（等价 ollama_service.md + env_ollama.ps1）

```bash
# 变量含义见 ollama.env 里的注释；改完需重启服务才生效
sudo tools/deploy/linux/install.sh --project /data/supermarketmanager --with-ollama \
    --ollama-bin /usr/local/bin/ollama --ollama-user ollama

sudo systemctl status ollama
curl http://127.0.0.1:11434/api/tags
```

若系统已自带 `ollama.service`（官方安装脚本会装），只把 `ollama.env` 挂进去即可，
不要重复安装：

```ini
# sudo systemctl edit ollama
[Service]
EnvironmentFile=/opt/llm-legacy-code-pipeline/tools/deploy/linux/ollama.env
```

`num_ctx` **不在环境变量里设**：编排器对每个请求显式下发 `options.num_ctx=92160`，
不依赖全局默认（规格书硬性要求）。

---

## 4. 无 systemd 时（cron / 容器）

```bash
# crontab -e
0 1   * * * cd /opt/llm-legacy-code-pipeline && ./tools/deploy/linux/run_nightly.sh  >> logs/cron.log 2>&1
*/5 * * * * cd /opt/llm-legacy-code-pipeline && ./tools/deploy/linux/watchdog.sh      >> logs/cron.log 2>&1
```

cron 环境里 `PATH` 很窄，且默认 locale 是 `C`，建议在 crontab 顶部加：

```bash
PATH=/usr/local/bin:/usr/bin:/bin
LANG=C.UTF-8
PYTHONUTF8=1
```

容器里没有 cron 时，让看门狗常驻即可（它顺带承担重启职责，但**首次启动仍需手动**）：

```bash
./tools/deploy/linux/watchdog.sh --loop --interval 300
```

---

## 5. 验收清单（迁移当天）

- [ ] `python3 -m pytest contract_tests tests -q` 全绿（与 Windows 同数：116 passed）
- [ ] `python3 tools/smoke_backend.py --profile ollama_qwen38 --effort off` 能拿到结果
- [ ] `models/qwen2_bpe/tokenizer.json` 已就位（否则 token 估算退化为启发式 ×1.18）
- [ ] `systemctl status legacy-nightly` 一次手动跑完整，退出码 0 或 2
- [ ] `logs/orchestrator.stdout.log` 与 `logs/orchestrator.log` 中文正常（无 `?`/乱码）
- [ ] `runtime/<项目slug>/state/heartbeat.json` 每 30s 更新
- [ ] 杀掉编排器后等 10 分钟，看门狗能把它拉起来
- [ ] `nvidia-smi` 可用（不可用也不影响运行，显存采样会优雅跳过）

---

## 6. 排障

| 现象 | 排查 |
|---|---|
| 日志中文乱码 | `localectl status` 看 LANG；或在 unit 的 `[Service]` 加 `Environment=LANG=C.UTF-8 PYTHONUTF8=1` |
| `StandardOutput=append:` 报错 | systemd < 240；把 `append:` 换成 wrapper 里的 `>>` |
| `PROJECT 未配置` | `nightly.env` 未生成或被删；重跑 `install.sh` |
| 定时器没触发 | `systemctl list-timers 'legacy-*'`；用户单元需 `loginctl enable-linger` |
| 启动即退出、无日志 | `journalctl -u legacy-nightly -b`，再看 `logs/orchestrator.stdout.log` |
| 路径含空格 | systemd `EnvironmentFile` 不支持，`install.sh` 会直接报错；改用不含空格的软链接 |

---

## 7. 与 Windows 的行为差异（仅此两处）

1. **文件系统大小写敏感**：Linux 区分大小写，`tools/jlp/lib_model.py` 按字面的
   `WebRoot` 匹配目录；老工程若实际目录叫 `webroot`，Windows 能匹配而 Linux 不能。
2. **日志轮转**：Windows 侧靠 `TimedRotatingFileHandler`（保留 14 天）+ 计划任务重定向；
   Linux 侧同样靠 `TimedRotatingFileHandler`，但 `orchestrator.stdout.log` 会一直追加，
   建议加 logrotate：

```bash
# /etc/logrotate.d/legacy-nightly
/opt/llm-legacy-code-pipeline/logs/orchestrator.stdout.log {
    daily
    rotate 14
    copytruncate
    missingok
    notifempty
}
```
