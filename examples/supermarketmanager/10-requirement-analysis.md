# 需求分析报告
## 文档信息
| 项 | 值 |
|---|---|
| 被分析项目 | supermarketmanager |
| 项目根路径 | `D:\IdeaProjects\supermarketmanager` |
| 生成时间 | 2026-10-28 14:31:27 |
| 生成工具 | jlp 1.0（静态分析，未编译/未执行/未联网） |
| 事实来源 | 01-structure.md / 02-dependencies.md / 03-modules.md |
| LLM 参与 | 未启用（纯静态事实） |

## 阅读说明
本报告由工具静态扫描源码得出，用于**快速建立对一个陌生老项目的认知**：

1. 所有数量、清单、依赖边都是脚本数出来的，可直接复核；
2. 涉及「意图」的判断（如某个类是废弃代码）均标注为提示，请人工确认；
3. 分析过程对被分析目录**只读**，不会改动或生成任何源文件。

## 1. 项目概览
**supermarketmanager** 是一个基于 Servlet + Biz/Service + DAO 的 Java Web 应用，共 33 个 Java 类、19 个 JSP 页面，Java/JSP 代码约 6,174 行。

请求入口统一由前端控制器（ControllerServlet）接收，再按 `action` 参数分发到各业务 Servlet，由 Servlet 完成参数收集、调用业务层、转发到 JSP 展示。

### 技术栈清单
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

## 2. 项目结构
| 维度 | 结论 |
|---|---|
| 构建方式 | Eclipse classpath、Eclipse/MyEclipse、MyEclipse Web 模块 |
| 依赖管理 | 手工拷贝 JAR 到 WEB-INF/lib |
| 打包形态 | WAR 目录结构（WebRoot） |
| 分层形态 | 业务层、实体/POJO、工具类、持久层、控制层、过滤器/拦截器 |


### 代码分布
| Java 包 | 文件数 | 行数 |
|---|---|---|
| com.hy.cxp.supermarket.dao.impl | 4 | 1095 |
| com.hy.cxp.supermarket.servlet | 4 | 1086 |
| com.hy.cxp.supermarket.entity | 8 | 720 |
| com.hy.cxp.supermarket.biz.impl | 4 | 244 |
| com.hy.cxp.supermarket.util | 2 | 229 |
| com.hy.cxp.supermarket.controller | 1 | 133 |
| com.hy.cxp.supermarket.filter | 2 | 91 |
| com.hy.cxp.supermarket.biz | 4 | 82 |
| com.hy.cxp.supermarket.dao | 4 | 82 |


### 页面分布
| 目录 | 页面数 |
|---|---|
| `WebRoot/security` | 18 |
| `WebRoot` | 1 |

## 3. 请求处理流程
```text
过滤器生效范围：/*、/security/*

浏览器
   │  *.do / *.html / *.jsp
   ▼
[过滤器] CharacterEncodingFilter、SercurityFilter
   │
   ▼
[前端控制器] ControllerServlet   ← 负责登录/登出/改密 + 按 URI 分派
   │ forward
   ▼
[业务 Servlet] GoodsServlet、OrdersServlet、SuppliersServlet、UsersServlet
   │ 调用
   ▼
[业务层 Biz/Impl]
   │ 调用
   ▼
[持久层 Dao/Impl]  ← extends BaseDao（JNDI 数据源 + PreparedStatement）
   │ SQL
   ▼
[数据库] Oracle

返回结果经 request.setAttribute 注入请求域，Servlet forward 回 JSP 渲染。
```

## 4. 功能模块
按真实调用链识别出 4 个业务模块：

### 4.1 Goods（UI 术语 `product*`）
**职责**：Goods 域的 新增、删除、修改、查询、分页、模糊查询。页面集合 `productAdd.jsp`、`productList.jsp`、`productUpdate.jsp`、`productView.jsp`。

| 层 | 构件 |
|---|---|
| 控制层 | GoodsServlet |
| 业务层 | GoodsBiz、GoodsBizImpl |
| 持久层 | GoodsDao、GoodsDaoImpl |
| 实体/视图 | Goods、GoodsView |
| 数据表 | `goods`、`goods_view`、`suppliers` |
| 动作 | `(无 action 参数/默认)`、`add`、`addView`、`del`、`details`、`save`、`search`、`update` |
| 能力 | 新增、删除、修改、查询、分页、模糊查询 |


