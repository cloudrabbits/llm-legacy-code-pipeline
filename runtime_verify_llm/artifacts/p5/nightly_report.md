# 夜间分析报告

- 项目：**supermarketmanager**（66 个文本文件，Java 33 / JSP 19）
- 识别模块：Goods, Orders, Suppliers, Users
- 依赖违规：0 条
- 风险条目：10

## 风险清单

- **[中]** 控制器层采用原生Servlet架构，缺乏现代Spring MVC或RESTful规范支持，不利于接口标准化与前后端解耦。（证据：com.hy.cxp.supermarket.servlet.GoodsServlet）
- **[高]** 业务涉及goods、goods_view与suppliers三表关联操作，切片未体现显式事务边界声明，跨表数据修改存在一致性隐患。（证据：com.hy.cxp.supermarket.biz.impl.GoodsBizImpl）
- **[中]** JSP页面集中存放于security目录但未见拦截器或RBAC配置说明，结合完整CRUD权限范围，存在越权访问风险。（证据：WebRoot/security/productUpdate.jsp）
- **[中]** 传统JSP+Servlet架构缺乏前后端分离与统一路由管理，页面直接依赖后端JSP渲染，不利于后续微服务化或现代前端框架迁移。（证据：WebRoot/security/billAdd.jsp,com.hy.cxp.supermarket.servlet.OrdersServlet）
- **[中]** 实体层引入非订单核心域类Suppliers至本模块，存在领域边界模糊与跨表/跨域耦合风险，可能影响订单数据模型的单一职责。（证据：com.hy.cxp.supermarket.entity.Suppliers）
- **[低]** 模块文件缺失P1架构标签校验，缺乏静态分层依赖约束，易引发越层调用或架构规范执行偏差。（证据：模块切片元数据（无该模块的 P1 标签））
- **[中]** Servlet混合处理标准CRUD与AJAX异步请求（如goodajax/supplierajax），请求分发逻辑内聚性不足，增加单元测试与维护成本。（证据：com.hy.cxp.supermarket.servlet.OrdersServlet.actions(goodajax,supplierajax)）
- **[中]** 单Servlet多Action模式存在耦合风险，所有用户操作路由至同一控制器，功能扩展时易导致方法膨胀与职责边界模糊。（证据：com.hy.cxp.supermarket.servlet.UsersServlet）
- **[中]** 引入视图实体UsersView对接users_view表，若涉及复杂关联或隐式更新逻辑，可能引发读写语义混淆与数据一致性隐患。（证据：com.hy.cxp.supermarket.entity.UsersView）
- **[低]** 模块未分配P1核心链路标签，缺乏关键路径标识，不利于生产环境性能监控、压测基线建立与故障快速定界。（证据：无该模块的 P1 标签）

## 产物索引

- `p0`：baseline.md, inventory.json
- `p1`：P1-batch-001.jsonl, P1-batch-002.jsonl
- `p2`：modules.json
- `p3`：deps.jsonl, layer_matrix.md, violations.json
- `p4`：Goods.md, Orders.md, Suppliers.md, Users.md, risks-Goods.json, risks-Orders.json, risks-Users.json, risks.json
