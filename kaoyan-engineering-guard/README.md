# 考研平台工程守卫（kaoyan-engineering-guard）

把硕途考研平台（`backend-main-fastapi` FastAPI + PostgreSQL / `frontend` React18 + Vite）
在真实事故中验证过的工程约束打包为一个项目级 Skill，供后续会话在改代码前加载。

## 组件

- `skills/kaoyan-engineering-guard/SKILL.md`：加载时机、决策规则摘要、验证纪律。
- `skills/kaoyan-engineering-guard/references/traps.md`：T1–T13 实测陷阱档案（现象→根因→处置）。

不含 commands / agents / hooks / MCP：本插件只沉淀约束与流程，不需要运行时集成。

## 来源

全部条目来自本项目会话的实测证据（测试 traceback、线上 500 日志、pg_indexes 核对、
浏览器截图对照），非外部模板。未包含任何凭据、密钥或机器绝对路径。

## 使用

安装启用后，在涉及迁移、测试、接口对接、UI 验证的请求中会自动触发；也可手动
`/kaoyan-engineering-guard` 加载。源码目录即本目录；安装需用户明确授权后进行。
