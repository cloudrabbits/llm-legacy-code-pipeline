# 老项目组件依赖改造方案（支持版）

> 适用对象：JSP + 裸 Servlet + Oracle 时代的 Java Web 老工程，依赖面覆盖
> Ant / Velocity / iBATIS 2 / Quartz / Apache POI / Axis / Commons 系列 /
> dom4j / Servlet API / JCE Provider(Sun) 以及若干闭源框架平台组件。
>
> 本方案由 `llm-legacy-code-pipeline` 的静态事实层（`tools/jlp`）支撑：
> **清单、数量、依赖边一律脚本产出**，LLM 只做叙述与归并，不产生事实。

---

## 1. 目标、约束与交付物

### 1.1 改造目标（可验收）

| 编号 | 目标 | 验收口径 |
|---|---|---|
| G1 | 依赖面**可枚举**：每个组件的使用位置、打包状态、配套缺失都有清单 | `02-dependencies.md` 的「组件改造台账」逐项非空且带证据 |
| G2 | 平台依赖**不再隐形**：容器/JDK 提供的 API（Servlet、JCE）单独成表 | 台账中出现 `servlet-api` / `jce-sunjce` 且带版本线索 |
| G3 | 风险**可追溯**：每条风险带文件级证据，可反查到具体类/行 | `10-requirement-analysis.md` 风险清单每条有 evidence |
| G4 | 改造**有顺序**：按破坏性与依赖关键路径排阶段，先定平台轨道再动业务组件 | 每个组件在台账里都有 `phase`（S0–S5）与 `breaking` |
| G5 | 回归**可判定**：每阶段有明确的入口/出口门禁与回滚点 | 第 5 节的验证矩阵全部有对应产物或命令 |

### 1.2 非目标

- 不做运行时改造（不动数据库、不改线上配置）——本方案只做静态识别、排序与门禁设计。
- 不替业务做技术选型（MyBatis vs JPA、CXF vs Spring WS 只给选项与代价，不给结论）。
- 不猜测闭源组件语义：闭源组件的信息**只能人工登记**（见 6.2）。

### 1.3 约束条件

| 约束 | 说明 | 落点 |
|---|---|---|
| C1 只读 | 不编译、不执行、不联网、不写入被分析目录 | `tools/jlp` 全流程 |
| C2 零第三方依赖 | 事实层只用 Python 标准库（≥3.8），扩展配置用 **JSON** 而非 YAML | `tools/jlp/lib_registry.py` |
| C3 事实优先 | 数量/清单/依赖边由脚本产出，LLM 不得生成事实 | `pipeline/stages.py` P0/P2/P3 |
| C4 后端无关 | `pipeline/`、`orchestrator.py` 中不得出现后端名 | `tests/test_no_backend_branch.py` |
| C5 快速失败 | 扩展配置**非法**直接抛错，不静默降级；**缺失**则视为该口子未启用 | `lib_registry.load()` |
| C6 无人值守 | 夜间 8 小时窗口，到点停止取新任务并兜底出报告 | `config/pipeline.yaml` |
| C7 不改默认行为 | 四个扩展口子默认全空 = 完全沿用脚本既有结论 | `config/legacy/modules.json` 等 |

### 1.4 交付物形式

| 交付物 | 路径 | 形态 | 谁维护 |
|---|---|---|---|
| 改造方案（本文） | `docs/legacy-modernization-plan.md` | Markdown | 架构组 |
| 组件改造台账配置 | `config/legacy/components.json` | JSON（内置基线 + 项目覆盖） | 架构组 + 厂商 |
| 闭源分派配置 | `config/legacy/dispatch.json` | JSON | 熟悉闭源平台的人 |
| 模块边界配置 | `config/legacy/modules.json` | JSON | 架构组 |
| 风险规则配置 | `config/legacy/risk_rules.json` | JSON | 架构组 + 安全 |
| 事实产物 | `runtime/<slug>/artifacts/p0/inventory.json`、`p0/baseline.md` | JSON + Markdown（自动生成） | 流水线 |
| 依赖与台账报告 | `out/<项目>/02-dependencies.md`、`facts.json` | Markdown + JSON（自动生成） | `tools/jlp` |
| 风险清单 | `out/<项目>/10-requirement-analysis.md` | Markdown（自动生成） | `tools/jlp` |
| 回归证据 | `tests/test_legacy_registry.py` | pytest | 架构组 |

