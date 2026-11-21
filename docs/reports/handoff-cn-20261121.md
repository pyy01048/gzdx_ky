# 交接报告 · 交给 CN 版继续（2026-11-21）

> 项目：D:\研途\gzdx_ky（git 仓库根即此目录；后端在 `backend-main-fastapi/`，前端在 `frontend/`）
> 生产：华为云 60.204.223.140（公网 HTTP，root SSH + paramiko，部署脚本 `deploy/push_update.py`）
> 本轮目标源文档：`D:\下载\考研平台整合落地方案.md`、`D:\桌面\用户管理界面.md`、`D:\桌面\零散方案参考.md`、`D:\研途\V3.12-后台评审报告-V4.0路线图.md`、`D:\研途\V3.12-后台测试标准与移交手册.md`

## 1. 结论速览

| 项 | 状态 |
|---|---|
| 用户管理（邮箱注册 / 邮箱验证 / 找回密码 / 用户管理界面重做 / pyy 密码重置〔凭据不入库〕） | ✅ 完成并上线，公网登录实测 200 |
| 《整合落地方案》《零散方案参考》主体（学科评估 119、章节习题同步、data-assets 并入、治理文档等） | ✅ 完成，明细见 `CHANGELOG.md` Unreleased 与 `docs/reports/` 各专项报告 |
| 插件优化（impeccable UI 评审 / vercel react-best-practices / super-dw SQL 索引对照 / plugin-creator 工程约束 skill） | ✅ 已执行并落入代码 |
| V3.12 后台评审整改（B-01~B-10 安全/性能集） | ✅ 代码完成、✅ 已部署、✅ 公网抽验通过（报告 §8.1）；⚠️ 全量 TC 矩阵复验收尾未完 |
| 测试 | ✅ 后端 100+60 passed（1 skip）、前端 492 passed、build ✓ 5.07s、公网只读探针通过 |
| **git 提交** | ❌ **未完**：367 文件已暂存但一次提交因 pre-commit ruff 存量门禁失败（105 errors），新提交数为 0，HEAD 仍是 `26b9bdd` |
| **服务器进程守护加固** | ❌ 未完：monitor cron + systemd faulthandler + 账号 B 重置（脚本已备好未跑） |

## 2. 已经完成并验证的事（都有实测数字，可引用）

### 2.1 用户管理（目标第 1 条）

- 邮箱注册 + 验证码 + 找回密码：迁移 `core/sql/116_users_email_auth.sql`（含节流/审计索引），路由在 `backend-main-fastapi/routers/auth/`，SMTP 走 QQ 主 + 163 备（发信实测 live）。
- 前端重做：`frontend/src/v3/pages/` 的 `UserAdmin.jsx` / `Login.jsx` / `ResetPassword.jsx` / `VerifyEmail.jsx`（按《用户管理界面.md》+ impeccable 评审落地）。
- pyy 密码已重置（**凭据仅运行时持有，不写入仓库/报告**，见红线 §3.2）：本地与公网均实测登录 200（2026-11-21 公网复验）。

### 2.2 V3.12 后台整改（登录安全 / 分页 / 脱敏 / 限流 / 鉴权收敛）

代码与本地验证（详见整改报告 `docs/reports/v312-review-remediation-20261121.md` §1-§7）：

- 登录/refresh 响应体移除明文 token（HttpOnly Cookie 单通道）；refresh 一次性轮换 + 重放灭族 + 登出服务端吊销（迁移 `core/sql/120_auth_sessions.sql`）。
- documents/textbooks 强制分页 + 字段裁剪 + facets + `scope:"global"` 标注：2666 篇列表 8.66s/2.79MB → 0.075s/22.5KB。
- `/api/health` 脱敏（零 DB），git_sha/库况移入 `/api/health/detail`（admin-only）；`/api/auth/*`、`/api/admin/users*` 一律 `no-store`；限流 429 + Retry-After（应用 + nginx 双层）。
- 12 个 documents 写端点收敛 `require_admin`；依赖覆盖矩阵测试（admin/user/anonymous）。
- nginx 站点配置重写（快速失败 / 长任务白名单 600s / server_tokens off / gzip / X-Request-ID / CSP Report-Only）。
- 40+ 脚本硬编码口令收敛到 `scripts/_conn.py`（唯一连接来源）；两份 QA 报告 DSN 脱敏。
- 契约漂移取证（§7 命令可复现）：评审者列的 12 个 404 路径前端调用数为 **0**（URL 是从页面名猜的），T10 反向守卫绿，实际漂移 = 0。
- 用户裁定：B-02 **维持公网 HTTP**（不做 TLS/HSTS，Cookie 无 Secure 位，知情决策已写进报告 §9）。

