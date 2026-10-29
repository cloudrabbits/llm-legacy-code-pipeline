# JSP/Java/Oracle 老项目 · 夜间无人值守分析流水线

把一个陌生的 JSP + 裸 Servlet + Oracle 老工程，在**夜间 8 小时无人值守**下，
跑出结构地图、模块边界、依赖矩阵、架构摘要与风险清单，最后汇总成一份晨报。

分两阶段交付，**同一套代码**：

| | 阶段一（外网仿真验证） | 阶段二（内网生产） |
|---|---|---|
| 后端 | DeepSeek V4.1-Flash 官方 API | Ollama（L20 单卡，qwen3.8:28b / family qwen35 / 27.3B / Q4_K_M） |
| 画像 | `deepseek_sim_qwen38` | `ollama_qwen38` |
| 窗口/预算 | 92160 / 80000 / 8192（**强制钳制**） | 同左 |
| 目的 | 验证切分可执行性、输出格式、断点续跑 | 验收 8 小时吞吐 |

**核心原则**：外网阶段主动放弃 DeepSeek 超出 qwen3.8:28b 的能力包络，否则验证无效。
窗口钳制、token 估算、推理档位全部按 Qwen 那侧算，DeepSeek 只是被当作一个"能力受限的远程后端"。

切换后端 = 改一个参数：

```powershell
python orchestrator.py --project D:\IdeaProjects\supermarketmanager --profile deepseek_sim_qwen38
python orchestrator.py --project D:\IdeaProjects\supermarketmanager --profile ollama_qwen38
```

---

## 1. 快速开始（外网仿真）

```powershell
cd D:\IdeaProjects\llm-legacy-code-pipeline

# 0) 依赖 + Qwen 词表（词表只需下一次，之后离线可用；内网只需拷 models\qwen2_bpe\）
python -m pip install -r requirements.txt
python tools\fetch_tokenizer.py

# 1) 自检：契约测试两个画像全绿
python -m pytest contract_tests tests -q

# 2) 后端冒烟（确认参数名/鉴权/归一化都对）
python tools\smoke_backend.py --profile deepseek_sim_qwen38 --effort off
python tools\smoke_backend.py --profile deepseek_sim_qwen38 --effort medium

# 3) 生成任务队列
python tools\plan_tasks.py --project D:\IdeaProjects\supermarketmanager

# 4) 先 dry-run（只跑纯脚本阶段，不花 token）
python orchestrator.py --project D:\IdeaProjects\supermarketmanager --dry-run --verbose

# 5) 真跑
python orchestrator.py --project D:\IdeaProjects\supermarketmanager --profile deepseek_sim_qwen38 --verbose
```

产物落在 `runtime/`：

```
runtime/artifacts/p0/{inventory.json, baseline.md}
runtime/artifacts/p1/P1-batch-00N.jsonl        # 文件分层打标
runtime/artifacts/p2/modules.json              # 模块边界
runtime/artifacts/p3/{deps.jsonl, violations.json, layer_matrix.md}
runtime/artifacts/p4/{<模块>.md, risks-<模块>.json}
runtime/artifacts/p5/{nightly_report.md, nightly_report.json}   # 晨报
runtime/state/{checkpoint.jsonl, index.json, heartbeat.json}
runtime/summaries/session-*.md                 # 跨会话摘要
logs/{orchestrator,backend,gpu}.log            # 按天轮转，保留 14 天
```

---

## 2. 架构：后端差异只允许存在于画像里