命令：

```powershell
# 事实层单独跑（不改被分析项目）
.\jlp.ps1 -ProjectPath D:\IdeaProjects\supermarketmanager
# 指定另一套扩展配置（如内网项目 A / 项目 B 各一套）
python tools/jlp/jlp.py --src <项目> --rules D:\rules\projA
# 流水线（含 P0 基线里的组件台账）
python orchestrator.py --project <项目> --profile ollama_qwen38
```

---

## 2. 组件识别与依赖梳理

### 2.1 四条识别通道

脚本不靠"猜"，每条结论都对应一种**可复现的证据源**：

| 通道 | 证据 | 能抓到 | 抓不到 |
|---|---|---|---|
| A. import 命名空间 | `java` 单元的 `import` 前缀 | Commons 系列、dom4j、POI、Quartz、iBATIS、Velocity | 反射调用、全限定名直接使用 |
| B. 磁盘"物证" | jar 文件名、配置文件名（`build.xml`/`*.vm`/`sqlmap-config.xml`/`quartz.properties`/`*.wsdd`/`velocity.properties`） | Ant（无 import）、Velocity 模板、Axis 部署描述 | 未入库、被重命名的 jar |
| C. 代码特征 | 正文正则（`SqlMapClient`、`Security.addProvider`、`SAXReader`、`HSSFWorkbook`） | 无 import 的用法、字符串常量里的算法名 | 动态拼接的类名 |
| D. 平台命名空间 | `javax.*` / `sun.*` / `com.sun.*` | **Servlet API、JCE Provider** | ——（原先被 `PLATFORM_NS` 过滤，是本次补的通道） |

> 关键缺口（已修）：`lib_scan.PLATFORM_NS` 会把 `javax.*`/`sun.*` 从"第三方依赖"里过滤掉，
> 导致 Servlet API 与 JCE Provider 在报告里**完全隐形**——而升级容器/JDK 时恰恰是它们最先炸。
> 现在它们走 `lib_registry.detect_platform_deps()`，单独成表。

### 2.2 组件台账（内置基线）

| 组件 | 类别 | 识别证据 | 现状 | 迁移目标 | 破坏性 | 阶段 |
|---|---|---|---|---|---|---|
| Apache Ant | 构建 | `build.xml` + `org.apache.tools.ant` | maintenance | Maven 3.x / Gradle | 中 | S1 |
| Apache Velocity | 视图/模板 | `org.apache.velocity` + `*.vm`/`velocity.properties` | maintenance | Velocity 2.x；或 FreeMarker/Thymeleaf | 中 | S2 |
| iBATIS 2.x | 持久层 | `com.ibatis` + `sqlmap-config.xml` + `SqlMapClient` | **EOL** | MyBatis 3.5.x | 高 | S3 |
| Quartz | 调度 | `org.quartz` + `quartz.properties` + `CronTrigger` | maintenance | Quartz 2.x / Spring `@Scheduled` | 高 | S3 |
| Apache POI | 文档处理 | `org.apache.poi` + `HSSF/XSSFWorkbook` | active | POI 5.x（poi/poi-ooxml 成套） | 中 | S3 |
| Apache Axis 1.x | WebService | `org.apache.axis` + `server-config.wsdd`/`*.wsdl` | **EOL** | JAX-WS/CXF 或 REST | 高 | S3 |
| Commons BeanUtils | 工具库 | `org.apache.commons.beanutils` | maintenance | 1.9.4+；长期改显式拷贝 | 低 | S2 |
| Commons Collections | 工具库 | `org.apache.commons.collections` | maintenance | collections4（**包名带版本**） | 中 | S4 |
| Commons DBCP | 数据源 | `org.apache.commons.dbcp` + `BasicDataSource` | maintenance | dbcp2 / HikariCP / 容器 JNDI | 中 | S3 |
| Commons FileUpload | 工具库 | `org.apache.commons.fileupload` | maintenance | 1.5（修 DoS CVE）或 `@MultipartConfig` | 中 | S2 |
| Commons IO / Lang / Logging | 工具库/日志 | 对应命名空间 | active / maintenance | io 2.x、lang3、SLF4J + jcl-over-slf4j | 低 | S2 |
| dom4j | XML | `org.dom4j` + `SAXReader` | maintenance | 2.1.x（或 StAX/JAXB），关外部实体 | 低 | S2 |
| Servlet API | 平台 API | `javax.servlet` + `web.xml` 声明版本 | **EOL**（2.x–3.x 轨道） | `jakarta.servlet` 6.x / Tomcat 10.1+ | 高 | **S4** |
| JSP API | 平台 API | `javax.servlet.jsp` | EOL | `jakarta.servlet.jsp` 3.x | 高 | S4 |
| JCE Provider (Sun) | 安全/平台 API | `javax.crypto` + `Security.addProvider`/`SunJCE` + `sunjce_provider.jar` | maintenance | 标准 JCA 调用（不写死 Provider），按需引 BouncyCastle | 中 | S3 |
| 闭源框架平台组件 | 闭源 | **必须人工登记**（见 6.2） | unknown | 先隔离（防腐层），再按模块替换 | 高 | S5 |

