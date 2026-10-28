# 00 · 环境预检报告
> 本阶段不调用任何模型，纯本地静态检查。

## 检查项
| 检查项 | 结果 | 判定 |
|---|---|---|
| Python | 3.13.2 | OK |
| 操作系统 | Windows 11 | OK |
| 本机 CPU 架构 | AMD64 | OK |
| 控制台输出 | 已强制 UTF-8 | OK |
| 目标路径 | D:\IdeaProjects\supermarketmanager | OK |
| 目录可读 | 是 | OK |
| 目录可写 | 是 | 提示：只读挂载也可以，本工具对目标只读 |
| 文本文件数 | 66 | OK |
| 二进制/其他文件数 | 42 | OK |
| 文本总行数 | 16,966 | OK |
| 主编码 | utf-8-sig | OK |
| 是否混编码 | 是（已逐个文件降级解码） | 提示 |

## 编码普查
按命中次数排列。**混编码是老项目常态**，所有读取都走`utf-8-sig → utf-8 → gb18030 → big5 → latin-1` 降级链，不会因个别文件乱码而中断。

| 编码 | 文件数 |
|---|---|
| utf-8-sig | 65 |
| gb18030 | 1 |

## 非 UTF-8 文件清单
这些文件在迁移到 UTF-8 工具链（Maven/Gradle/新版 IDE）时需要转码：

- `supermarket.sql`

## 分析入口判定
- 部署描述文件：`WebRoot/WEB-INF/web.xml`，声明版本 `3.0`，Schema 版本 `2.5`
- Java 源文件 33 个，根包：`com.hy.cxp.supermarket.biz`, `com.hy.cxp.supermarket.biz.impl`, `com.hy.cxp.supermarket.controller`, `com.hy.cxp.supermarket.dao`, `com.hy.cxp.supermarket.dao.impl`
- JSP 页面 19 个

## 结论
**通过**：环境满足条件，目标可读，共发现 66 个可解析文本文件（16,966 行）。继续执行后续阶段。
