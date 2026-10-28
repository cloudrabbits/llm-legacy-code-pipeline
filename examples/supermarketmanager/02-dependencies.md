# 02 · 依赖关系分析
> 依赖边由 import / extends / implements / 同包引用解析得出；URL 链路由 web.xml 与 Servlet 分支还原。

## 分层画像
| 层 | 类数 | 行数 | 方法数 |
|---|---|---|---|
| 控制层 | 5 | 1219 | 68 |
| 持久层 | 8 | 1177 | 72 |
| 实体/POJO | 8 | 720 | 137 |
| 业务层 | 8 | 326 | 72 |
| 工具类 | 2 | 229 | 22 |
| 过滤器/拦截器 | 2 | 91 | 6 |

## Java 类清单
按行数降序。`继承/实现` 一列能直接看出接口 - 实现配对与基础类复用。

| 类 | 层 | 包 | 行数 | 方法数 | 继承 / 实现 |
|---|---|---|---|---|---|
| OrdersDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 357 | 11 | BaseDao / OrdersDao |
| OrdersServlet | 控制层 | com.hy.cxp.supermarket.servlet | 357 | 16 | HttpServlet |
| UsersDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 273 | 9 | BaseDao / UsersDao |
| SuppliersServlet | 控制层 | com.hy.cxp.supermarket.servlet | 259 | 16 | HttpServlet |
| SuppliersDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 256 | 8 | BaseDao / SuppliersDao |
| UsersServlet | 控制层 | com.hy.cxp.supermarket.servlet | 239 | 15 | HttpServlet |
| GoodsServlet | 控制层 | com.hy.cxp.supermarket.servlet | 231 | 14 | HttpServlet |
| GoodsDaoImpl | 持久层 | com.hy.cxp.supermarket.dao.impl | 209 | 8 | BaseDao / GoodsDao |
| ControllerServlet | 控制层 | com.hy.cxp.supermarket.controller | 133 | 7 | HttpServlet |
| BaseDao | 工具类 | com.hy.cxp.supermarket.util | 117 | 8 | - |
| Page | 工具类 | com.hy.cxp.supermarket.util | 112 | 14 | - |
| Suppliers | 实体/POJO | com.hy.cxp.supermarket.entity | 107 | 22 | - |
| Users | 实体/POJO | com.hy.cxp.supermarket.entity | 107 | 22 | - |
| Goods | 实体/POJO | com.hy.cxp.supermarket.entity | 103 | 17 | Serializable |
| OrdersDetail | 实体/POJO | com.hy.cxp.supermarket.entity | 97 | 20 | - |
| Orders | 实体/POJO | com.hy.cxp.supermarket.entity | 87 | 14 | - |
| OrdersView | 实体/POJO | com.hy.cxp.supermarket.entity | 81 | 16 | - |
| OrdersBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 72 | 11 | OrdersBiz |
| GoodsView | 实体/POJO | com.hy.cxp.supermarket.entity | 70 | 14 | - |
| UsersView | 实体/POJO | com.hy.cxp.supermarket.entity | 68 | 12 | - |
| UsersBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 60 | 9 | UsersBiz |
| GoodsBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 58 | 8 | GoodsBiz |
| SuppliersBizImpl | 业务层 | com.hy.cxp.supermarket.biz.impl | 54 | 8 | SuppliersBiz |
| SercurityFilter | 过滤器/拦截器 | com.hy.cxp.supermarket.filter | 47 | 3 | Filter |
| CharacterEncodingFilter | 过滤器/拦截器 | com.hy.cxp.supermarket.filter | 44 | 3 | Filter |
| OrdersBiz | 业务层 | com.hy.cxp.supermarket.biz | 24 | 11 | - |
| OrdersDao | 持久层 | com.hy.cxp.supermarket.dao | 24 | 11 | - |
| GoodsBiz | 业务层 | com.hy.cxp.supermarket.biz | 20 | 8 | - |
| UsersBiz | 业务层 | com.hy.cxp.supermarket.biz | 20 | 9 | - |
| GoodsDao | 持久层 | com.hy.cxp.supermarket.dao | 20 | 8 | - |
| UsersDao | 持久层 | com.hy.cxp.supermarket.dao | 20 | 9 | - |
| SuppliersBiz | 业务层 | com.hy.cxp.supermarket.biz | 18 | 8 | - |
| SuppliersDao | 持久层 | com.hy.cxp.supermarket.dao | 18 | 8 | - |