```
orchestrator.py          主循环（薄）：取任务 → 执行 → 落盘 → 心跳 → 到点收尾
pipeline/
  backend.py             薄适配器：Backend.complete(task) -> Result
  profiles/              ★ 后端差异唯一收敛点
    base.py              通用 JSON-over-HTTP 画像（报文形状由配置声明）
    deepseek_sim_qwen38.py / ollama_qwen38.py
  transports.py          HTTP JSON 传输 + 确定性桩传输
  tokenizer.py           Qwen BPE 精确计数 / 纯标准库启发式兜底
  models.py errors.py config_loader.py util.py
  checkpoint.py          append-only JSONL + os.replace 原子快照 + 启动重建
  artifacts.py           阶段产物与摘要（原子写，摘要 ≤4K token）
  session.py             会话状态机（≤6 轮 / 70K / 切模块 / 质量下降）
  context.py             预算装配与分块装箱
  planner.py             任务加载/校验/排序/软阻塞门禁
  executor.py            重试、指数退避、降级路由
  stages.py              P0–P5 阶段处理器
  scan.py                事实层：调用 tools/jlp 取结构化事实
  acceptance.py          产物自动验收
  monitor.py             心跳 + nvidia-smi 显存水位
  logging_setup.py       分类日志 + 按天轮转
config/
  budget.yaml            92160 / 80000 / 8192（三值不随后端变化）
  pipeline.yaml          时间窗、重试、门禁、资源、路径
  profiles/*.yaml        端点/模型/effort 映射/报文字段落位/响应字段落位
  secrets.local.yaml     密钥（gitignore）
tasks/*.json             任务队列（pydantic 校验）
contract_tests/          后端无关契约测试（同一套断言跑两个画像）
tests/                   单元测试 + dry-run 集成测试
tools/                   fetch_tokenizer / smoke_backend / plan_tasks / watchdog.ps1 / deploy/
                         （Linux：deploy/linux/{install.sh,run_nightly.sh,watchdog.sh} + jlp.sh）
```

**约束是自动强制的**：`tests/test_no_backend_branch.py` 会用 `tokenize` 剥掉注释与字符串，
只扫代码标识符；`pipeline/`、`orchestrator.py` 里出现 `deepseek` / `ollama` / `provider` 即失败。
后端名只允许出现在 `pipeline/profiles/`、`config/`、`tests/`、`tools/`。

后端差异全部体现在 YAML 的**声明式路径**里，例如：

```yaml
# config/profiles/deepseek_sim_qwen38.yaml
effort:
  reasoning_toggle: {path: thinking.type, enabled_value: enabled}
  payload:
    "off":    {thinking.type: disabled, reasoning_effort: null}
    "medium": {thinking.type: enabled,  reasoning_effort: high}
request_map:  {messages: messages, max_output_tokens: max_tokens, num_ctx: null}
response:
  text: choices.0.message.content
  reasoning: choices.0.message.reasoning_content
  finish_reason: choices.0.finish_reason
  prompt_comparable: false      # DeepSeek 计数与 Qwen 估算不可比
```

```yaml
# config/profiles/ollama_qwen38.yaml
effort:
  reasoning_toggle: {path: think, enabled_value: true}
  payload:
    "off":    {think: false}
    "medium": {think: true, reasoning_effort: medium}
request_map:  {messages: messages, max_output_tokens: options.num_predict, num_ctx: options.num_ctx}
response:
  text: message.content
  reasoning: message.thinking
  finish_reason: done_reason
  done_flag: done
  prompt_tokens: prompt_eval_count
  prompt_comparable: true
```

`num_ctx` 因此是**逐请求显式下发**的，不依赖 Ollama 全局默认。

---

## 3. 五个阶段

| 阶段 | 谁算 | 输入 | 产物 | 自动验收 |
|---|---|---|---|---|
| P0 基线 | 脚本 | 全库文件、编码、web.xml、SQL 建表 | `p0/inventory.json`、`baseline.md` | `llm_free`，零 LLM 调用 |
| P1 打标 | LLM | 按 30K token 装箱的源码批 | `p1/*.jsonl`（layer/module/risk） | 必含 `items`、layer 枚举正则、**脚本补齐未覆盖文件** |
| P2 模块边界 | 脚本骨架 + LLM 归并 | 脚本模块切分 + 路由表 + P1 标签 | `p2/modules.json` | 必含 `modules` |
| P3 依赖 | **脚本先算边，LLM 只判违规** | 跨层统计/可疑直连/未解析外部依赖 | `p3/deps.jsonl`、`violations.json`、`layer_matrix.md` | 必含 `violations` |
| P4 摘要+风险 | LLM | 脚本模块切片 + 该模块 P1 标签 | `p4/<模块>.md`、`risks-<模块>.json` | 必含 `summary`/`risks`，风险须带 evidence |
| P5 晨报 | 脚本 | P0–P4 全部产物 | `p5/nightly_report.md/.json` | `llm_free`，时间窗到点也会兜底补跑 |

**事实优先**：脚本已经算出来的东西（文件清单、路由、依赖边）一律先落盘，
只把**压缩视图**交给模型。首夜实测教训——让模型复述大表会撑爆 `max_tokens`
并截断成非法 JSON，改成"脚本算边 + 模型只判违规"后 P3 稳定通过。

---

## 4. 无人值守部署（Windows）

