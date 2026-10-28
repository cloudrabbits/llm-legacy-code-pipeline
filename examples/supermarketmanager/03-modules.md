# 03 · 功能模块分析
> 共识别出 **4 个业务模块**，另有 3 个页面未挂接到任何业务 Servlet。

## 模块总览
| # | 后端领域 | 前端页面前缀 | Servlet | 页面数 | 能力 |
|---|---|---|---|---|---|
| 1 | **Goods** | `product*` | GoodsServlet | 4 | 新增、删除、修改、查询、分页、模糊查询 |
| 2 | **Orders** | `bill*` | OrdersServlet | 4 | 新增、删除、修改、查询、分页、模糊查询 |
| 3 | **Suppliers** | `provider*` | SuppliersServlet | 4 | 新增、删除、修改、查询、分页、模糊查询 |
| 4 | **Users** | `user*` | UsersServlet | 4 | 新增、删除、修改、查询、分页、模糊查询 |

> 「前端页面前缀」是从页面名（`userAdd` / `userList` …）反推出的 UI 术语。老项目常见后端 `Suppliers` 与前端 `provider*` 不一致，这里显式标出映射。

## 1. Goods（页面群：`product*`）
| 层 | 构件 |
|---|---|
| 页面层 | `WebRoot/security/productAdd.jsp`、`WebRoot/security/productList.jsp`、`WebRoot/security/productUpdate.jsp`、`WebRoot/security/productView.jsp` |
| 控制层 | `com.hy.cxp.supermarket.servlet.GoodsServlet` |
| 业务层 | `com.hy.cxp.supermarket.biz.GoodsBiz`、`com.hy.cxp.supermarket.biz.impl.GoodsBizImpl` |
| 持久层 | `com.hy.cxp.supermarket.dao.GoodsDao`、`com.hy.cxp.supermarket.dao.impl.GoodsDaoImpl` |
| 实体/视图对象 | `com.hy.cxp.supermarket.entity.Goods`、`com.hy.cxp.supermarket.entity.GoodsView` |
| 数据表 | `goods`、`goods_view`、`suppliers` |

### 支持的动作
- `(无 action 参数/默认)`
- `add`
- `addView`
- `del`
- `details`
- `save`
- `search`
- `update`

### 页面清单
| 页面 | 行数 | 脚本片段 | 表单提交目标 |
|---|---|---|---|
| `WebRoot/security/productAdd.jsp` | 132 | 2 | `Goods.do?action=add` |
| `WebRoot/security/productList.jsp` | 139 | 2 | - |
| `WebRoot/security/productUpdate.jsp` | 129 | 2 | `Goods.do?action=save` |
| `WebRoot/security/productView.jsp` | 101 | 2 | - |

### 涉及的数据对象
- `goods`
- `goods_view`
- `suppliers`


## 2. Orders（页面群：`bill*`）
| 层 | 构件 |
|---|---|
| 页面层 | `WebRoot/security/billAdd.jsp`、`WebRoot/security/billList.jsp`、`WebRoot/security/billUpdate.jsp`、`WebRoot/security/billView.jsp` |
| 控制层 | `com.hy.cxp.supermarket.servlet.OrdersServlet` |
| 业务层 | `com.hy.cxp.supermarket.biz.OrdersBiz`、`com.hy.cxp.supermarket.biz.impl.OrdersBizImpl` |
| 持久层 | `com.hy.cxp.supermarket.dao.OrdersDao`、`com.hy.cxp.supermarket.dao.impl.OrdersDaoImpl` |
| 实体/视图对象 | `com.hy.cxp.supermarket.entity.Orders`、`com.hy.cxp.supermarket.entity.OrdersDetail`、`com.hy.cxp.supermarket.entity.OrdersView`、`com.hy.cxp.supermarket.entity.Suppliers` |
| 数据表 | `goods`、`orders`、`orders_view` |

### 支持的动作
- `(无 action 参数/默认)`
- `add`
- `addView`
- `del`
- `details`
- `goodajax`
- `save`
- `search`
- `supplierajax`
- `update`

### 页面清单
| 页面 | 行数 | 脚本片段 | 表单提交目标 |
|---|---|---|---|
| `WebRoot/security/billAdd.jsp` | 129 | 3 | `Orders.do?action=add` |
| `WebRoot/security/billList.jsp` | 198 | 3 | - |
| `WebRoot/security/billUpdate.jsp` | 147 | 2 | `Orders.do?action=save` |
| `WebRoot/security/billView.jsp` | 82 | 2 | - |

### 涉及的数据对象
- `goods`
- `orders`
- `orders_view`


## 3. Suppliers（页面群：`provider*`）
| 层 | 构件 |
|---|---|
| 页面层 | `WebRoot/security/providerAdd.jsp`、`WebRoot/security/providerList.jsp`、`WebRoot/security/providerUpdate.jsp`、`WebRoot/security/providerView.jsp` |
| 控制层 | `com.hy.cxp.supermarket.servlet.SuppliersServlet` |
| 业务层 | `com.hy.cxp.supermarket.biz.SuppliersBiz`、`com.hy.cxp.supermarket.biz.impl.SuppliersBizImpl` |
| 持久层 | `com.hy.cxp.supermarket.dao.SuppliersDao`、`com.hy.cxp.supermarket.dao.impl.SuppliersDaoImpl` |
| 实体/视图对象 | `com.hy.cxp.supermarket.entity.Suppliers` |
| 数据表 | `suppliers`、`suppliers_view` |