## 内部依赖关系
### 类级依赖边（A → B）
- `ControllerServlet` → `Users`
- `ControllerServlet` → `UsersBiz`
- `ControllerServlet` → `UsersBizImpl`
- `GoodsBiz` → `Goods`
- `GoodsBiz` → `GoodsView`
- `GoodsBiz` → `Page`
- `GoodsBizImpl` → `Goods`
- `GoodsBizImpl` → `GoodsBiz`
- `GoodsBizImpl` → `GoodsDao`
- `GoodsBizImpl` → `GoodsDaoImpl`
- `GoodsBizImpl` → `GoodsView`
- `GoodsBizImpl` → `Page`
- `GoodsDao` → `Goods`
- `GoodsDao` → `GoodsView`
- `GoodsDao` → `Page`
- `GoodsDaoImpl` → `BaseDao`
- `GoodsDaoImpl` → `Goods`
- `GoodsDaoImpl` → `GoodsDao`
- `GoodsDaoImpl` → `GoodsView`
- `GoodsDaoImpl` → `Page`
- `GoodsServlet` → `Goods`
- `GoodsServlet` → `GoodsBiz`
- `GoodsServlet` → `GoodsBizImpl`
- `GoodsServlet` → `GoodsView`
- `OrdersBiz` → `Orders`
- `OrdersBiz` → `OrdersDetail`
- `OrdersBiz` → `OrdersView`
- `OrdersBiz` → `Page`
- `OrdersBiz` → `Suppliers`
- `OrdersBizImpl` → `Orders`
- `OrdersBizImpl` → `OrdersBiz`
- `OrdersBizImpl` → `OrdersDao`
- `OrdersBizImpl` → `OrdersDaoImpl`
- `OrdersBizImpl` → `OrdersDetail`
- `OrdersBizImpl` → `OrdersView`
- `OrdersBizImpl` → `Page`
- `OrdersBizImpl` → `Suppliers`
- `OrdersDao` → `Orders`
- `OrdersDao` → `OrdersDetail`
- `OrdersDao` → `OrdersView`
- `OrdersDao` → `Page`
- `OrdersDao` → `Suppliers`
- `OrdersDaoImpl` → `BaseDao`
- `OrdersDaoImpl` → `Orders`
- `OrdersDaoImpl` → `OrdersDao`
- `OrdersDaoImpl` → `OrdersDetail`
- `OrdersDaoImpl` → `OrdersView`
- `OrdersDaoImpl` → `Page`
- `OrdersDaoImpl` → `Suppliers`
- `OrdersServlet` → `Goods`
- `OrdersServlet` → `GoodsBiz`
- `OrdersServlet` → `GoodsBizImpl`
- `OrdersServlet` → `GoodsView`
- `OrdersServlet` → `Orders`
- `OrdersServlet` → `OrdersBiz`
- `OrdersServlet` → `OrdersBizImpl`
- `OrdersServlet` → `OrdersDetail`
- `OrdersServlet` → `OrdersView`
- `OrdersServlet` → `Page`
- `OrdersServlet` → `Suppliers`
- `OrdersServlet` → `SuppliersBiz`
- `OrdersServlet` → `SuppliersBizImpl`
- `SuppliersBiz` → `Page`
- `SuppliersBiz` → `Suppliers`
- `SuppliersBizImpl` → `Page`
- `SuppliersBizImpl` → `Suppliers`
- `SuppliersBizImpl` → `SuppliersBiz`
- `SuppliersBizImpl` → `SuppliersDao`
- `SuppliersBizImpl` → `SuppliersDaoImpl`
- `SuppliersDao` → `Page`
- `SuppliersDao` → `Suppliers`
- `SuppliersDaoImpl` → `BaseDao`
- `SuppliersDaoImpl` → `Page`
- `SuppliersDaoImpl` → `Suppliers`
- `SuppliersDaoImpl` → `SuppliersDao`
- `SuppliersServlet` → `Page`
- `SuppliersServlet` → `Suppliers`
- `SuppliersServlet` → `SuppliersBiz`
- `SuppliersServlet` → `SuppliersBizImpl`
- `UsersBiz` → `Page`
- `UsersBiz` → `Users`
- `UsersBiz` → `UsersView`
- `UsersBizImpl` → `Page`
- `UsersBizImpl` → `Users`
- `UsersBizImpl` → `UsersBiz`
- `UsersBizImpl` → `UsersDaoImpl`
- `UsersBizImpl` → `UsersView`
- `UsersDao` → `Page`
- `UsersDao` → `Users`
- `UsersDao` → `UsersView`
- `UsersDaoImpl` → `BaseDao`
- `UsersDaoImpl` → `Page`
- `UsersDaoImpl` → `Users`
- `UsersDaoImpl` → `UsersDao`
- `UsersDaoImpl` → `UsersView`
- `UsersServlet` → `Page`
- `UsersServlet` → `Users`
- `UsersServlet` → `UsersBiz`
- `UsersServlet` → `UsersBizImpl`
- `UsersServlet` → `UsersView`

