# 01 · 项目结构分析
> 全部数字由脚本统计得出，非估算。

## 一句话画像
**supermarketmanager** 是一个 Servlet + Biz/Service + DAO 的 Web 应用：33 个 Java 类、19 个 JSP 页面、共 6,174 行 Java/JSP 代码（全量文本 16,966 行 / 108 个文件）。

## 规模总览
| 维度 | 数量 |
|---|---|
| Java 源文件 | 33 |
| JSP 页面 | 19 |
| SQL 脚本 | 1 |
| XML / properties 配置 | 2 |
| JAR 依赖包 | 6 |
| Java + JSP 代码行数 | 6,174 |
| 文本总行数 | 16,966 |
| 仓库文件总数 | 108 |

## 目录骨架（≤4 层）
每个节点显示的是**该目录及其子目录**的累计文件数与行数；更深的目录已并入第 4 层祖先。

```text
- /.settings （该目录累计 1 个文件 · 8 行）
- /WebRoot （该目录累计 30 个文件 · 13,031 行）
  - /META-INF （该目录累计 1 个文件 · 4 行）
  - /WEB-INF （该目录累计 1 个文件 · 83 行）
  - /js （该目录累计 7 个文件 · 10,453 行）
  - /security （该目录累计 19 个文件 · 2,401 行）
- /src （该目录累计 33 个文件 · 3,762 行）
  - /com （该目录累计 33 个文件 · 3,762 行）
    - /hy （该目录累计 33 个文件 · 3,762 行）
      - /cxp （该目录累计 33 个文件 · 3,762 行）
```

## 文件类型画像
| 扩展名 | 类别 | 文件数 | 行数 | 体积 |
|---|---|---|---|---|
| .java | Java 源码 | 33 | 3,762 | 98 KB |
| .jsp | JSP 页面 | 19 | 2,412 | 81 KB |
| .png | 图片资源 | 17 | - | 98 KB |
| .js | JavaScript | 7 | 10,453 | 294 KB |
| .jar | JAR 依赖包 | 6 | - | 1279 KB |
| .jpg | 图片资源 | 6 | - | 451 KB |
|  | (无扩展名) | 5 | - | 4 KB |
| .xml | XML 配置 | 2 | 91 | 4 KB |
| .html | HTML 页面 | 2 | 79 | 3 KB |
| .prefs | Eclipse 首选项 | 2 | - | 1 KB |
| .md | Markdown | 1 | 16 | 1 KB |
| .sql | SQL 脚本 | 1 | 149 | 5 KB |
| .mf | 清单文件 | 1 | 4 | 0 KB |
| .dmp | 数据库转储 | 1 | - | 8 KB |
| .~sql | SQL 备份副本 | 1 | - | 5 KB |
| .component | Eclipse 组件配置 | 1 | - | 0 KB |
| .container | Eclipse 容器配置 | 1 | - | 0 KB |
| .name | Eclipse 名称配置 | 1 | - | 0 KB |
| .db | Windows 缩略图缓存 | 1 | - | 31 KB |

## Java 包分布
| 包 | 文件数 | 行数 | 方法数 |
|---|---|---|---|
| com.hy.cxp.supermarket.dao.impl | 4 | 1095 | 36 |
| com.hy.cxp.supermarket.servlet | 4 | 1086 | 61 |
| com.hy.cxp.supermarket.entity | 8 | 720 | 137 |
| com.hy.cxp.supermarket.biz.impl | 4 | 244 | 36 |
| com.hy.cxp.supermarket.util | 2 | 229 | 22 |
| com.hy.cxp.supermarket.controller | 1 | 133 | 7 |
| com.hy.cxp.supermarket.filter | 2 | 91 | 6 |
| com.hy.cxp.supermarket.biz | 4 | 82 | 36 |
| com.hy.cxp.supermarket.dao | 4 | 82 | 36 |

## 体积最大的源文件（前 15）
| 文件 | 行数 | 类别 |
|---|---|---|
| `WebRoot/js/jquery.js` | 9790 | JavaScript |
| `WebRoot/js/datetime.js` | 360 | JavaScript |
| `src/com/hy/cxp/supermarket/dao/impl/OrdersDaoImpl.java` | 357 | Java 源码 |
| `src/com/hy/cxp/supermarket/servlet/OrdersServlet.java` | 357 | Java 源码 |
| `src/com/hy/cxp/supermarket/dao/impl/UsersDaoImpl.java` | 273 | Java 源码 |
| `src/com/hy/cxp/supermarket/servlet/SuppliersServlet.java` | 259 | Java 源码 |
| `src/com/hy/cxp/supermarket/dao/impl/SuppliersDaoImpl.java` | 256 | Java 源码 |
| `src/com/hy/cxp/supermarket/servlet/UsersServlet.java` | 239 | Java 源码 |
| `src/com/hy/cxp/supermarket/servlet/GoodsServlet.java` | 231 | Java 源码 |
| `src/com/hy/cxp/supermarket/dao/impl/GoodsDaoImpl.java` | 209 | Java 源码 |
| `WebRoot/security/billList.jsp` | 198 | JSP 页面 |
| `WebRoot/security/providerList.jsp` | 182 | JSP 页面 |
| `WebRoot/security/userList.jsp` | 177 | JSP 页面 |
| `supermarket.sql` | 149 | SQL 脚本 |
| `WebRoot/security/billUpdate.jsp` | 147 | JSP 页面 |

## 技术栈指纹
| 维度 | 判定 | 证据 |
|---|---|---|
| 视图技术 | JSP（含脚本片段） | 19 个 .jsp，累计 46 个 `<% %>` 片段；19 个文件使用 EL 表达式 |
| 标签库 | JSTL：c | 来自 `<%@ taglib %>` 指令 |
| 页面编码 | UTF-8 | JSP `pageEncoding` 指令 |
| MVC 框架 | 无框架，裸 Servlet + 前端控制器 | web.xml 声明 5 个 Servlet，未见 Struts/Spring 配置 |
| 请求分发模式 | 前端控制器（Front Controller） | `ControllerServlet` 用 `requestURI` 尾段 + `action` 字符串分派 |
| 前端脚本 | jQuery（`WebRoot/js/jquery.js`） | 静态资源目录扫描 |
| 异步交互 | 4 个异步入口 | `Goods.do?action=search&name=`、`Orders.do?action=search&gname=`、`Suppliers.do?action=search&name=`、`Users.do?action=search&name=` |
| 持久层 | 手写 JDBC（PreparedStatement） | 4 个 DAO 直接使用 `java.sql.*`，未见 ORM import |
| 数据源获取 | JNDI 容器数据源（DataSource） | `java:comp/env/jdbc/orcl` |
| 数据库类型 | Oracle | 证据：SQL 方言 |
| Servlet 规范 | web.xml 声明 3.0 / Schema 2.5 | `WebRoot/WEB-INF/web.xml` |

## 构建与部署形态
| 维度 | 结论 |
|---|---|
| 构建方式 | Eclipse classpath、Eclipse/MyEclipse、MyEclipse Web 模块 |
| 依赖管理 | 手工拷贝 JAR 到 WEB-INF/lib |
| 打包形态 | WAR 目录结构（WebRoot） |
| 分层形态 | 业务层、实体/POJO、工具类、持久层、控制层、过滤器/拦截器 |