### 2.3 部署与公网抽验（2026-11-21 本次会话实测）

部署事实：并行「中枢/品牌化」工作流把同一工作树经 `push_update.py` 推上了服务器，**本整改集已随之上线**（`120_auth_sessions` 生效）。当日公网只读探针全部通过：

```
/api/health                    → {"status":"ok","version":"3.0.0"}
/api/documents?page_size=1     → 200  0.084s  3.4KB        （整改前 8.66s/2.79MB）
/api/documents?page_size=101   → 422
/api/health/detail（匿名）      → 401
nginx 头                        → Server 无版本号 / X-Request-ID / CSP Report-Only / auth 路径 no-store
POST /api/auth/login (pyy)     → 200，响应体 "token" 出现 0 次，HttpOnly Cookie×2（refresh 限 Path=/api/auth）
POST /api/auth/refresh 无 Cookie → 401（缺失分支 JSON）
GET /api/auth/me（带 Cookie）→ POST /api/auth/logout → 200 → 200
```

已写入整改报告 §8.1。测试口径：后端 `100 + 60 passed`（1 skip），前端 vitest `50 文件 / 492 passed`，`npm run build` ✓。

## 3. 还没做的事（按优先级，这就是 CN 版的工作清单）

### P0 · 完成 git 提交（用户已授权，唯一卡点是 pre-commit ruff 存量门禁）

当前仓库状态（务必先原样确认再动）：

- HEAD = `26b9bdd`，本次失败提交**没有**产生任何新 commit，**无 stash 残留**（`git stash list` 空）。
- 索引已暂存 367 文件（含 116/120_school_branding 等）；工作树另有 112 个未暂存改动（其中 54 个是 hook 运行时 ruff-format 自动重排，属正常，要一并提交）。
- **尚未跟踪、需要补 add**：`backend-main-fastapi/core/sql/120_auth_sessions.sql`、`deploy/harden_20261121.py`、`deploy/monitor_kaoyan.py`、`deploy/reset_account_b.py`、`docs/reports/v312-review-remediation-20261121.md`（及本交接报告）、`frontend/acceptance/shots/public-schools-live.png`。
- 原计划两笔提交：① 基线 367（含并行品牌化工作）；② V3.12 整改集（排除清单 26 路径的反集——见整改报告 §6 与 CHANGELOG 对应条目）。

待过的门禁（pre-commit 装在仓库根 `D:\研途\gzdx_ky\.pre-commit-config.yaml`，上次失败三件事）：

1. **vendored ECDICT 解析失败**：`scripts/data/ECDICT-master/dictutils.py`、`linguist.py` 是 Python2 语法，ruff-format exit 2。→ 在仓库根 `pyproject.toml` 第 5 行 `extend-exclude` 追加 `"scripts/data/ECDICT-master"`（hook 调用带 `--force-exclude`，配置即生效）。
2. **ruff check 105 errors**：先 `ruff check --fix`（约 51 个安全自动项 I001/F401/F541/E401/UP035 等），剩余人工项：
   - `B904` ×17：`routers/ai/ai.py` 行 308/310/466/593/759/770/781/792/803，`routers/platform/netdisk.py` ×8 → `raise ... from e`。
   - `E712` ×3：`routers/kaoyan/admin_schools.py` —— **是 SQLAlchemy `Column == True` 过滤条件，必须改 `.is_(True)`，绝不能按自动修复改成真值判断**（会静默改 SQL 语义）。
   - `UP038` ×6：`core/pg_types.py` ×3、`routers/kaoyan/kaoyan.py`、`scripts/govern_warn*`、`scripts/import_school_eval_pg.py` → `isinstance(x, (A, B))` 改 `isinstance(x, A | B)`。
   - 杂项：`E741`（kaoyan.py:604、scripts/backfill_school_branding.py:566×2）、`F841 base_end`（routers/study/plan.py）、`B005`、`B007`（dedup 脚本循环变量）。
   - `training/`、`tools/ocr/DeepSeek-OCR`、`_archive` 已在 exclude，不用管。
