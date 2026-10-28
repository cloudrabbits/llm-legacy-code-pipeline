# 夜间编排器（跨夜续跑版）使用说明

对应文档：`docs/nightly-automation-plan.md`（编排/守护）与 `docs/feasibility-validation-plan.md`（可分析性/验证/§5 跨夜设计）。

## 1. 一分钟上手

```bash
# 在 WSL 内（脚本位于 Windows 项目目录，通过 /mnt/d 访问亦可）
cd /mnt/d/IdeaProjects/LibrarySystem/tools/nightly

./nightly.sh --dry-run                 # 先看续跑清单，不调模型（排障首选）
./nightly.sh                           # 正式跑一夜（默认 --resume）
./nightly.sh --only T03                # 只跑一个任务
./nightly.sh --stop                    # 让正在运行的实例优雅停止
./summarize.sh --final                 # 生成跨夜最终报告
```

调度（每晚 23:25 唤起）：

```bash
# Kylin/Ubuntu：crontab
30 23 * * * cd /path/to/tools/nightly && ./nightly.sh >> ~/nightly/logs/cron.log 2>&1
# Windows + WSL：计划任务
schtasks /Create /TN "NightlyOpenCode" /SC DAILY /ST 23:25 /RL HIGHEST /F ^
  /TR "wsl.exe -d Ubuntu -u violet -- bash -lc 'cd /mnt/d/IdeaProjects/LibrarySystem/tools/nightly && ./nightly.sh'"
```

## 2. 目录与数据流

```
SRC(源项目) --rsync--> WORK(工作副本, ext4) --OpenCode--> WORK/docs|patches|staging
                                                    |
                                              OUT/*.raw.md（模型原始输出）
                                                    |
                                         lib/extract.py 抽取正文/交接卡/事实
                                                    |
                                          lib/verify.py 验收 -> SQLite 状态库
收尾：rsync 回传 docs/reports/patches/staging 到 SRC
```

运行时目录（默认 `~/nightly`）：

| 路径 | 内容 |
|---|---|
| `state.db` | 任务/分片/运行/事实/快照（SQLite） |
| `work/` | 被分析项目的工作副本 |
| `out/` | 每个分片的模型原始输出 |
| `logs/<date>/` | run.log、分片 stderr、验收结果 |
| `reports/` | 预检、每夜报告、resume-brief、final |
| `run/` | 当前分片 pid / 输出文件（看门狗用） |

## 2.5 调用通道（实测决定，别改错）

| `LLM_MODE` | 行为 | 何时用 |
|---|---|---|
| **`direct`（默认）** | 直连 Ollama `/api/generate`，`think=false`；上下文由脚本预取（L0 + input_range 文件原文） | 默认档。实测唯一稳定产出 |
| `opencode` | 走 OpenCode agent（模型可用 read/write 工具） | 需要模型自主探索、或模型指令遵从足够强时 |

实测依据（`docs/validation-report-2026-10-27.md` §2）：

- agent 模式下 `qwen3.6-35B-A3B` 会**"叙述意图但不执行"**：只回 `Now let me create the output directory and write the deliverable.` 就结束会话；极小请求固定开销 74–93 s；
- 直连 + 开思维链：3000 token 全被思考吃掉，且模型自述 *"I will simulate running `find|wc -l` and report plausible exact numbers"*（**会编造统计**）；
- 直连 + `think=false` + **L0 脚本图层**：60–75 s 产出可交付文档，行数/方法数全部正确。

所以：**事实必须由脚本给（`lib/l0.py`），模型只写叙述**。`TOOL_MODE` 同时默认 `text`（正文即产物，不依赖模型写文件）。

## 3. 关键机制

