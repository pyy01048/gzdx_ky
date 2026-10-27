# B-auth 核验报告：登录与权限实现程度（后端 backend-main-fastapi/ + 前端 frontend/）

核验日期：2026-10-18（只读核验，未运行迁移/服务，未改任何文件；所有密码/密钥值已脱敏）
方法：全仓 grep + 逐文件精读；行号以当日工作区快照为准（核验期间 netdisk.py 疑被并发修改过一次，行号均已二次定位）。结论分级：✅已完成 / 🟡部分 / ❌未做。

> 路径说明：原定输出 `.zwork/plan-gap/B-auth.md` 因平台保留 `.zwork/` 无法写入，改存本文件。

## 总览

| 项 | 结论 | 一句话 |
|---|---|---|
| B1 | ✅已完成（重构换代） | utils/auth.py 已删除，换成 models.User + PBKDF2 + 强制改密；旧全局密码退出机制 |
| B2 | ✅已完成 | /api/auth/* 六端点 + PyJWT HS256 access/refresh 双 httpOnly cookie |
| B3 | 🟡基本完成 | app 级默认拒绝 + 路径分类表；抽查发现 6 个漏配管理守卫的写端点 |
| B4 | ❌未做 | 学习表全部无 user_id、无行级过滤，仍是单用户共享数据模型 |
| B5 | ❌未做（有意不用） | 无 alembic；用 core/sql/ 编号 SQL + create_all，users DDL 在 104/107 |
| B6 | ✅已完成 | /login、RequireAuth/RequireAdmin、cookie 会话 + 401 刷新重试 |

---

## B1 utils/auth.py 与 SimpleAuthMiddleware 现状 — ✅

1. **旧文件已物理删除**。`utils/` 目录现为 access_policy.py / middleware.py / security.py 等，无 auth.py。
   历史证据：`utils/data/logs/app.log.2026-09-01:1307`、`app.log.2026-10-09:172` 等多处堆栈含
   `File "D:\平台\backend-main-fastapi\utils\auth.py", line 53, in dispatch`（旧认证中间件的调度行）；
   2026-10-09 之后的日志不再出现该文件。
2. **SimpleAuthMiddleware 代码零引用**：全后端 `*.py` grep `SimpleAuthMiddleware` 仅命中日志文件，源码无定义无注册。
3. **APP_PASSWORD 单全局密码已退出机制，仅剩文档残留**：
   - 无任何 .py 读取 APP_PASSWORD（唯一命中是生成脚本文案 `scripts/make_bats.py:55`："建议在 .env 里设置 APP_PASSWORD 防止陌生人访问"）。
   - `.env:14/24/26` 仍有相关注释与一个已脱敏的赋值行（遗留，未清理）；
     `.env.example` 已不提 APP_PASSWORD，只保留 `ADMIN_INITIAL_PASSWORD`（:13,16，值脱敏）。
   - 不是"应急后备"：无任何代码路径回退到全局密码。
4. **users 表模型存在**：`models.py:1231-1253` `class User(Base): __tablename__ = "users"`，列含
   `password_hash`（:1236，"PBKDF2 哈希，库内无明文"）、`role`(:1238, "admin | user")、
   `must_change_password`(:1240, "首登/重置后强制改密")、`token_version`(:1243, "会话版本号")、
   `deleted_at`(:1247, 软删除)。注意：User 在根 models.py，**不在 core/models/**。
5. **密码哈希 PBKDF2**：`utils/security.py:47-56` `hash_password` = `hashlib.pbkdf2_hmac("sha256", ..., 240_000)`，
   存储格式 `pbkdf2_sha256$iters$salt$dk`；`:57-66` `verify_password` 用 `hmac.compare_digest`。
   注释明说不选 bcrypt 是为免 2C2G 机器编译依赖（:45-47）。
6. **首登强改**：`utils/security.py:177-186` `current_user` 对 `must_change_password=True` 的用户，
   除 `_PASSWORD_CHANGE_ALLOWED = ("/api/auth/me", "/api/auth/change-password", "/api/auth/logout")`（:170-174）外
   一律 403 + code=PASSWORD_CHANGE_REQUIRED。
   内置管理员：`security.py:347-380` `ensure_bootstrap_admin`（users 空时建 `pyy`/BOOTSTRAP_ADMIN:342，
   密码取 ADMIN_INITIAL_PASSWORD 或随机、仅日志打印一次，必须首改）；启动挂钩 `main.py:404-414`。
7. **遗留第二通道**：`main.py:214-247` 可选 `X-API-Token` 中间件（配 APP_API_TOKEN 才启用），与账号体系并存，属旧机制残余，未与角色打通。

## B2 JWT — ✅

1. **路由齐全**（`routers/auth.py`，prefix /api/auth）：
   `GET /status`(:112-114，返回 mode=account)、`POST /login`(:116-140)、`POST /refresh`(:142-155)、
   `POST /logout`(:156-160)、`GET /me`(:162-165)、`POST /change-password`(:167-183)；
   管理端 `admin_router` prefix=/api/admin/users 且 `dependencies=[Depends(require_admin)]`(:39-40)：
   列表(:205-223)/创建(:226-254)/改角色禁用(:258-286)/重置密码(:289-299)/软删(:309-331)/恢复(:333-363)。
2. **库**：`requirements.txt:10` `PyJWT==2.10.1`；`utils/security.py:27` `import jwt`，HS256（:122,132）。
   非 python-jose、无 passlib/bcrypt 依赖。JWT_SECRET 未配置时从凭据主密钥 HMAC 派生，保证多 worker 一致（:95-108）。
3. **access/refresh 双 token**：`security.py:105-128` access cookie `kaoyan_access` 20min（JWT_ACCESS_MIN:72）+
   refresh cookie `kaoyan_refresh` 14d（JWT_REFRESH_DAYS:73，path=/api/auth:33）；httponly + samesite=strict + secure(https:110-113)；
   同时兼容 `Authorization: Bearer`（:158-162）。token payload 带 `ver`（token_version），改密/重置/禁用/软删自增使旧会话全失效
   （routers/auth.py:176-178, 276-279, 293-296, 322-324；security.py:140-154）。
4. **登录限流**：`security.py:236-305` LoginRateLimiter（进程内滑动窗口；注释自认多 worker 下上限×workers，靠 nginx limit_req 兜底）；
   `routers/auth.py:115-136` 应用，且统一报"用户名或密码错误"防账号枚举（:130-136）。
5. 审计：用户管理全操作写 AuditLog（`core/models/schools.py` 的 AuditLog；routers/auth.py:89-102 `_audit`）。

## B3 RBAC 守卫覆盖 — 🟡（集中式策略，抽查发现 6 个漏网端点）

1. **依赖存在**：`utils/security.py:186-198` `require_admin`（非 admin 403）；`:200-206` `admin_for_writes`
   （共享数据登录可读、写需管理员）。无更细的 require_role——角色模型只有 admin|user（:37-39）。
2. **全局默认拒绝是主闸**：`utils/access_policy.py:5-13` 注释"新加的路由默认也要登录——不靠每个 router 自己记得加 Depends"；
   `main.py:90` `dependencies=[_Depends(enforce_access)]`（app 构造期挂载）。`enforce_access`（access_policy.py:111-120）：
   非公开路径一律先 `current_user`，再按三张表判管理员：
   - `PUBLIC_PATHS`（:16-22）：/api/health、/api/auth/status|login|refresh|logout；其余 /api/* 全要登录。
   - `ADMIN_PREFIXES`（:24-36，全方法）：/api/admin/、/api/backup、/api/storage、/api/quality、/api/model-training、
     /api/kb-import、/api/imports、/api/kb/、/api/performance、/api/netdisk/platform-config。
     全部 5 个 admin_* router（admin_schools:15、admin_netdisk:18、admin_system:7、admin_schools_crawler:19、
     watermark_admin:28）都在 /api/admin/ 前缀内 → 覆盖。
   - `ADMIN_WRITE_PREFIXES`（:38-47）：taxonomy、textbooks、documents、codebank、conflicts、links、settings、/api/ai/providers。
   - `ADMIN_ENDPOINTS`（:49-85，方法+路径模板 30+ 条）：quiz 题目 CRUD/导入/抽知识点/batch-delete、papers save+delete、
     kaoyan notices/crawl、spider/run、collection/runs|refresh、reforms/scan、crawl-targets toggle|bulk|reset、
     notice-alert classify|backfill|scan|import|import/batch、notices/backfill-important、
     netdisk test-connection|classify|ingest|files/{id}/ingest|ingest-all、qa import-qbank|refresh-weak|review-queue/{id}/resolve。
3. **抽查后判定仍未挂管理守卫的管理/破坏性写接口**（登录普通用户即可调用）：
   | # | 端点 | 位置 | 性质 |
   |---|---|---|---|
   | 1 | POST /api/errors/batch-delete | routers/stats_export.py:141-149 | 硬删 ErrorRecord ≤500 条；ADMIN_ENDPOINTS 只有 /api/quiz/batch-delete，漏了 errors |
   | 2 | POST /api/quiz/review/{question_id} | routers/quiz.py:1559-1577 | accept 改共享题目科目/题型/知识点、reject 置 is_junk；题目 CRUD 均为管理端点，复核动作漏配 |
   | 3 | POST /api/netdisk/sync | routers/netdisk.py:318-324 | 拉网盘文件入库，写共享 NetdiskFile/Document |
   | 4 | POST /api/netdisk/logout | routers/netdisk.py:499-505 | 清除**共享**百度网盘授权 token，影响全体用户 |
   | 5 | POST /api/netdisk/refresh-token | routers/netdisk.py:109-114 | 刷新共享网盘 token |
   | 6 | POST /api/netdisk/callback | routers/netdisk.py:119-127 | OAuth 回调写共享 PlatformConfig 凭据 |
   （另：GET /api/netdisk/platform-configs 对普通用户可读，但 `netdisk.py:812` `_strip_remote_secrets` 已脱敏下发，风险低。）
4. **行为有测试背书**：`tests/test_auth.py`（约 380 行）覆盖：未登录 401（:129）、普通用户 403（:147,208）、管理员 200（:161）、
   创建用户首登强制改密（:119,179,303）、重置密码（:193,232）、最后一个管理员保护（:212-213）、软删/恢复/用户名占用（:324-384）、
   审计落库（:235-236）。前端 `frontend/src/test/auth.guard.test.jsx` 覆盖 RequireAuth/RequireAdmin。

## B4 数据隔离 — ❌（架构性未做：单用户共享数据 + 少量例外）

1. **根 models.py 全部 48 个 ORM 类无一含 user_id 列**（grep `user_id|class \w+\(Base\)` 于 models.py 仅命中类定义行）。
2. 抽样核对（模型定义 → 结论）：
   | 表 | 定义 | user_id | router 过滤 |
   |---|---|---|---|
   | goals | models.py:121 | ❌ | 无 |
   | tasks | models.py:190 | ❌ | 无 |
   | error_records | models.py:309 | ❌ | 无（errors.py 全量 CRUD；stats_export.py:141 批量硬删也不分人） |
   | study_sessions | models.py:357 | ❌ | 无 |
   | flashcards | models.py:674 | ❌ | 无 |
   | word_decks / words | models.py:890 / 906 | ❌ | 无 |
   | review_schedules | models.py:156 | ❌ | 无 |
   | study_stats / study_events | models.py:873 / 1115 | ❌ | 无 |
   | quiz_sessions / quiz_attempts | core/models/quiz_sessions.py:17 / 71 | ❌ | 无 |
3. **过滤机制层面**：`routers/` 下 `Depends(current_user)`、`request.state.user` 仅 auth.py 自身使用（grep 证据）；
   `enforce_access` 只做"认证 + 管理员判定"，不做行级 scope。即任何登录用户读写全部学习数据。
4. **例外（部分接线）**：
   - 网盘三表 `third_party_accounts` / `preview_sessions` / `netdisk_operation_log`：`core/models/netdisk.py:23/54/70`
     user_id NOT NULL，由 /api/admin/netdisk 按 user_id 增删查（routers/admin_netdisk.py:49-316）；
     但**用户态** /api/netdisk/* 用共享凭据 `PlatformConfig(platform_name="baidu_netdisk")`
     （services/netdisk_service.py:416-421），与 per-user 账号表不挂钩。
   - `PaperAttempt.user_id`：core/models/questions.py:212，注释"用户 ID（预留多用户扩展）"——列在、无人写入。
   - `CodeSubmission.user_id`：core/models/code_oj.py:77 可空；router 以 query 参数收 user_id（routers/code_oj.py:74），
     且 code_oj 整体未挂载（main.py include 段注释："代码上机 OJ 暂不挂载"）。
5. **设计声明（文档自认单用户，但已过期）**：`routers/notices.py:5-9` "真库无 users 表、models.py 无 User 模型、
   无认证中间件（已核实）→ 单用户设计：is_read/is_starred 落在 kaoyan_notices 列上"；
   `services/kaoyan/notice_read.py:9-13` 同口径（"建 user_id 列只会引入恒为 1 的列，纯属无收益复杂度"）。
   前半句与 models.py:1231 现状**矛盾** → 注释过期；后果：通知已读/加星是全用户共享状态。
6. 结论：多账号登录已实现，但"谁能看/改哪行数据"完全未隔离；当前靠"用户都是自家人"的前提运行。

## B5 Alembic — ❌（明确不用 Alembic，另一套机制）

1. `alembic/` 目录不存在、`alembic.ini` 不存在（Test-Path 均 False）；requirements.txt 无 alembic。
2. 实际迁移机制：
   - `core/sql/000…107` 编号幂等 SQL（Postgres 方言）；users 表 DDL：`core/sql/104_users.sql:5-22`
     （含 role CHECK :38-39、ix_users_role_active :41），软删除列在 `107_users_soft_delete.sql`；
     `core/models/__init__.py:3` 注明 ORM 分片与 core/sql 一一对应。
   - `migrate.py:1` 自述"轻量数据库迁移入口（SQLite 单文件，无需 Alembic）"（SQLite 补列线，与 core/sql 的 PG 线并存）。
   - 启动兜底：`main.py:406` `Base.metadata.create_all(bind=engine)` + `ensure_bootstrap_admin`。
   - 无 users 表的"alembic 首版迁移"概念——首版即 104_users.sql。
3. 注意：core/sql 需人工/脚本按序执行（启动只 create_all，不跑 104/107 的增量），无版本表记录已应用脚本。

## B6 前端 — ✅

1. **路由**（frontend/src/App.jsx）：`:123` /login（`pages/Login`，懒加载 :60）；`:124` /force-change-password
   （pages/ForceChangePassword.jsx，:16 未登录重定向回 /login）；`:125` `<RequireAuth><AppShell/></RequireAuth>` 包住全部业务路由；
   `:209` /admin 由 `<RequireAdmin><AdminLayout/></RequireAdmin>` 保护；`:126` /403。
2. **守卫**（frontend/src/auth/AuthContext.jsx）：`RequireAuth` :99-107（anon → Navigate /login 带 from；
   must-change → /force-change-password）；`RequireAdmin` :109-113（非 admin → /403，与实测一致）。
   AuthProvider 启动调 `/auth/me` 定状态 loading|anon|must-change|ready|error（:23-40）；
   登录期每 15 分钟主动 POST /auth/refresh 续 cookie（:12-13, 42-51）。
3. **token 存储**：前端不存 token——access/refresh 均为 httpOnly cookie（后端 security.py:117-128 下发），
   前端仅在内存 state 保存 user 快照（AuthContext.jsx:69-77），无 localStorage/sessionStorage 凭据。
4. **401/刷新处理**（frontend/src/api/client.js）：:92-102 refresh 单飞（并发 401 共用一次刷新）；
   :104-110 `NO_REFRESH_PATHS`（/auth/* 四路径）与 `NO_REFRESH_PREFIXES=['/netdisk/']`（:107 注释：2026-10-18 登录后卡死事故——
   网盘授权失效 401 不得触发全局 session 修复；后端对应改为 409，routers/netdisk.py:57-72）；
   :206-215 非 401 业务路径：401 → refresh 成功则原请求重试一次（_retried）→ 仍 401 派发 `auth:required` 事件（AuthProvider 收到即回登录页）；
   :213-214 403 + code=PASSWORD_CHANGE_REQUIRED → `auth:password-change` 事件 → must-change 状态。
5. authApi 封装：client.js:669-677（status/login/logout/refresh/me/changePassword）。

---

## 缺口清单（按优先级）

1. **【B4·架构】行级数据隔离缺失**：全部学习表无 user_id、无查询过滤；errors/flashcards/words/tasks/goals/quiz 等任何登录用户可读写全量数据；
   通知已读态共享。要么补 user_id + 全链路 scope（大工程），要么明确单租户定位并在文档/UI 声明"共用一份数据"。
2. **【B3·配置】6 个漏网管理端点**：/api/errors/batch-delete、/api/quiz/review/{id}、/api/netdisk/sync|logout|refresh-token|callback
   ——建议补进 access_policy 的 ADMIN_ENDPOINTS / ADMIN_WRITE_PREFIXES（改一行表的集中修法）。
3. **【B1/B4·文档】过期注释**：routers/notices.py:5-9 与 services/kaoyan/notice_read.py:9-13 仍声称"无 users 表/无认证中间件"，
   与 models.py:1231 矛盾，误导后续开发。
4. **【B1·清理】APP_PASSWORD 残留**：.env:14/24/26 注释与赋值行（值已脱敏）、scripts/make_bats.py:55 提示文案，均已无代码作用。
5. **【B2·运维】登录限流在进程内存**，多 worker 下阈值放大、重启即清零，依赖 nginx limit_req 兜底（security.py:268-276 自认）。
6. **【B5·流程】core/sql 无执行器/版本表**：启动只 create_all，104/107 等增量靠人工按序执行；若团队预期 Alembic 需先对齐认知。
7. **【功能】code_oj 未挂载**（main.py 注释：判题子进程 2C2G 扛不住）；PaperAttempt.user_id 预留未接线——恢复时需先补隔离。

## 待证项 / 未覆盖

- `server-upload/backend-main-fastapi/`（仓库内另一份后端副本）未核验，疑似部署快照；本报告只覆盖 `backend-main-fastapi/`。
- 未实际运行服务验证 403/401 行为（只读约束）；行为结论以代码 + tests/test_auth.py 断言 + 2026-10-18 dogfood 实测为据。
- nginx 层 limit_req 配置不在本仓库可见范围内，限流兜底实际生效程度待部署侧确认。