### 支持的动作
- `(无 action 参数/默认)`
- `add`
- `del`
- `details`
- `save`
- `search`
- `update`

### 页面清单
| 页面 | 行数 | 脚本片段 | 表单提交目标 |
|---|---|---|---|
| `WebRoot/security/providerAdd.jsp` | 128 | 2 | `Suppliers.do?action=add` |
| `WebRoot/security/providerList.jsp` | 182 | 2 | - |
| `WebRoot/security/providerUpdate.jsp` | 128 | 2 | `Suppliers.do?action=save&id=${supplier.sid}` |
| `WebRoot/security/providerView.jsp` | 80 | 2 | - |

### 涉及的数据对象
- `suppliers`
- `suppliers_view`


## 4. Users（页面群：`user*`）
| 层 | 构件 |
|---|---|
| 页面层 | `WebRoot/security/userAdd.jsp`、`WebRoot/security/userList.jsp`、`WebRoot/security/userUpdate.jsp`、`WebRoot/security/userView.jsp` |
| 控制层 | `com.hy.cxp.supermarket.servlet.UsersServlet` |
| 业务层 | `com.hy.cxp.supermarket.biz.UsersBiz`、`com.hy.cxp.supermarket.biz.impl.UsersBizImpl` |
| 持久层 | `com.hy.cxp.supermarket.dao.UsersDao`、`com.hy.cxp.supermarket.dao.impl.UsersDaoImpl` |
| 实体/视图对象 | `com.hy.cxp.supermarket.entity.Users`、`com.hy.cxp.supermarket.entity.UsersView` |
| 数据表 | `users`、`users_view` |

### 支持的动作
- `(无 action 参数/默认)`
- `add`
- `del`
- `details`
- `save`
- `search`
- `update`

### 页面清单
| 页面 | 行数 | 脚本片段 | 表单提交目标 |
|---|---|---|---|
| `WebRoot/security/userAdd.jsp` | 145 | 2 | `Users.do?action=add` |
| `WebRoot/security/userList.jsp` | 177 | 8 | - |
| `WebRoot/security/userUpdate.jsp` | 143 | 2 | `Users.do?action=save&id=${user.userid}` |
| `WebRoot/security/userView.jsp` | 115 | 2 | - |

### 涉及的数据对象
- `users`
- `users_view`


## 公共 / 基础设施构件
| 类 | 层 | 行数 | 说明 |
|---|---|---|---|
| `BaseDao` | 工具类 | 117 | 提供连接获取 |
| `Page` | 工具类 | 112 | - |
| `ControllerServlet` | 控制层 | 133 | 继承 `HttpServlet` |
| `CharacterEncodingFilter` | 过滤器/拦截器 | 44 | 实现 `Filter` |
| `SercurityFilter` | 过滤器/拦截器 | 47 | 实现 `Filter` |

## 未归属到业务模块的页面
这些页面不承载任何业务模块的 CRUD，通常是登录/改密/欢迎页等由前端控制器直接处理的公共页，或已废弃页面：

| 页面 | 行数 | 表单目标 | 归属说明 |
|---|---|---|---|
| `WebRoot/login.jsp` | 57 | `login.do` | 由基础设施 ControllerServlet 处理（Servlet 转发 `login.jsp`），不属于任何业务模块 |
| `WebRoot/security/password.jsp` | 121 | `modifyPassword.do` | 表单提交到 `modifyPassword.do`，未解析到业务 Servlet |
| `WebRoot/security/welcome.jsp` | 79 | - | 由基础设施 ControllerServlet 处理（Servlet 重定向 `security/welcome.jsp`），不属于任何业务模块 |

## 典型请求链路
| 入口页面 | 调用链 | 解析过程 |
|---|---|---|
| `WebRoot/security/productAdd.jsp` | `Goods.do?action=add` → `GoodsServlet` → `GoodsDao` → `GoodsDaoImpl` | `Goods.do` 命中 `*.do`（extension） → ControllerServlet 分派 `Goods.do` → 转交 `/servlet/GoodsServlet` → 命中 `/servlet/GoodsServlet` -> GoodsServlet |
| `WebRoot/security/billAdd.jsp` | `Orders.do?action=add` → `OrdersServlet` → `OrdersDao` → `OrdersDaoImpl` | `Orders.do` 命中 `*.do`（extension） → ControllerServlet 分派 `Orders.do` → 转交 `/servlet/OrdersServlet` → 命中 `/servlet/OrdersServlet` -> OrdersServlet |
| `WebRoot/security/providerAdd.jsp` | `Suppliers.do?action=add` → `SuppliersServlet` → `SuppliersDao` → `SuppliersDaoImpl` | `Suppliers.do` 命中 `*.do`（extension） → ControllerServlet 分派 `Suppliers.do` → 转交 `/servlet/SuppliersServlet` → 命中 `/servlet/SuppliersServlet` -> SuppliersServlet |
| `WebRoot/security/userAdd.jsp` | `Users.do?action=add` → `UsersServlet` → `UsersDao` → `UsersDaoImpl` | `Users.do` 命中 `*.do`（extension） → ControllerServlet 分派 `Users.do` → 转交 `/servlet/UsersServlet` → 命中 `/servlet/UsersServlet` -> UsersServlet |