> Linux（systemd）部署见 [`tools/deploy/linux/README.md`](tools/deploy/linux/README.md)。
> 其中 `install.sh` / `run_nightly.sh` / `watchdog.sh` 与本节 4.1–4.3 一一对应，
> 流水线本体（`orchestrator.py` / `pipeline/` / `tools/jlp`）无需任何改动。
> 事实层入口在 Linux 上用 `./jlp.sh`（等价 `.\jlp.ps1`）。

### 4.1 注册计划任务

```powershell
# 方式 A（推荐首夜）：注册但 Enabled=false，需要时手动触发
powershell -ExecutionPolicy Bypass -File tools\deploy\register_task.ps1 `
    -Project D:\IdeaProjects\supermarketmanager -Manual

schtasks /Run /TN LegacyCodeNightly      # 手动跑
schtasks /End /TN LegacyCodeNightly      # 停
schtasks /Query /TN LegacyCodeNightly /V /FO LIST

# 方式 B：每日 01:00 自动启动，最长 8 小时
powershell -ExecutionPolicy Bypass -File tools\deploy\register_task.ps1 `
    -Project D:\IdeaProjects\supermarketmanager -Schedule -Start 01:00
```

任务定义用的是**完整 XML**（非"基本任务"模式）：`/RU SYSTEM /RL HIGHEST`、
`ExecutionTimeLimit=PT8H`、失败重试 3 次 × 10 分钟、忽略电池状态。

### 4.2 看门狗

```powershell
# 每 5 分钟检查一次心跳，10 分钟无心跳则杀掉僵死进程并重启
schtasks /Create /TN "LegacyCodeNightlyWatchdog" /SC MINUTE /MO 5 /RU SYSTEM /RL HIGHEST `
  /TR "powershell -ExecutionPolicy Bypass -File D:\IdeaProjects\llm-legacy-code-pipeline\tools\watchdog.ps1 -Project D:\IdeaProjects\supermarketmanager" /F