### 分层调用矩阵
行＝调用方，列＝被依赖方，数字＝该方向的依赖边数量。

| 调用方 \ 被依赖方 | 业务层 | 实体/POJO | 工具类 | 持久层 | 控制层 |
|---|---|---|---|---|---|
| 业务层 | 4 | 18 | 8 | 7 | - |
| 实体/POJO | - | - | - | - | - |
| 工具类 | - | - | - | - | - |
| 持久层 | - | 18 | 12 | 4 | - |
| 控制层 | 14 | 12 | 3 | - | - |

### 分层违规检查
未发现跨层反向依赖，调用方向自上而下，符合经典分层。

## 请求路由（web.xml）
| URL 模式 | Servlet 名 | Servlet 类 | 源文件 |
|---|---|---|---|
| `*.do` | Controller | com.hy.cxp.supermarket.controller.ControllerServlet | `src/com/hy/cxp/supermarket/controller/ControllerServlet.java` |
| `/servlet/UsersServlet` | UsersServlet | com.hy.cxp.supermarket.servlet.UsersServlet | `src/com/hy/cxp/supermarket/servlet/UsersServlet.java` |
| `/servlet/OrdersServlet` | OrdersServlet | com.hy.cxp.supermarket.servlet.OrdersServlet | `src/com/hy/cxp/supermarket/servlet/OrdersServlet.java` |
| `/servlet/SuppliersServlet` | SuppliersServlet | com.hy.cxp.supermarket.servlet.SuppliersServlet | `src/com/hy/cxp/supermarket/servlet/SuppliersServlet.java` |
| `/servlet/GoodsServlet` | GoodsServlet | com.hy.cxp.supermarket.servlet.GoodsServlet | `src/com/hy/cxp/supermarket/servlet/GoodsServlet.java` |

### 过滤器链
| URL 模式 | 过滤器类 |
|---|---|
| `/*` | com.hy.cxp.supermarket.filter.CharacterEncodingFilter |
| `/security/*` | com.hy.cxp.supermarket.filter.SercurityFilter |

### 欢迎文件
- `login.html`
- `index.jsp`