| 机制 | 实现 |
|---|---|
| 分片级断点 | `chunk` 表；长任务在 `tasks/<id>.chunks.tsv` 声明分片（示例：`T06.chunks.tsv`） |
| 三级停止 | SOFT(前30min) → CHECKPOINT(前5min) → HARD；`--stop` 或 SIGTERM 触发 |
| 原子写 | 产物先 `.tmp` → `sync` → `rename`，再写状态；杜绝半截文件 |
| 启动期修复 | `reset-running` + `ghosts`（清幽灵进度）+ `snap-diff`→`mark-stale`（精确失效） |
| 看门狗 | 分片输出静止超过 `STALL_MIN`(10min) 终止并重跑 |
| 幂等 | 分片输出路径固定、合并是纯脚本（`merge.sh`）、事实库按 pk upsert |
| L0 图层 | 每晚用 `lib/l0.py` 扫源码生成 `ai/context/L0-inventory.md`（行数/方法数/依赖边），注入每个分片 |
| 产物唯一来源 | 产物目录**不参与** rsync（阻止"回传的旧产物被灌回工作副本"），抽取时再用 `--since` 校验 mtime |
| 截止夜 | `DEADLINE_NIGHT`(默认4) 跳过 `WRAPUP_SKIP` 任务并强制出最终报告 |
| 人工暂停 | `touch ~/nightly/PAUSE` |

## 4. 常用配置（可用环境变量覆盖）

| 变量 | 默认 | 说明 |
|---|---|---|
| `PROJECT_ROOT` / `SRC` | 脚本上两级目录 | 被分析项目 |
| `ROOT` | `~/nightly` | 运行时目录（建议放 ext4，不要放 `/mnt/c`、`/mnt/d`） |
| `MODEL` | `local-ollama/qwen3.6-35B-A3B-90k` | 生产改为 Kylin 侧模型名 |
| `NUM_CTX` / `MAX_INPUT_TOKENS` | 90000 / 60000 | 上下文与单会话输入上限 |
| `HARD_STOP` | 07:10 | 硬停时刻 |
| `STALL_MIN` | 10 | 卡死判定分钟数 |
| `DEADLINE_NIGHT` / `WRAPUP_SKIP` | 4 / T09,T16 | 截止夜与跳过项 |
| `TOOL_MODE` | auto | `text` 强制从 stdout 抽取（模型无写文件能力时用） |

## 5. 验证工装（`../validate/`）

```bash
# 生成三类规模的合成老项目语料（含 30 题金标准）
python3 ../validate/mklegacy.py --out ~/legacy/b1 --text-mb 5  --jar-mb 20 --seed 7
python3 ../validate/mklegacy.py --out ~/legacy/b2 --text-mb 20 --jar-mb 60 --seed 7
python3 ../validate/mklegacy.py --out ~/legacy/b3 --text-mb 50 --jar-mb 120 --seed 7

# 两条对照臂
./run_experiment.sh --corpus ~/legacy/b1 --arm A --out results/armA
./run_experiment.sh --corpus ~/legacy/b1 --arm B --out results/armB

# 评分与指标
python3 ../validate/grade.py --questions ~/legacy/b1/questions.json --answers results/armA \
        --corpus ~/legacy/b1 --out results/armA.score.json
python3 ../validate/metrics.py --score armA=results/armA.score.json --score armB=results/armB.score.json \
        --scale runs.jsonl --compression comp.json --out reports/feasibility.json

# 跨夜混沌测试（V7）
./chaos.sh term | ./chaos.sh kill9 | ./chaos.sh change | ./chaos.sh crash
```

## 6. 自检脚本（不调用模型，秒级）

```bash
./smoke_test.sh     # 语法 + 状态库 + 干跑清单 + 验收器 + 合成语料 + 评分器
./test_resume.sh    # 跨夜续跑：跳过已完成、分片合并幂等、幽灵进度回退、变更精确失效
./chaos.sh term     # SIGTERM 优雅停止 / kill9 崩溃恢复 / change 变更失效 / crash 断电修复
```

已在本机（WSL Ubuntu 24.04）实测通过：`PASS=23 FAIL=0`，续跑脚本输出符合预期
（第 2 夜跳过 T01/T06、合并幂等、幽灵进度回退为 pending、变更文件精确命中 `BookDao.java`）。

## 7. 生产（Kylin V10 + L20 + Qwen3 27B）迁移前必做

1. `preflight.sh --niah`：实测 decode/prefill tok/s、工具调用能力、90K 检索曲线；
2. `ollama ps` + `nvidia-smi`：确认 `Q4_K_M + q8 KV` 组合装得下（fp8 权重 + fp16 KV ≈ 49GB 会 OOM）；
3. 编码普查：GBK/GB2312 需先转码副本；
4. 平台冒烟：OpenCode 二进制、cron/systemd、磁盘；
5. 用同一套 30 题金标准在生产上重跑，得到生产自己的准确率基线。