### 4.2 Orders（UI 术语 `bill*`）
**职责**：Orders 域的 新增、删除、修改、查询、分页、模糊查询。页面集合 `billAdd.jsp`、`billList.jsp`、`billUpdate.jsp`、`billView.jsp`。

| 层 | 构件 |
|---|---|
| 控制层 | OrdersServlet |
| 业务层 | OrdersBiz、OrdersBizImpl |
| 持久层 | OrdersDao、OrdersDaoImpl |
| 实体/视图 | Orders、OrdersDetail、OrdersView、Suppliers |
| 数据表 | `goods`、`orders`、`orders_view` |
| 动作 | `(无 action 参数/默认)`、`add`、`addView`、`del`、`details`、`goodajax`、`save`、`search`、`supplierajax`、`update` |
| 能力 | 新增、删除、修改、查询、分页、模糊查询 |


### 4.3 Suppliers（UI 术语 `provider*`）
**职责**：Suppliers 域的 新增、删除、修改、查询、分页、模糊查询。页面集合 `providerAdd.jsp`、`providerList.jsp`、`providerUpdate.jsp`、`providerView.jsp`。

| 层 | 构件 |
|---|---|
| 控制层 | SuppliersServlet |
| 业务层 | SuppliersBiz、SuppliersBizImpl |
| 持久层 | SuppliersDao、SuppliersDaoImpl |
| 实体/视图 | Suppliers |
| 数据表 | `suppliers`、`suppliers_view` |
| 动作 | `(无 action 参数/默认)`、`add`、`del`、`details`、`save`、`search`、`update` |
| 能力 | 新增、删除、修改、查询、分页、模糊查询 |


### 4.4 Users（UI 术语 `user*`）
**职责**：Users 域的 新增、删除、修改、查询、分页、模糊查询。页面集合 `userAdd.jsp`、`userList.jsp`、`userUpdate.jsp`、`userView.jsp`。

| 层 | 构件 |
|---|---|
| 控制层 | UsersServlet |
| 业务层 | UsersBiz、UsersBizImpl |
| 持久层 | UsersDao、UsersDaoImpl |
| 实体/视图 | Users、UsersView |
| 数据表 | `users`、`users_view` |
| 动作 | `(无 action 参数/默认)`、`add`、`del`、`details`、`save`、`search`、`update` |
| 能力 | 新增、删除、修改、查询、分页、模糊查询 |


### 4.5 公共 / 其他页面
不归属任何业务模块：`login.jsp`、`password.jsp`、`welcome.jsp`

## 5. 依赖与环境要求
### 5.1 war 内已打包的 JAR
| JAR | 体积 |
|---|---|
| `WebRoot/WEB-INF/lib/commons-beanutils-1.7.0.jar` | 184 KB |
| `WebRoot/WEB-INF/lib/commons-collections-3.2.jar` | 558 KB |
| `WebRoot/WEB-INF/lib/commons-lang-2.4.jar` | 256 KB |
| `WebRoot/WEB-INF/lib/commons-logging-1.1.jar` | 52 KB |
| `WebRoot/WEB-INF/lib/ezmorph-1.0.4.jar` | 84 KB |
| `WebRoot/WEB-INF/lib/json-lib-2.2.3-jdk13.jar` | 145 KB |

### 5.2 第三方依赖核对
| 依赖库 | 命名空间 | 引用次数 | 已打包 | 缺少配套 |
|---|---|---|---|---|
| json-lib | `net.sf.json` | 1 | 是 | - |

### 5.3 运行容器要求
- 需在容器中配置 JNDI 数据源：`java:comp/env/jdbc/orcl`
- Oracle 驱动（`ojdbc`）未打进 war，需由容器 lib 目录提供
- Servlet 容器需支持 Servlet 2.5 规范