## 前端控制器 / Servlet 分派表
### UsersServlet
| action | 跳转目标 | 读取的参数 | 调用的业务方法 |
|---|---|---|---|
| `(无 action 参数/默认)` | `../security/userList.jsp` | `pageIndex` | `userBiz.getPageInfo`、`userBiz.list` |
| `details` | `../security/userView.jsp` | `id` | `userBiz.findById` |
| `add` | `Users.do` | `houseDate`、`sex`、`userAddress`、`userId`、`userName`、`userlei`、`userpassword`、`userphone` | `userBiz.add` |
| `update` | `../security/userUpdate.jsp` | `id` | `userBiz.findById` |
| `save` | `Users.do` | `houseDate`、`id`、`sex`、`userAddress`、`userlei`、`userphone` | `userBiz.update` |
| `del` | `Users.do` | `uid` | `userBiz.del` |
| `search` | `../security/userList.jsp` | `name` | `biz.findByName` |

### OrdersServlet
| action | 跳转目标 | 读取的参数 | 调用的业务方法 |
|---|---|---|---|
| `(无 action 参数/默认)` | `../security/billList.jsp` | `pageIndex` | `orderBiz.getPageInfo`、`orderBiz.list`、`supplierBiz.list` |
| `addView` | `../security/billAdd.jsp` | - | `goodBiz.list` |
| `add` | `Orders.do` | `billId`、`billName`、`billNum`、`supplier`、`zhifu` | `orderBiz.add`、`orderBiz.findGid` |
| `details` | `../security/billView.jsp` | `id` | `orderBiz.findById` |
| `update` | `../security/billUpdate.jsp` | `id` | `orderBiz.findById`、`orderBiz.findSupByGname` |
| `save` | `Orders.do` | `billId`、`billName`、`onum`、`supplier`、`zhifu` | `orderBiz.findGid`、`orderBiz.update` |
| `del` | `Orders.do` | `oid` | `orderBiz.del` |
| `supplierajax` | - | `gname` | `biz.findSupByGname` |
| `goodajax` | - | `gname`、`sid` | `biz.findGid`、`goodBiz.findById` |
| `search` | `../security/billList.jsp` | `gname`、`opaid`、`sname` | `ordersBiz.search`、`supplierBiz.list` |

### SuppliersServlet
| action | 跳转目标 | 读取的参数 | 调用的业务方法 |
|---|---|---|---|
| `(无 action 参数/默认)` | `../security/providerList.jsp` | `pageIndex` | `suppliersBiz.getPageInfo`、`suppliersBiz.list` |
| `add` | `Suppliers.do` | `address`、`describe`、`fax`、`people`、`phone`、`providerId`、`providerName` | `supplierBiz.add` |
| `details` | `../security/providerView.jsp` | `id` | `suppliersBiz.findById` |
| `update` | `../security/providerUpdate.jsp` | `id` | `suppliersBiz.findByIdForUpdate` |
| `save` | `Suppliers.do` | `address`、`describe`、`fax`、`id`、`phone` | `suppliersBiz.update` |
| `del` | `Suppliers.do` | `sid` | `supplierBiz.del` |
| `search` | `../security/providerList.jsp` | `name` | `biz.findByName` |

### GoodsServlet
| action | 跳转目标 | 读取的参数 | 调用的业务方法 |
|---|---|---|---|
| `(无 action 参数/默认)` | `../security/productList.jsp` | - | `goodBiz.list` |
| `add` | `Goods.do` | `gstock`、`price`、`productId`、`productName`、`sid`、`unit` | `goodBiz.add` |
| `details` | `../security/productView.jsp` | `id` | `goodBiz.findById` |
| `update` | `../security/productUpdate.jsp` | `id` | `goodBiz.findById`、`goodBiz.findSid` |
| `save` | `Goods.do` | `gstock`、`price`、`productId`、`productName`、`sid`、`unit` | `goodBiz.update` |
| `del` | `Goods.do` | `gid` | `goodBiz.del` |
| `addView` | `../security/productAdd.jsp` | - | `goodBiz.findSid` |
| `search` | `../security/productList.jsp` | `name` | `biz.findByName` |