> 台账字段由 `config/legacy/components.json` 与内置基线按 `id` 归并：
> **同 id 覆盖、新 id 追加、`enabled:false` 忽略**。改迁移目标/阶段只改配置，不改代码。

### 2.3 依赖梳理的输出口径

`02-dependencies.md` 新增两段，`facts.json` 新增 `components` / `platform_deps` 两个字段：

- **组件改造台账**：组件 / 类别 / 状态 / 引用次数 / war 内 jar（缺失标 `**未打包**`）/ 缺失配套 /
  迁移目标 / 破坏性 / 建议阶段 + 每条注意事项。
- **平台/容器/JDK 提供的依赖**：组件 / 由谁提供 / 状态 / 版本线索（Servlet 版本取自 `web.xml`
  `declared_version`）/ 引用次数 / 迁移目标 / 阶段 + 证据。
- P0 `inventory.json` / `baseline.md` 同步带上组件数与"停更或状态未知"清单，晨报可直接引用。

---

## 3. 改造范围与影响分析

### 3.1 影响维度

| 维度 | 看什么 | 从哪里取 |
|---|---|---|
| 耦合面 | 引用次数、涉及文件清单、跨层依赖边 | 台账 `usage` + `evidence`、`p3/deps.jsonl` |
| 可替换性 | active / maintenance / EOL / unknown | 台账 `status`（闭源默认 `unknown`） |
| API 破坏性 | 包名是否变更、接口是否变 | 台账 `breaking` |
| 运行时约束 | JDK 版本、容器版本、数据库方言 | `web.xml` 版本、`jdbc_urls`、SQL 方言 |
| 安全合规 | CVE、弱算法、内部 API | 风险规则（`risk_rules.json` + 内置 4 条） |
| 可回归性 | 是否有可对比的输出基线 | 见第 5 节（导出文件、SQL 结果集、HTTP 响应） |

### 3.2 关键路径（决定改造顺序）

```
JDK/容器版本定档 ──► javax -> jakarta（S4，全量改名）
        │                    ▲
        │                    │ 必须先定档，否则 Commons/POI/Quartz 的可选版本无从选择
        ▼
构建与依赖管理（S1，Ant -> Maven/Gradle）
        ▼
低风险升级（S2：Commons 升级、日志统一、安全补丁）
        ▼
破坏性替换（S3：iBATIS2 -> MyBatis、Quartz 1->2、Axis -> CXF、POI 3->5、JCE 规范化）
        ▼
命名空间迁移（S4：javax->jakarta、collections->collections4）
        ▼
闭源组件隔离与替换（S5：防腐层 + 契约测试）
```

