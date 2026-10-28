# supermarketmanager 分析摘要
> 生成时间 2026-10-28 14:31:27 · jlp 1.0

## 一句话
supermarketmanager：Servlet + Biz/Service + DAO 的 Java Web 应用，33 类 / 19 页 / 6,174 行代码，4 个业务模块。

## 模块一览
| 模块 | UI 前缀 | 页面 | 能力 | 主要表 |
|---|---|---|---|---|
| Goods | `product*` | 4 | 新增、删除、修改、查询、分页、模糊查询 | goods、goods_view、suppliers |
| Orders | `bill*` | 4 | 新增、删除、修改、查询、分页、模糊查询 | goods、orders、orders_view |
| Suppliers | `provider*` | 4 | 新增、删除、修改、查询、分页、模糊查询 | suppliers、suppliers_view |
| Users | `user*` | 4 | 新增、删除、修改、查询、分页、模糊查询 | users、users_view |

## 技术栈
| 维度 | 现状 |
|---|---|
| 视图技术 | JSP（含脚本片段） |
| 标签库 | JSTL：c |
| 页面编码 | UTF-8 |
| MVC 框架 | 无框架，裸 Servlet + 前端控制器 |
| 请求分发模式 | 前端控制器（Front Controller） |
| 前端脚本 | jQuery（`WebRoot/js/jquery.js`） |
| 异步交互 | 4 个异步入口 |
| 持久层 | 手写 JDBC（PreparedStatement） |
| 数据源获取 | JNDI 容器数据源（DataSource） |
| 数据库类型 | Oracle |
| Servlet 规范 | web.xml 声明 3.0 / Schema 2.5 |

## Top 风险
| 级别 | 问题 |
|---|---|
| 高 | 会话中明文保存口令类字段 |
| 中 | 静态资源悬空引用 |
| 中 | 无显式事务边界 |
| 低 | 欢迎页配置失效 |
| 低 | 遗留 System.out 调试输出 |
| 低 | 遗留 TODO/FIXME 标记 |

## 建议优先做
- **P0** — 处理会话中的口令类字段
- **P1** — 补齐或移除悬空的 css/js/图片引用
- **P1** — 固化运行环境说明（JNDI + 驱动）
- **P1** — 为跨表写操作补事务边界

## 产物
- `00-preflight.md`
- `01-structure.md`
- `02-dependencies.md`
- `03-modules.md`
- `10-requirement-analysis.md`
- `99-summary.md`
- `facts.json`