### ControllerServlet（前端控制器）
| action | 跳转目标 | 读取的参数 | 调用的业务方法 |
|---|---|---|---|
| `login.do` | `login.jsp`、`security/welcome.jsp` | `password`、`username` | `userBiz.login` |
| `modifyPassword.do` | `security/welcome.jsp` | `newPassword`、`oldPassword` | - |
| `loginOut.do` | `login.html` | - | - |
| `Users.do` | `/servlet/UsersServlet` | - | - |
| `Goods.do` | `/servlet/GoodsServlet` | - | - |
| `Suppliers.do` | `/servlet/SuppliersServlet` | - | - |
| `Orders.do` | `/servlet/OrdersServlet` | - | - |

## 页面 → 后端 调用矩阵
只统计**主动发起**的调用（表单 action、AJAX URL），导航栏链接不计入，否则每个页面都会因为导航栏而同时引用所有模块。

| 页面 | 方式 | 目标 | 处理者 |
|---|---|---|---|
| `WebRoot/login.jsp` | 表单提交 | `login.do` | 解析失败 |
| `WebRoot/security/billAdd.jsp` | 表单提交 | `Orders.do?action=add` | OrdersServlet |
| `WebRoot/security/billList.jsp` | 异步请求 | `Orders.do?action=search&gname=` | OrdersServlet |
| `WebRoot/security/billUpdate.jsp` | 表单提交 | `Orders.do?action=save` | OrdersServlet |
| `WebRoot/security/billView.jsp` | - | - | - |
| `WebRoot/security/password.jsp` | 表单提交 | `modifyPassword.do` | 解析失败 |
| `WebRoot/security/productAdd.jsp` | 表单提交 | `Goods.do?action=add` | GoodsServlet |
| `WebRoot/security/productList.jsp` | 异步请求 | `Goods.do?action=search&name=` | GoodsServlet |
| `WebRoot/security/productUpdate.jsp` | 表单提交 | `Goods.do?action=save` | GoodsServlet |
| `WebRoot/security/productView.jsp` | - | - | - |
| `WebRoot/security/providerAdd.jsp` | 表单提交 | `Suppliers.do?action=add` | SuppliersServlet |
| `WebRoot/security/providerList.jsp` | 异步请求 | `Suppliers.do?action=search&name=` | SuppliersServlet |
| `WebRoot/security/providerUpdate.jsp` | 表单提交 | `Suppliers.do?action=save&id=${supplier.sid}` | SuppliersServlet |
| `WebRoot/security/providerView.jsp` | - | - | - |
| `WebRoot/security/userAdd.jsp` | 表单提交 | `Users.do?action=add` | UsersServlet |
| `WebRoot/security/userList.jsp` | 异步请求 | `Users.do?action=search&name=` | UsersServlet |
| `WebRoot/security/userUpdate.jsp` | 表单提交 | `Users.do?action=save&id=${user.userid}` | UsersServlet |
| `WebRoot/security/userView.jsp` | - | - | - |
| `WebRoot/security/welcome.jsp` | - | - | - |