**顺序约束（不可颠倒）**

1. **平台轨道先定**：Servlet/Jakarta 与 JDK 版本不定档，其余组件的版本选型全是猜测。
2. **构建先现代化**：没有依赖管理就无法锁定版本、无法做依赖树对比，回归也无从谈起。
3. **Commons 先升后迁**：先升到"同包名的安全版本"（S2），再做"改包名"的破坏性迁移（S4），
   两件事分开可以各回滚一次。
4. **闭源放最后**：闭源组件没有版本可选，只能先冻结接口、加防腐层，最后按模块替换。

### 3.3 影响面统计口径（脚本产出，禁止人工估）

- 每个组件：`usage`（import 命中数 + 代码特征命中数 + 物证文件数），`evidence` 最多 5 条文件级证据。
- 跨层违规与依赖边：`p3/deps.jsonl` + `p3/violations.json`（脚本算边，LLM 只判违规）。
- 组件状态派生风险：仍在用的 EOL/unknown 组件 → 一条"停更或状态未知"风险（带组件名清单）。

---

## 4. 分阶段改造策略与迁移路径

| 阶段 | 主题 | 主要内容 | 出口门禁 | 回滚方式 |
|---|---|---|---|---|
| **S0** | 盘点与基线 | 跑事实层、登记闭源组件、固化回归基线（HTTP 响应/SQL 结果集/导出文件） | 台账覆盖全部在用组件；基线快照入库 | 无（只读） |
| **S1** | 构建与平台轨道 | Ant → Maven/Gradle；定 JDK 与容器版本；清理手拷 jar | 依赖树可复现（`dependency:tree` 基线） | 构建脚本并存，双轨验证 |
| **S2** | 低风险升级 | Commons（beanutils/io/lang/logging/fileupload）、dom4j、Velocity 升安全版本；日志统一到 SLF4J | 编译通过 + 依赖树 diff 只剩预期项 + S0 基线全绿 | 版本号回退（同包名，回滚成本最低） |
| **S3** | 破坏性替换 | iBATIS2→MyBatis 3；Quartz 1→2；Axis→CXF/JAX-WS；POI 3→5；DBCP→dbcp2/HikariCP；JCE 规范化（去 Provider 硬编码、换弱算法） | 逐模块契约测试 + Oracle 方言分页专项 + 调度时序专项 | 双写/开关切换；保留旧实现到验收结束 |
| **S4** | 命名空间迁移 | `javax.*`→`jakarta.*`（Servlet/JSP/JSTL/EL）、collections→collections4 | 容器启动 + 全量 URL 冒烟 + 导出/上传专项 | 源码级全量改名，靠版本库整体回退 |
| **S5** | 闭源组件 | 冻结接口 → 防腐层 → 契约测试 → 按模块替换 | 适配器两侧契约测试一致 | 适配器开关（新旧实现并存） |

### 4.1 各组件的迁移要点（易踩坑）