## 6. 数据对象
| 类别 | 对象 |
|---|---|
| SQL 脚本中的表 | goods、orders、suppliers、users |
| SQL 脚本中的视图 | goods_view、orders_detail、orders_view、suppliers_view、users_view |
| SQL 脚本中的序列 | seq_gid、seq_oid、seq_sid、seq_uid |
| 源码 SQL 引用的表 | goods、goods_view、orders、orders_view、suppliers、suppliers_view、users、users_view |

## 7. 风险与技术债
### [高] 会话中明文保存口令类字段
密码被写入 HttpSession，任何能访问会话的代码/调试页都可读取。

证据：

- `pwd`

### [中] 静态资源悬空引用
页面引用了仓库中不存在的文件，部署后对应样式/脚本/图片会 404。

证据：

- `WebRoot/login.html` -> `css/style.css`
- `WebRoot/login.jsp` -> `css/style.css`
- `WebRoot/security/billAdd.jsp` -> `css/public.css`
- `WebRoot/security/billAdd.jsp` -> `css/style.css`
- `WebRoot/security/billList.jsp` -> `css/public.css`
- `WebRoot/security/billList.jsp` -> `css/style.css`
- `WebRoot/security/billUpdate.jsp` -> `css/public.css`
- `WebRoot/security/billUpdate.jsp` -> `css/style.css`
- `WebRoot/security/billView.jsp` -> `css/public.css`
- `WebRoot/security/billView.jsp` -> `css/style.css`
- `WebRoot/security/password.jsp` -> `css/public.css`
- `WebRoot/security/password.jsp` -> `css/style.css`
- `WebRoot/security/productAdd.jsp` -> `css/public.css`
- `WebRoot/security/productAdd.jsp` -> `css/style.css`
- `WebRoot/security/productList.jsp` -> `css/public.css`

### [中] 无显式事务边界
持久层每条 SQL 独立取连接且未调用 commit/rollback，跨表写操作无法保证一致性。

证据：

- `GoodsDaoImpl`
- `OrdersDaoImpl`
- `SuppliersDaoImpl`
- `UsersDaoImpl`

### [低] 欢迎页配置失效
web.xml 声明的 welcome-file 在仓库中不存在，容器会退到下一个或报 404。

证据：

- `index.jsp`

### [低] 遗留 System.out 调试输出
共 65 处 console 打印，生产环境应改为日志框架便于分级与落盘。

证据：

- `OrdersServlet` × 20
- `SuppliersServlet` × 14
- `GoodsServlet` × 13
- `UsersServlet` × 12
- `CharacterEncodingFilter` × 3

### [低] 遗留 TODO/FIXME 标记
共 10 处未完成标记。

证据：

- `Goods`
- `GoodsBizImpl`
- `GoodsDaoImpl`
- `GoodsView`
- `Orders`
- `OrdersDetail`
- `OrdersView`
- `Suppliers`
- `Users`
- `UsersDaoImpl`

### [提示] 未归属到业务模块的页面
这些页面没有指向任何 Servlet 的表单/异步请求，通常是公共页或已被废弃。

证据：

- `WebRoot/login.jsp`
- `WebRoot/security/password.jsp`
- `WebRoot/security/welcome.jsp`

### [提示] 未参与任何业务切片的类
通常是工具类/过滤器/基础设施，也可能是已废弃代码，需人工确认。

证据：

- `BaseDao`
- `CharacterEncodingFilter`
- `ControllerServlet`
- `Page`
- `SercurityFilter`

## 8. 维护与现代化建议
| 优先级 | 建议 | 理由 |
|---|---|---|
| P0 | 处理会话中的口令类字段 | 会话明文保存密码，属安全问题，应先于任何重构处理 |
| P1 | 补齐或移除悬空的 css/js/图片引用 | 页面当前依赖不存在的文件，属于可直接修复的显性缺陷 |
| P1 | 固化运行环境说明（JNDI + 驱动） | 数据源与 JDBC 驱动都在容器侧，缺少文档会导致「换台机器就跑不起来」 |
| P1 | 为跨表写操作补事务边界 | 逐语句取连接且无 commit/rollback，异常时会产生脏数据 |
| P2 | 修正 web.xml 的 welcome-file | 配置指向不存在资源，会导致首屏 404 或回退行为不确定 |
| P2 | 用日志框架替换 System.out | 便于分级、落盘与线上排障 |
| P3 | 清理 TODO/FIXME 并登记为条目 | 避免未完成意图被埋没在代码里 |
| P3 | 把 `WEB-INF/classes` 的 `.class` 与体积较大的二进制加入 .gitignore | 编译产物入库会让 diff/评审噪声变大 |
| P3 | 先固化一份「能跑起来的环境说明」再谈重构 | 老项目最大的风险是无人知道如何启动；本报告第 5 节已给出线索 |