3. **然后**：`ruff format` 复跑 → 补 add（含上表未跟踪件）→ 提交两笔；注意 hook 还有 end-of-file-fixer/eslint，可能二次改动需再 stage 一轮。

### P1 · 服务器守护加固（脚本已写好、未执行）

`deploy/harden_20261121.py`（paramiko root+key）：monitor → `/opt/kaoyan` + 幂等 crontab；systemd drop-in `PYTHONFAULTHANDLER=1` + daemon-reload + restart；`ACCOUNT_B_PW` 环境变量存在时经 SSH stdin → `deploy/reset_account_b.py`（密码不落盘）→ shred；nginx 部分已在部署时生效、脚本会自然跳过或幂等重放。跑之前：确认重启 kaoyan 服务的影响窗口（低峰执行）。

### P2 · TC 矩阵收尾（对照《V3.12-后台测试标准与移交手册.md》）

- 全端点匿名矩阵 + documents/textbooks 写端点越权（TC 手册口径，公网低负载）。
- 限流 429 JSON 壳 + Retry-After 公网触发（用匿名端点，**不要**用登录失败去触发 ≤5 次红线）。
- 账号 B 重置后首登 + `must_change_password` 流程。
- monitor cron 心跳日志确认。
- 结果续写整改报告 §8.2（append-only），逐条勾 G1-G12，G10 在 P0 提交后复查 `/api/health/detail` 的 git_sha 无 `-dirty`。

### P3 · 明确不做 / 留待裁定（别自作主张）

- TLS/HSTS：用户已裁定维持 HTTP，**不要**再提。
- Wave 2 命名空间拆分、API 版本化：V4.0 决策项，本轮不做破坏性重构。
- OJ：已定不挂载服务器（2C2G 不够），代码和表保留。

## 4. 红线与环境坑（违反会出事故）

1. 探测红线：登录失败累计 ≤5 次；禁止全量拉 `/documents`（未分页的旧路径已不存在，但仍别拿 page_size 顶格扫库）；生产出现 5xx 立即停手 15 分钟再观察。
2. 密钥：SMTP authcode、PG 口令只在 `.env`；任何新脚本不得内嵌口令（统一走 `scripts/_conn.py` 或 stdin）。
3. **cookiejar 坑**：`http.cookiejar` 会静默丢弃 domain=`testserver` 显式设置的 Cookie —— 轮换/吊销测试必须用裸 `headers={"Cookie": ...}`（已修，回归时别再改回去，且这两条测试各带「错误消息分支断言 + 阳性对照」防假绿）。
4. 迁移账本：服务器库无账本时 `--all-pending` 会整批 baseline-skip 新脚本 → `push_update.py` 已内置 120 单文件补跑；账本按完整文件名记录，两个 `120_*` 并存安全（先例 112×2）。
5. Git Bash 的 `/tmp` ≠ Windows 临时目录（跨 curl/python 传文件用当前目录）；改 hook 相关环境变量后要重开 shell。
6. 本地 dev 后端在 :8000 后台运行（工作树版）；本地测试库 `kaoyan_test` 每 session drop/recreate，勿连生产库跑测试。
7. **同一工作树有两条工作线**（本 V3.12 线 + 中枢/品牌化线，后者总结在仓库根 `整改与品牌化交付总结_2026-11-21.md`，其前端验收 88/88）。暂存区是共享的——提交前先 `git status` 复核，勿把对方半成品 reset 掉。

## 5. 文件索引

- 整改主报告：`docs/reports/v312-review-remediation-20261121.md`（§8 已含公网抽验，§9 已记 TLS 裁定）
- 变更清单：`CHANGELOG.md` [Unreleased]（Security/Changed/Added 已更新）
- 用户管理界面规格：`D:\桌面\用户管理界面.md`；总方案：`D:\下载\考研平台整合落地方案.md`；零散参考：`D:\桌面\零散方案参考.md`
- 部署/加固：`deploy/push_update.py`、`deploy/harden_20261121.py`、`deploy/reset_account_b.py`、`deploy/monitor_kaoyan.py`
- 关键测试：`backend-main-fastapi/tests/test_auth.py`（轮换/吊销含阳性对照）、`test_email_auth.py`、`test_document_file_stream.py`、`test_subject_vocab_alignment.py`、`test_api_contract.py`、`test_frontend_api_surface.py`