| 组件 | 迁移要点 |
|---|---|
| iBATIS 2 → MyBatis 3 | `SqlMapClient`→`SqlSession`；`#v#`/`$v$`→`#{}`/`${}`；`<dynamic>`→`<if>/<where>`；手写事务边界→声明式事务；Oracle `ROWNUM` 分页改 Dialect 并逐条核对排序稳定性 |
| Quartz 1 → 2 | `Scheduler` 接口变更；`JobDetail`/`Trigger` 改用 Builder；`Job.execute` 异常签名变化；cron 表达式语义需逐个核对；集群模式下表结构也变 |
| Axis 1 → CXF/JAX-WS | **先冻结 WSDL 契约做回归基线**，再重新生成 stub；`server-config.wsdd` 部署模型不再适用 |
| POI 3 → 5 | 单元格类型枚举、颜色/字体 API、日期工具均有变更；大文件导出必须改 SXSSF 流式，否则 OOM；导出结果是天然回归基线 |
| Commons DBCP → dbcp2 | 包名加 `2`；`maxActive`→`maxTotal`、`maxWait`→`maxWaitMillis`；**配置漏改会静默回到默认值**，必须逐项核对 |
| Commons Collections → collections4 | 包名带版本号，是全量改名；同时确认没有反序列化利用链依赖（3.1 的 `InvokerTransformer` 是老问题） |
| Commons FileUpload | 上传是安全敏感面：大小限制、临时目录清理、文件名过滤、1.5 的 DoS 修复都要专项回归 |
| Velocity 1 → 2 | 包名不变但要求 Java 8+；`#set`/宏的行为差异需模板级回归；若只是渲染邮件模板，优先"保持现状 + 隔离"，不急着换引擎 |
| dom4j | 1.6.1 有 XXE 相关 CVE；升级同时必须关闭外部实体解析 |
| Servlet API | `javax`→`jakarta` 一次性全量改名；`web.xml` 从 2.x DTD 升到 3+ schema 时，Filter/Listener 顺序语义需复核 |
| JCE (SunJCE) | 去掉 `new SunJCE()` / `Security.addProvider` 硬编码；`sun.misc.BASE64Encoder` → `java.util.Base64`；MD5/SHA-1/DES/3DES/RC4 换成 SHA-256 系列 / AES-GCM / SM3-SM4（按合规要求） |
| 闭源组件 | 无版本可选：先冻结接口签名 → 加防腐层（业务侧只见自有接口）→ 用契约测试锁行为 → 再按模块替换实现 |

---

## 5. 兼容性与回归验证要求

### 5.1 分层验证矩阵

| 层 | 验证内容 | 判定方式 | 自动化程度 |
|---|---|---|---|
| L1 制品 | 编译通过、依赖树锁定、无重复/冲突版本 | `dependency:tree` diff 与 S1 基线逐项比对 | 全自动 |
| L2 接口 | 老 URL（含前端控制器 `*.do?action=x`）的响应码与关键字段 | S0 基线快照逐条 diff | 全自动（契约测试） |
| L3 数据 | SQL 结果集、分页边界、字符集（GBK/UTF-8）、事务边界 | 结果集快照 + 分页首/中/末页核对 | 半自动（需造数） |
| L4 运行 | 容器启动无错、Quartz 调度时序、POI 导出文件、上传落盘 | 启动日志 + 调度触发记录 + 导出文件结构比对 | 半自动 |
| L5 安全 | 依赖 CVE、弱算法、JDK 内部 API、外部实体解析 | 风险规则（脚本）+ 依赖扫描 | 全自动（规则部分） |
| L6 静态事实 | 组件台账、平台依赖、跨层违规、风险清单与改造前一致或更优 | 两次 `facts.json` diff | 全自动 |

### 5.2 各组件的专项回归点（必须逐项打勾）

| 组件 | 专项回归点 |
|---|---|
| iBATIS2 → MyBatis | 动态 SQL 每个分支执行结果一致；分页首/中/末页；`NULL` 与空串处理；批量提交的事务边界 |
| Quartz | 每个 Job 的触发时序与错峰；misfire 策略；集群下不重复执行 |
| Axis / WS | 请求/响应 XML 样本逐字段比对；异常（SoapFault）语义；超时与重试 |
| POI | 导出文件（xls/xlsx）可被打开且关键单元格一致；大文件内存曲线；日期/数字格式 |
| Commons DBCP | 连接池最大/最小/超时参数生效；连接泄漏检测；JNDI 数据源切换后仍可用 |
| Commons FileUpload | 超限文件、空文件、中文文件名、临时目录残留 |
| Velocity | 每个模板渲染输出逐字节比对（含转义与编码） |
| dom4j | XML 解析在关闭外部实体后不回归；大文件不 OOM |
| Servlet/JSP | 全量 URL 冒烟；Filter 链顺序；编码过滤器（GBK 老项目高频问题）；Session 行为 |
| JCE | 加解密结果与旧实现互通（迁移期必须双跑）；密钥长度与算法白名单；性能（换 Provider 后） |
| 闭源组件 | 适配器两侧契约测试；授权/License 机制不受影响；异常路径与超时 |