## 附录 A · 产物清单
| 文件 | 内容 |
|---|---|
| `00-preflight.md` | 环境预检 |
| `01-structure.md` | 项目结构 |
| `02-dependencies.md` | 依赖关系 |
| `03-modules.md` | 功能模块 |
| `10-requirement-analysis.md` | 需求分析报告（本文） |
| `99-summary.md` | 一页摘要 |
| `facts.json` | 机读事实库 |

## 附录 B · 复现命令
```powershell
python "D:\IdeaProjects\llm-legacy-code-pipeline\tools\jlp\jlp.py" --src "D:\IdeaProjects\supermarketmanager"
```

## 附录 C · Java 类全清单
| 类 | 层 | 包 | 行数 | 方法数 |
|---|---|---|---|---|
| GoodsBiz | 业务层 | com.hy.cxp.supermarket.biz | 20 | 8 |
| GoodsBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 58 | 8 |
| OrdersBiz | 业务层 | com.hy.cxp.supermarket.biz | 24 | 11 |
| OrdersBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 72 | 11 |
| SuppliersBiz | 业务层 | com.hy.cxp.supermarket.biz | 18 | 8 |
| SuppliersBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 54 | 8 |
| UsersBiz | 业务层 | com.hy.cxp.supermarket.biz | 20 | 9 |
| UsersBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 60 | 9 |
| Goods | 实体/POJO | com.hy.cxp.supermarket.entity | 103 | 17 |
| GoodsView | 实体/POJO | com.hy.cxp.supermarket.entity | 70 | 14 |
| Orders | 实体/POJO | com.hy.cxp.supermarket.entity | 87 | 14 |
| OrdersDetail | 实体/POJO | com.hy.cxp.supermarket.entity | 97 | 20 |
| OrdersView | 实体/POJO | com.hy.cxp.supermarket.entity | 81 | 16 |
| Suppliers | 实体/POJO | com.hy.cxp.supermarket.entity | 107 | 22 |
| Users | 实体/POJO | com.hy.cxp.supermarket.entity | 107 | 22 |
| UsersView | 实体/POJO | com.hy.cxp.supermarket.entity | 68 | 12 |
| BaseDao | 工具类 | com.hy.cxp.supermarket.util | 117 | 8 |
| Page | 工具类 | com.hy.cxp.supermarket.util | 112 | 14 |
| GoodsDao | 持久层 | com.hy.cxp.supermarket.dao | 20 | 8 |
| GoodsDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 209 | 8 |
| OrdersDao | 持久层 | com.hy.cxp.supermarket.dao | 24 | 11 |
| OrdersDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 357 | 11 |
| SuppliersDao | 持久层 | com.hy.cxp.supermarket.dao | 18 | 8 |
| SuppliersDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 256 | 8 |
| UsersDao | 持久层 | com.hy.cxp.supermarket.dao | 20 | 9 |
| UsersDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 273 | 9 |
| ControllerServlet | 控制层 | com.hy.cxp.supermarket.controller | 133 | 7 |
| GoodsServlet | 控制层 | com.hy.cxp.supermarket.servlet | 231 | 14 |
| OrdersServlet | 控制层 | com.hy.cxp.supermarket.servlet | 357 | 16 |
| SuppliersServlet | 控制层 | com.hy.cxp.supermarket.servlet | 259 | 16 |
| UsersServlet | 控制层 | com.hy.cxp.supermarket.servlet | 239 | 15 |
| CharacterEncodingFilter | 过滤器/拦截器 | com.hy.cxp.supermarket.filter | 44 | 3 |
| SercurityFilter | 过滤器/拦截器 | com.hy.cxp.supermarket.filter | 47 | 3 |
