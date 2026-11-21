# 架构总览

> 最后核对：2026-11-20 · commit a7f92ea · 维护人：pyy

## 1. 分层

```
浏览器 (React SPA, 构建产物直出 backend/static)
   │  httpOnly JWT cookie + SSE
Nginx (静态 + 反代 + 限流 + 安全头)
   │
FastAPI (main.py 构造 app → app_lifecycle.lifespan → routers.registry.iter_routers)
   ├─ routers/   6 域 · 485 条路由（唯一挂载点 registry.py）
   ├─ services/  业务服务（检索 / AI 路由 / 知识库管线 / 仪表盘聚合 …）
   ├─ core/      ORM 模型（core/models 按域拆分）· 数据库会话 · core/sql 编号迁移
   ├─ utils/     安全、scope 行级隔离、日志、响应编码
   └─ pipeline/  离线数据管线（采集 / OCR / 向量 / 迁移脚本）
PostgreSQL 16 + pgvector   ←→   家中算力节点（Tailscale：OCR 8888 / rerank 8140 / Ollama 11434）
```

## 2. 路由域（routers/registry.py 为唯一真相）

| 域 | 模块数 | 内容 |
|---|---|---|
| `study` | 24 | 仪表盘 / 刷题 / 错题 / 复习 / 单词 / 任务规划 / 学习统计 |
| `knowledge` | 10 | 文档 / 知识库 / 分块 / 教材 / 检索 / 导入 |
| `ai` | 6 | 答疑 / 讲题 / 会话 / 模型设置 |
| `kaoyan` | 6 | 院校 / 专业 / 分数线 / 对比 / 自划线 |
| `platform` | 6 | 管理端 / 平台配置 / 通知 / 网盘 / 健康 |
| `auth` | 1 | 登录 / 刷新 / 登出 / 用户 |

新增路由只在 `routers/<domain>/` 下建模块并在 registry 登记——`main.py` 不允许再写 `include_router`。

## 3. 数据流（关键三条）

1. **文档入库**：上传 → 解析（PDF/Word/图片 OCR）→ 清洗 → 分块 → 建向量 + 全文索引 → 体检（`services/kb_pipeline.py`）→ 可自愈。
2. **刷题闭环**：组卷 → `quiz_sessions` → 逐题作答 `quiz_attempts` → 交卷判分 → 错题 `error_records` → 复习排程 `review_schedules` → 到期进复习队列。
3. **AI 答疑**：问题 → 科目识别（`ai_router.detect_subject`）→ 混合检索（FTS + 向量 + RRF）→ 上下文拼装 → 本地 Ollama / 云端兜底 → 答案 + 引用 → 回流薄弱点。

## 4. 关键约束（违反即事故）

| 约束 | 位置 | 守卫 |
|---|---|---|
| 测试绝不碰生产库 | `tests/conftest.py` | import 前硬断言，生产库名即退出 |
| 行级隔离统一机制 | `utils/scope.py` + `core/sql/108_*` | `tests` 双账号用例（e2e isolation） |
| 结构变更走编号 SQL | `core/sql/*.sql` + `schema_migrations` | `tests/test_schema_ledger.py` |
| 视图只读 | `tests/test_view_readonly.py` | ORM 不得映射视图 |
| 依赖方向 routers → services → models/utils | `tests/test_import_direction.py`（计划） | AST 扫描 |
| 时间统一 UTC 存储、前端按本地展示 | `utils/response.py`（UtcZJSONResponse） | 契约测试 |

## 5. 前后端契约

- 后端响应统一 snake_case；时间带 `+00:00` 偏移。
- 前端 `src/api/client.js` 是唯一请求出口；`src/nav/navConfig.js` 是唯一导航源。
- 字段漂移由契约测试（`tests/test_api_contract.py`、`test_words_*`）在 CI 暴露。

## 6. 部署形态

见 [deploy/DEPLOY.md](../../deploy/DEPLOY.md)：Nginx + systemd（uvicorn 多 worker，仅监听 127.0.0.1）+ PostgreSQL（仅 localhost）+ 家中算力节点（Tailscale 内网）。版本标识由 `/api/health` 的 `git_sha` 提供。