### 5.3 与本流水线的对接

- **改造前**：跑一次 P0–P5，产物作为"改造前基线"归档（`runtime/<slug>/` 已按项目隔离）。
- **改造中**：每个阶段结束后重跑 `tools/jlp`，diff 两份 `facts.json` 的
  `components` / `platform_deps` / 风险清单，确认"组件只减不增、风险只降不升"。
- **改造后**：P3 的跨层违规数、P4 的风险条目数应不高于基线；晨报 `p5/nightly_report.md`
  直接作为阶段验收材料的索引。

---

## 6. 扩展口子（预留，供后续自行补充）

四个口子统一放在 `config/legacy/`（JSON，纯标准库可读），由 `tools/jlp/lib_registry.py` 加载：

| 文件 | 解决什么 | 默认行为 |
|---|---|---|
| `components.json` | 组件识别与迁移台账（尤其是**闭源组件**） | 内置基线覆盖开源组件；闭源留模板占位 |
| `dispatch.json` | **闭源框架的分派机制** | 空 = 只走内置的 `action.equals` 解析 |
| `modules.json` | **模块边界划分** | 全空 = 沿用脚本的"类名后缀 + 调用边"切分 |
| `risk_rules.json` | **风险规则定义** | 内置 4 条通用规则 + 组件状态派生规则 |

**合并语义**（四个口子一致）：列表按 `id` 归并，**同 id 覆盖、新 id 追加，`enabled:false` 忽略**；
配置缺失 = 口子未启用；配置非法 = 抛 `ValueError` 快速失败（C5）。

加载位置可用环境变量 `JLP_RULES_DIR` 或 `--rules <目录>` 覆盖，便于**一个项目一套规则**。

### 6.1 组件登记（components.json）

```json
{
  "components": [
    {
      "id": "vendor-sdk",
      "name": "某闭源 SDK",
      "category": "闭源组件",
      "status": "unknown",
      "provided_by": "app",
      "namespaces": ["com.vendor.sdk"],
      "jar_patterns": ["vendor-sdk"],
      "file_markers": ["vendor-config.xml"],
      "code_patterns": ["extends\\s+com\\.vendor\\.framework\\.BaseAction"],
      "requires": [],
      "migration": {"target": "防腐层隔离后再替换", "breaking": "high", "phase": "S5"}
    }
  ]
}
```

- `provided_by`：`app`（打进 war）/ `container` / `jdk` / `unknown`。
  填 `container`/`jdk`/`unknown` 的组件走**平台依赖**通道，不会混进第三方表。
- `status: unknown` 会被"组件状态派生规则"抓成风险，提醒先确认厂商支持状态。
- 想改某个开源组件的迁移目标或阶段：用它的内置 `id`（如 `ibatis2`）写一条覆盖项即可。

### 6.2 闭源框架的分派机制（dispatch.json）

**为什么必须单独登记**：脚本默认只认 `if (action.equals("x"))`。闭源平台常见
"自研前端控制器 + 参数名不是 action + 路由写在 XML 里"，不登记的话，
**路由还原、模块归属、页面归属会整片为空**，后面所有分析都建立在空事实上。

```json
{
  "rules": [
    {
      "id": "vendor-param",
      "framework": "某闭源平台（请求参数分派）",
      "kind": "action_param",
      "action_param": "method",
      "branch_pattern": "\"(\\w+)\"\\.equals\\(\\s*method\\s*\\)",
      "action_group": 1,
      "front_controller_pattern": "extends\\s+com\\.vendor\\.framework\\.DispatchServlet"
    }
  ]
}
```

- `branch_pattern` + `action_group`：切分分支并取动作名（可同时登记多套）。
- `front_controller_pattern`：命中则该 Servlet 被视为**分派中枢**，
  不参与业务模块切分（否则会切出一个空壳模块）。
- `kind: xml_config` 的分派：脚本只能看到分发类、看不到分支，
  请同时填 `config_files` 并**人工核对**路由清单（当前不自动解析 XML 路由）。