```

### 4.3 时间窗行为

到 8 小时（或 `--duration-hours`）后：**停止取新任务，在途任务跑完**，
然后强制补跑 P5 晨报并写 `RUN_END`，退出码 `2`（时间窗耗尽，属正常收尾）。

---

## 5. 迁移到内网（阶段二）

1. 拷 `models\qwen2_bpe\tokenizer.json`（7MB；缺了会退化为启发式 ×1.18 安全系数）。
2. `pip install -r requirements.txt`（或提前 `pip download` 离线包）。
3. Ollama 注册为服务：见 [`tools/deploy/ollama_service.md`](tools/deploy/ollama_service.md)，
   环境变量脚本 `tools\deploy\env_ollama.ps1`。
4. 改 `--profile ollama_qwen38`，跑一遍：

```powershell
python -m pytest contract_tests -q                                  # 必须与阶段一同样全绿
python tools\smoke_backend.py --profile ollama_qwen38 --effort off
python orchestrator.py --project <内网项目> --profile ollama_qwen38 --max-tasks 3 --verbose
```

5. 首夜实测吞吐（外网阶段**不验收**吞吐，只验收切分/格式/续跑）。

---

## 6. 契约测试：迁移一致性的证据

`contract_tests/test_contracts.py` 同一套断言在两个画像下各跑一遍：

| 断言 | 内容 |
|---|---|
| 预算钳制 | 79K 输入成功；81K 抛 `ContextOverflowError`，且断言**桩传输调用计数不变**（请求根本没发出） |
| 截断一致 | `max_tokens=2048` → `truncated=True`、`finish_reason=LENGTH`；正常结束为 `STOP` |
| effort 归一化 | `off` → `reasoning is None`；`medium` → 非空；`effort_applied` 为归一化档位 |
| 重试语义 | 极短 timeout → `attempts=3`、`error_class=TimeoutError`、`sleeps=[1,2]` |
| 归一化逐字段相等 | 两画像对同一逻辑输入产出完全相同的 `Result`（`backend_name` 除外） |
| SUSPECT 可比性 | 用量偏差同比例时：Ollama 标 `SUSPECT`，DeepSeek 不标（自有 tokenizer，标记即误报） |

```powershell
python -m pytest contract_tests tests -q     # 当前 116 passed
```

### 外网仿真实跑结果（`supermarketmanager`，7 个任务全绿）

```
P0-baseline    succeeded   66 个文本文件 / Java 33 / JSP 19 / 编码 utf-8-sig(65)+gb18030(1)
P1-batch-001   succeeded   prompt 30920  completion 5960
P1-batch-002   succeeded   prompt 27799  completion 3249
P2-modules     succeeded   4 个模块：Goods / Orders / Suppliers / Users
P3-deps        succeeded   脚本 207 条依赖边 + LLM 违规判定 0 条
P4-arch        succeeded   4/4 模块摘要，23 条带证据的风险
P5-report      succeeded   nightly_report.md
```

> 注：P2 有一次跑出 5 个模块（把登录拆成 `Auth`），因此 P4 采用
> `payload.module="auto"` —— 模块清单在运行时从 P2 产物读取，计划期不写死。

---

## 7. 已知限制

- **控制台中文显示**：日志与产物都是 UTF-8。旧版 PowerShell/cmd 若显示乱码，
  先 `chcp 65001`，读文件用 `Get-Content -Encoding UTF8`。计划任务里 stdout
  重定向到 `logs\orchestrator.stdout.log`，与 `.log` 文件一致，均为 UTF-8。

- **仿真不等于等价**：DeepSeek 与 qwen3.8:28b 的词表、指令遵循、长上下文衰减都不同。
  外网阶段能证明的是"切分可行、格式稳定、续跑可靠"，不是"输出质量相同"。
- `prompt_comparable=false` 的画像不做 SUSPECT 判定（DeepSeek 计数与 Qwen 估算不可比），
  这是**唯一**被允许的画像间行为差异，已由契约测试显式固定。
- 静态解析无法还原反射调用、运行时拼 SQL、动态 include，报告中以"提示"标注需人工确认。
- P1 按文件整体装箱；单文件若本身就超过批预算，`plan_tasks.py` 会给出警告，
  此时需要调小 `--batch-tokens` 或在 `pipeline/context.py` 的 `split_oversized` 路径上做文件内切分。

## 8. 待确认事项与内网实测结论

### 已确认（2026-10-29 内网 `/api/tags` + 单轮对话实测）

| 编号 | 事项 | 结论 |
|---|---|---|
| #1 | 内网模型确切版本 | `qwen3.8:28b`（family=qwen35，27.3B 参数，Q4_K_M，capabilities 含 thinking）；非初版 Qwen3-27B，`effort.mode` 维持 enum + 顶层 `think`，无需改 bool |
| #2 | Ollama 原生 `/api/chat` + 顶层 `think` | 实测可用：`think:false`→无 thinking，`think:true`→有 thinking；纯文本单轮对话正常 |
| #5 | 自定义 Modelfile / Jinja | 未使用，prompt 无需手拼 `<|im_start|>`，暂不需要 `raw:true` |

> 补充说明：`reasoning_effort` 顶层字段 Ollama **忽略且不报错**，仅 `think` 控制是否思考；
> 配置中保留该字段仅用于档位语义对称（`effort_applied` 归一化依赖档位名），不影响运行行为。
> response 各路径（text / reasoning / finish_reason / done / prompt_tokens）全部命中，无需改动。

### 仍待人工确认

| 编号 | 事项 | 落点 |
|---|---|---|
| #ext-1 | 官方 effort 映射是 `xhigh→high`；本配置按需求写 `xhigh→max`，一行可改回 | `config/profiles/deepseek_sim_qwen38.yaml` |
| #ext-2 | DeepSeek Tracking ID 的 header 名未公开，暂未启用 | 同上 `extra_headers` |

---

## 9. 事实层：`tools/jlp`（静态分析器）

本流水线的 P0/P2/P3 不自己造事实，而是调用仓库里既有的静态分析器
[`tools/jlp`](tools/jlp/README.md)——它只做**只读静态解析**：混编码降级解码、
Java/JSP/web.xml/SQL 解析、URL 路由还原、模块纵向切片、确定性风险规则（每条带证据）。

它零第三方依赖、自带 28 项离线自检，可独立使用：

```powershell
.\jlp.ps1 -ProjectPath D:\IdeaProjects\supermarketmanager
.\jlp.ps1 -SelfTest
```

```bash
# Linux
./jlp.sh --src /data/supermarketmanager
./jlp.sh --self-test
```

案例（`supermarketmanager`，MyEclipse 时代 JSP + Servlet + Oracle 工程）已被 `tools/jlp`
完整分析过，产出 4 个功能模块（Users / Suppliers / Goods / Orders），
本流水线的 P2/P4 结果与之一致——这也是选择"脚本算事实、模型做叙述"的直接原因。
