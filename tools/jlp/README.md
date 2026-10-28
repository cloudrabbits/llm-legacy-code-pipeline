# jlp —— JSP 遗留项目分析器

对 JSP / 裸 Servlet 时代的 Java Web 老项目做**只读静态分析**，梳理
**项目结构 / 依赖关系 / 功能模块**，输出便于人类阅读的需求分析文档。

- 零第三方依赖（只用 Python 标准库），Python ≥ 3.8
- 只读：不编译、不执行、不联网、不写入被分析目录
- 事实由脚本产出，LLM 最多改写叙述（默认关闭）

## 快速开始

```powershell
# Windows
.\jlp.ps1 -SelfTest                                  # 离线自检
.\jlp.ps1 -ProjectPath D:\IdeaProjects\supermarketmanager
```

```bash
# 跨平台
python tools/jlp/jlp.py --src /path/to/project --out ./out/project
python tools/jlp/jlp.py --self-test
python tools/jlp/jlp.py --src X --stages structure,deps
python tools/jlp/jlp.py --src X --facts-only
python tools/jlp/jlp.py --src X --llm-url http://127.0.0.1:11434/api/generate --llm-model qwen2.5:7b
```

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--src` | 被分析项目根目录（只读） |
| `--out` | 产物目录，默认 `<仓库>/out/<项目目录名>` |
| `--stages` | 逗号分隔：`preflight,structure,deps,modules,report` |
| `--exclude-dir` | 额外排除的目录名，可重复 |
| `--max-file-bytes` | 超过该大小的文本跳过内容解析（默认 4 MB） |
| `--llm-url` / `--llm-model` | 开启可选 LLM 叙述增强，需同时提供 |
| `--facts-only` | 只落 `facts.json` |
| `--quiet` | 减少过程输出 |
| `--self-test` | 合成语料离线自检（不联网、不需要 LLM） |

## 模块划分

```
lib_scan.py   事实抽取层  遍历、编码降级读取、Java/JSP/web.xml/SQL 解析、依赖边
lib_model.py  派生模型层  路由还原、模块切分、能力矩阵、风险规则
lib_tech.py   技术栈指纹  框架/前端控制器/JDBC/JNDI/容器/数据库判定
lib_md.py     渲染层      Markdown 表格/代码块/原子写
stage_*.py    五个阶段    各产出一份文档
jlp.py        CLI 入口    参数解析 + 阶段编排 + Windows 控制台 UTF-8
selftest.py   离线自检    合成语料 → 28 项断言
```

## 五个阶段

### S0 预检 `stage_preflight.py` → `00-preflight.md`

确认"能不能扫"。关键一步是**按文件降级解码**：

```
utf-8-sig → utf-8 → gb18030 → big5 → latin-1
```

老项目的 `.sql`、部分 `.jsp` 常是 GBK/GB2312，Windows 上不做这步，后面全是乱码。
同时检查：Python 版本、目标可读可写、目录/文件/行数概览、能否识别 `WEB-INF` 与 `src`。

### S1 结构 `stage_structure.py` → `01-structure.md`

- 目录骨架：递归累计文件数与行数（超过 4 层向上并入）
- 文件类型画像：按扩展名聚合数量/行数/最大单文件 + 中文说明
- Java 包分布、JSP 页面分布
- 行数 Top-N 源文件
- **技术栈指纹**（`lib_tech.py`）：是否用 SSH/SSM 框架、是否有前端控制器、JSP 是否含 scriptlet、
  是否用 JSTL、持久层是 ORM 还是裸 JDBC、数据源是 JNDI 还是直连、Servlet 规范版本、数据库类型
- 构建 / 部署形态：无构建？war 已展开？是否有 `pom.xml` / `build.xml`

### S2 依赖 `stage_deps.py` → `02-dependencies.md`

- **分层画像**：按 `包后缀 + 类名后缀` 判定 `控制层/业务层/持久层/实体/工具类/过滤器`
- **依赖边**：`import` + `extends` + `implements` + 同包引用 → `A → B`
- **分层调用矩阵**与**反向依赖检查**（控制层直接依赖持久层、业务层反向依赖控制层……）
- **URL 路由还原**：`web.xml` 的 `servlet-mapping` × Servlet 内 `if (action.equals("x"))` 分支，
  连 `*.do → 前端控制器 → /servlet/XxxServlet` 的两级跳转都能解析到最终处理类
- **Servlet 分派表**：每个 action → 读取的参数 / 调用的业务方法 / 跳转目标
- **页面 ↔ 后端调用矩阵**：表单提交、异步请求
- **第三方依赖核对**：源码引用的命名空间 vs war 内实际 JAR，`缺失/缺配套` 会被显式标出

### S3 模块 `stage_modules.py` → `03-modules.md`

不做文件名猜测，用**真实调用边**切分：

1. 以类名后缀（`Biz/Service/Dao/Servlet/Action/Manager`）取领域词作为模块种子
2. 按领域词装配 `Servlet / Biz / BizImpl / Dao / DaoImpl / XxxView` 三层
3. 页面归属用**三级信号**（强→弱）：
   - ① 页面主动发起的表单提交 / 异步请求
   - ② Servlet `forward` / `redirect` 的目标页（解决"查看详情"这类无表单的展示页）
   - ③ 页面内普通链接（先剔除在半数以上页面都出现的**全站导航栏**）
4. 表单所在的 url-process/model/save/add/del 分支 → 抽取**动作清单**
5.  Dao 实现体+接口方法名 → **CRUD 能力矩阵**（查询/新增/修改/删除/分页/模糊查询）
6.  Dao 的 SQL FROM/UPDATE/INSERT/JOIN → 反查**数据表**，再用 Dao import 反查**实体**

产出每模块的纵向切片（页面→Servlet→Biz→Dao→实体→表）+ 页面清单 + 未归属页面说明。

### S4 汇总 `stage_report.py` → `10-requirement-analysis.md` + `99-summary.md`

组织前三份事实成需求分析报告：概览 / 结构 / **请求处理流程图** / 模块逐个 /
依赖与运行要求 / 数据对象 / **风险与技术债（每条带证据）** / **分级建议** +
三个附录（产物清单、复现命令、Java 类全清单）。

同时产出 `99-summary.md` 一页纸速览。

### S5 可选 LLM `stage_llm.py` → `05-llm-narrative.md`

**默认关闭**。仅 "--llm-url 与 --llm-model 同时提供" 时启用，`think=false` +
只喂 `facts.json` 摘要，明确禁止改动任何数字。服务不可达时自动降级，不影响前面阶段产物。

> 这条约束来自旧版本的实测结论：**不给脚本事实，模型就会编出像模像样的统计数字**。
> 所以答案是"脚本负责算，模型最多改写措辞"。

## 自检

```powershell
python tools/jlp/jlp.py --self-test
```

合成一个 8 类 / 3 页的迷你工程（含 GBK 编码的 `.sql` 与 `.jsp`、前端控制器、
界面术语与后端命名不一致的情形），断言：

- 文件数、JSP 数、编码判定（GBK 文件必须被识别）
- `CREATE TABLE` 对象解析
- 前端控制器识别、`web.xml` 路由条数
- `User.do?action=add` 经前端控制器解析到正确的业务 Servlet
- 模块页数/页面前缀/能力矩阵/实体反查/数据表反查
- 导航栏之外的页面不归属业务模块
- 悬空资源、`System.out`、未归属页面等风险是否检出
- 端到端命令行返回码与全部产物存在性

当前：`PASS=28  FAIL=0`（Windows PowerShell 实测）。

## 已知限制

- 只做静态解析：反射调用、运行时拼 SQL、动态 include 无法还原，会以"提示"标注需人工确认。
- 模块切分依赖调用边；某页面既不提交表单、也不被 Servlet 转发时，会落入"未归属页面"
  而不是被臆造到某个模块。
- 混合框架（SSH/SSM）或无 `web.xml` 的现代项目，技术栈指纹仍需人工复核——工具给的是**证据**，不是结论。