### 6.3 模块边界划分（modules.json）

脚本默认按类名后缀（`Biz/Service/Dao/Servlet/Action/Manager`）取领域词作种子，
再用真实调用边挂页面。命名不规范、或分派被闭源框架接管导致切分错位时，在这里纠正：

```json
{
  "modules": {
    "seed_suffixes": ["Biz", "Service", "Dao", "Servlet", "Action", "Manager"],
    "domain_aliases": {"User": "Users"},
    "package_modules": {"com.hy.cxp.supermarket.order": "Orders"},
    "exclude_types": ["FrontController", "BaseAction"],
    "force_merge": [["Goods", "Stock"]]
  }
}
```

- `package_modules` 优先级**高于**类名后缀（闭源平台按包分层时最有用）。
- `exclude_types`：框架基类/基础设施不作为模块种子。
- `force_merge`：脚本切得过细时把 B 并入 A（合并 servlet/biz/dao/entity/tables）。
- 全部留空 = 完全沿用脚本默认行为（C7）。

### 6.4 风险规则定义（risk_rules.json）

声明式：给证据（命名空间 / 代码正则 / jar 关键字 / 文件名），命中即产出一条带证据的风险。

```json
{
  "rules": [
    {
      "id": "oracle-rownum-paging",
      "level": "中",
      "title": "Oracle ROWNUM 手写分页",
      "detail": "迁移 MyBatis 或换库时需改写为 Dialect，并核对排序稳定性与边界页。",
      "scope": {"code_patterns": ["rownum\\s*<="], "file_exts": [".java", ".sql", ".xml"]},
      "min_hits": 1,
      "evidence_limit": 15
    }
  ]
}
```

内置 4 条通用规则（可用同 id 覆盖）：`jdk-internal-api`、`hardcoded-crypto-provider`、
`weak-crypto-algorithm`、`javax-to-jakarta`；外加一条派生规则
`component-status`（仍在用的 EOL/unknown 组件）。

---

## 7. 执行清单

```powershell
# 1) 事实层跑一遍，拿到改造前基线（只读，不动被分析项目）
.\jlp.ps1 -ProjectPath D:\IdeaProjects\supermarketmanager
#    产物：out\supermarketmanager\02-dependencies.md（组件改造台账 + 平台依赖）

# 2) 补齐闭源组件与分派机制（本方案唯一的必填人工项）
#    - config\legacy\components.json：登记闭源包名前缀 / jar 名 / 基类签名 / status
#    - config\legacy\dispatch.json：登记闭源框架的 branch_pattern 与 front_controller_pattern

# 3) 纠正模块边界（可选，切分错位时才填）
#    config\legacy\modules.json

# 4) 补项目专属风险规则（可选）
#    config\legacy\risk_rules.json

# 5) 回归验证：改造后重跑，diff 两份 facts.json
python tools/jlp/jlp.py --src <项目> --out out\<项目>_after
#    关注：components 只减不增、platform_deps 版本线索上升、风险条目不增加

# 6) 流水线（夜间无人值守，P0 基线自带组件台账）
python orchestrator.py --project <项目> --profile ollama_qwen38
```

---

## 8. 待确认事项

| 编号 | 事项 | 落点 |
|---|---|---|
| #P1 | 目标 JDK 与目标容器版本（决定 Servlet/Jakarta 轨道） | 需业务与运维共同定档，定档后回填 `components.json` 的 `servlet-api.version_hint` |
| #P2 | 闭源组件清单：包名前缀、jar 名、配置文件、基类/接口签名、厂商支持状态 | `config/legacy/components.json`（本方案无法推断，必须人工填） |
| #P3 | 闭源框架的真实分派方式（参数名？XML？注解？） | `config/legacy/dispatch.json` |
| #P4 | Oracle 版本与是否保留（决定方言改造量） | 台账 + `risk_rules.json` 的分页规则 |
| #P5 | 每阶段的回归基线由谁维护、存哪里 | 建议随 `runtime/<slug>/` 归档 |
