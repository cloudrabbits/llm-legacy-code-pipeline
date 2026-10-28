# 案例：`supermarketmanager`

这是工具在真实老项目上的一次完整示范产物，**由以下命令原样生成，未经手工编辑**：

```powershell
cd D:\IdeaProjects\llm-legacy-code-pipeline
.\jlp.ps1 -ProjectPath D:\IdeaProjects\supermarketmanager
```

- 被分析项目：`D:\IdeaProjects\supermarketmanager`（不随本仓库分发）
- 运行环境：Windows (win32) / PowerShell / Python 3.13.2
- 退出码：`0`

## 建议阅读顺序

| 顺序 | 文件 | 你会得到什么 |
|---|---|---|
| 1 | `99-summary.md` | 一页纸：规模、模块、Top 风险、建议 |
| 2 | `10-requirement-analysis.md` | 完整需求分析报告（含请求流程图、风险证据、建议） |
| 3 | `03-modules.md` | 4 个功能模块的纵向切片（页面→Servlet→Biz→Dao→实体→表） |
| 4 | `02-dependencies.md` | 依赖边、分层调用矩阵、URL 路由、Servlet 分派表、第三方依赖核对 |
| 5 | `01-structure.md` | 目录骨架、文件类型画像、技术栈指纹 |
| 6 | `00-preflight.md` | 环境预检与混编码普查 |
| 7 | `facts.json` | 机读事实库，所有数字的来源，可 diff / 复核 |

## 从这次示范里能看到什么

**规模**：33 个 Java 类 / 19 个 JSP 页面 / 6,174 行 Java+JSP 代码。

**架构**：裸 Servlet + `ControllerServlet` 前端控制器 + Biz/Service + DAO，
手写 JDBC + PreparedStatement，JNDI 数据源 `java:comp/env/jdbc/orcl` → Oracle。

**4 个功能模块**（最右列是老项目典型的"后端命名 vs 前端命名不一致"）：

| 模块 | Servlet | UI 页面群 | 主要数据表 | 能力 |
|---|---|---|---|---|
| Users | `UsersServlet` | `user*` | `users`、`users_view` | 增/删/改/查/分页/模糊查询 |
| Suppliers | `SuppliersServlet` | `provider*` | `suppliers`、`suppliers_view` | 增/删/改/查/分页/模糊查询 |
| Goods | `GoodsServlet` | `product*` | `goods`、`goods_view` | 增/删/改/查/分页/模糊查询 |
| Orders | `OrdersServlet` | `bill*` | `orders`、`orders_view` | 增/删/改/查/分页/模糊查询 |

**请求链路**（工具还原出来的两级跳转）：

```
浏览器 ──*.do──▶ CharactersEncodingFilter ──▶ ControllerServlet（按 URI 尾段分派）
        ──forward /servlet/xxx──▶ 业务 Servlet ──▶ Biz ──▶ Dao ──▶ Oracle
                                        └──forward──▶ JSP 渲染
```

**工具确定性检出的风险**（每条都带证据，见 `10-requirement-analysis.md` 第 7 节）：

- **[高]** `session.setAttribute("pwd", ...)` —— 会话中明文保存口令
- **[中]** 29 处静态资源悬空引用（`css/public.css`、`css/style.css` 在仓库中并不存在）
- **[中]** 持久层无显式事务边界，逐语句取连接且无 commit/rollback
- **[低]** 65 处 `System.out.println`、10 处 TODO/FIXME、`welcome-file` 指向不存在的 `index.jsp`
- **[提示]** Oracle 驱动未打进 war，需由容器 lib 提供；JNDI 资源需在容器中配置
