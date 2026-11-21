---
name: kaoyan-engineering-guard
description: 在硕途考研平台仓库（backend-main-fastapi / frontend）做任何后端结构变更、测试编写、前端接口对接或 UI 验证之前加载。携带已实测踩坑验证过的工程约束：迁移账本 checksum 规则、测试库污染防护、mock 与真实接口形状对照、空态即交付、URL 任务一致性、浏览器验证纪律。触发词：考研平台、kaoyan、gzdx_ky、迁移、schema_migrations、test_auth、mock、空态、验证截图。
---

# 考研平台工程守卫

本 skill 的每一条规则都来自本仓库真实事故（测试全绿但线上崩、查不到、渲染空白），不是推测。
修改代码前先读 [references/traps.md](references/traps.md) 对应章节；交付前按「验证纪律」走完。

## 何时加载

- 新增 / 修改 `backend-main-fastapi/core/sql/` 编号迁移脚本
- 编写或修改 `backend-main-fastapi/tests/` 用例与 fixture
- 前端 `frontend/src/api/client.js` 对接、页面 mock、状态渲染
- 对运行中的 :8000 服务做浏览器 / curl 验证
- 任何「已完成」声明之前

## 决策规则（摘要）

1. **迁移账本**：编号脚本一旦入账，内容不可再改（checksum 校验会 halt 全部后续迁移）。
   需要变更结构 → 新增编号脚本。确需重登记旧脚本：先逐条比对线上 schema 与脚本当前内容
   （列类型、索引、约束全等），确认后才更新 `schema_migrations.checksum`，再 `run_pending`。
   启动日志为 GBK 编码：grep 中文会漏，用 ASCII 关键字（编号、`Traceback`）或直接查库核对。
2. **测试库隔离**：同一测试库禁止两个 pytest 进程并发（fixture 会清 users / auth_events，
   互相制造假失败）。开跑前 `tasklist` / netstat 确认无残留 pytest；后台任务被 stop 后
   子进程可能存活，必须按 PID 清理。
3. **形状对照**：mock 与断言必须对照真实路由返回的字段名、容器类型（`[]` vs 对象）、
   数值口径（0-100 vs 0-1）与 client.js 现存方法名；禁止照页面想象写 mock。
4. **空态即交付**：不得塞演示数据填 UI；无数据时的空态文案与恢复路径是功能的一部分。
   凭据解密失败等上游损坏 → 降级为「未配置」空态 + 告警日志，不允许整链路 500。
5. **URL 任务一致性**：任何带 URL 的调用必须与当前任务目标一致；不得复用历史会话里的
   代理 /  routify 地址或无关旧 URL。
6. **浏览器验证**：hash 路由同 URL 导航是 same-document，不会加载新 bundle —— 改前端后
   必须 `location.reload()` 或跨文档导航；截图一次批量看桌面 + 移动，修复一批后再确认一轮。
7. **会话与重启**：JWT 签名密钥随进程启动生成时，重启 :8000 会使全部会话失效；
   验证脚本要先重新登录再探接口，401 不等于接口坏。

## 验证纪律

- 后端改动：跑对应测试文件全量（`pytest tests/test_x.py -q`），报告真实通过数 / 耗时；
  失败先取 traceback 再改，禁止靠猜。
- 结构改动：查 `pg_indexes` / `information_schema` 确认线上已生效，不以「启动没报错」为准。
- 前端改动：`npm run build` 成功 + 浏览器 reload 后截图核对缺陷清单逐条消失 + console error 清单核对。
- 声明完成前：把目标拆成清单，逐条对应证据（文件、命令输出、截图、测试数）；缺证据 = 未完成。