### 页面 → 静态/内部包含
| 页面 | 静态包含 | 运行时包含 | 脚本片段数 | EL 表达式数 |
|---|---|---|---|---|
| `WebRoot/login.jsp` | - | - | 2 | 1 |
| `WebRoot/security/billAdd.jsp` | - | - | 3 | 3 |
| `WebRoot/security/billList.jsp` | - | - | 3 | 15 |
| `WebRoot/security/billUpdate.jsp` | - | - | 2 | 10 |
| `WebRoot/security/billView.jsp` | - | - | 2 | 8 |
| `WebRoot/security/password.jsp` | - | - | 2 | 2 |
| `WebRoot/security/productAdd.jsp` | - | - | 2 | 3 |
| `WebRoot/security/productList.jsp` | - | - | 2 | 7 |
| `WebRoot/security/productUpdate.jsp` | - | - | 2 | 8 |
| `WebRoot/security/productView.jsp` | - | - | 2 | 7 |
| `WebRoot/security/providerAdd.jsp` | - | - | 2 | 1 |
| `WebRoot/security/providerList.jsp` | - | - | 2 | 11 |
| `WebRoot/security/providerUpdate.jsp` | - | - | 2 | 8 |
| `WebRoot/security/providerView.jsp` | - | - | 2 | 7 |
| `WebRoot/security/userAdd.jsp` | - | - | 2 | 1 |
| `WebRoot/security/userList.jsp` | - | - | 8 | 10 |
| `WebRoot/security/userUpdate.jsp` | - | - | 2 | 8 |
| `WebRoot/security/userView.jsp` | - | - | 2 | 8 |
| `WebRoot/security/welcome.jsp` | - | - | 2 | 1 |

## 后端 → 页面 跳转
| 类 | 转发 (forward) | 重定向 (redirect) |
|---|---|---|
| `ControllerServlet` | `/servlet/GoodsServlet`、`/servlet/OrdersServlet`、`/servlet/SuppliersServlet`、`/servlet/UsersServlet`、`login.jsp` | `login.html`、`security/welcome.jsp` |
| `SercurityFilter` | - | `/supermarketmanager1115/login.html` |
| `GoodsServlet` | `../security/productAdd.jsp`、`../security/productList.jsp`、`../security/productUpdate.jsp`、`../security/productView.jsp` | `Goods.do` |
| `OrdersServlet` | `../security/billAdd.jsp`、`../security/billList.jsp`、`../security/billUpdate.jsp`、`../security/billView.jsp` | `Orders.do` |
| `SuppliersServlet` | `../security/providerList.jsp`、`../security/providerUpdate.jsp`、`../security/providerView.jsp` | `Suppliers.do` |
| `UsersServlet` | `../security/userList.jsp`、`../security/userUpdate.jsp`、`../security/userView.jsp` | `Users.do` |

## 第三方依赖
### war 内已打包的 JAR
| 文件 | 体积 |
|---|---|
| `WebRoot/WEB-INF/lib/commons-beanutils-1.7.0.jar` | 184 KB |
| `WebRoot/WEB-INF/lib/commons-collections-3.2.jar` | 558 KB |
| `WebRoot/WEB-INF/lib/commons-lang-2.4.jar` | 256 KB |
| `WebRoot/WEB-INF/lib/commons-logging-1.1.jar` | 52 KB |
| `WebRoot/WEB-INF/lib/ezmorph-1.0.4.jar` | 84 KB |
| `WebRoot/WEB-INF/lib/json-lib-2.2.3-jdk13.jar` | 145 KB |

### 源码实际使用的第三方命名空间
| 命名空间 | 依赖库 | 引用次数 | 打包状态 | 缺少的配套 jar |
|---|---|---|---|---|
| `net.sf.json` | json-lib | 1 | 已在 war 中 | - |

## 数据库依赖
| 数据库 | 判定依据 | 驱动 jar 关键字 | 驱动是否在 war 内 |
|---|---|---|---|
| Oracle | SQL 方言 | ojdbc | 否（由容器 lib 提供） |


数据源通过 JNDI 获取，需在运行容器的配置中提供资源：

- `java:comp/env/jdbc/orcl`

### SQL 脚本中的数据库对象
| 脚本 | 编码 | 表 | 视图 | 序列 |
|---|---|---|---|---|
| `supermarket.sql` | gb18030 | goods、orders、suppliers、users | goods_view、orders_detail、orders_view、suppliers_view、users_view | seq_gid、seq_oid、seq_sid、seq_uid |
