# 快速开始

> 最后核对：2026-11-20 · commit a7f92ea · 维护人：pyy

## 1. 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| Python | 3.10+（本项目在 3.13 验证） | 后端 |
| PostgreSQL | 16 + pgvector | 生产与测试都必须真 PG（SQLite 仅历史兼容） |
| Node.js | 18+ | 仅改前端时需要 |
| GPU | 可选 | 本地模型 / OCR 加速 |

## 2. 后端启动

```bash
cd backend-main-fastapi
pip install -r requirements.txt -r requirements-dev.txt
copy ..\deploy\backend.env.template .env      # 填 PG_PASSWORD / JWT_SECRET / KAOYAN_SECRET_KEY
python scripts/diagnostics/check_env.py       # 环境自检
python main.py                                # http://127.0.0.1:8000
```

首次登录使用 `ADMIN_USERNAME` / `ADMIN_INITIAL_PASSWORD`，**首次登录强制改密**。

## 3. 五种启动方式

| 方式 | 入口 | 场景 |
|---|---|---|
| 图形启动器 | `启动.bat` | 日常（含服务状态/菜单） |
| 本机模式 | `启动-本机.bat` | 仅 127.0.0.1，最安全 |
| 局域网模式 | `启动-局域网.bat` | 手机/平板访问，显示二维码 |
| 命令行 | `python main.py` | 开发调试 |
| 系统服务 | `deploy/kaoyan.service` | 服务器（systemd） |

## 4. 数据库初始化

```bash
# 建库（示例）
createdb -U postgres kaoyan
psql -d kaoyan -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 结构：create_all 兜底 + 编号 SQL 账本（幂等）
python scripts/execute_core_sql.py --status      # 看已登记/待执行/checksum 漂移
python scripts/execute_core_sql.py --all-pending # 执行未入账脚本
```

> 存量库首次接账本：`--all-pending` 在账本为空且库中已有业务表时自动走 baseline
> （只登记不执行），避免重放历史脚本。全新空库则全量执行。

## 5. 前端构建

```bash
cd frontend
npm ci
npm run lint        # eslint（0 error 门禁）
npm test            # vitest
npm run build       # 产物直出 ../backend-main-fastapi/static
```

## 6. 常见问题

| 症状 | 排查 |
|---|---|
| 启动报 PG 连接失败 | `.env` 的 `PG_*`；`pg_isready -h 127.0.0.1` |
| `/api/health` degraded | 看返回的 `kb.vector_store` / `kb.fts5` / `kb.quiz` |
| 登录后 401 循环 | cookie 是否 Secure（生产默认 Secure，需 HTTPS）；`COOKIE_SECURE=0` 仅过渡 |
| 前端页面 404 / 静态 MIME 错 | 是否 `npm run build` 到 backend static；base 必须为 `/` |
| 测试连到生产库 | conftest 会硬断言退出；检查 `PG_DATABASE` 是否被改写为 `kaoyan_test` |
