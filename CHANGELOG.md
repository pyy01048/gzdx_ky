# Changelog

本文件记录每次发布的关键变更。格式参考 Keep a Changelog，版本遵循语义化。

## [Unreleased]

### Security
- V3.12 后台评审整改（报告 `docs/reports/v312-review-remediation-20261121.md`）：登录/refresh 响应体移除明文 token（HttpOnly Cookie 单通道）；refresh 一次性轮换 + 重放灭族 + 登出服务端吊销（迁移 120 `auth_sessions`）；12 个原无鉴权的 documents 写端点（含 DELETE）收敛 require_admin；公开 /api/health 脱敏为零 DB 探活，git_sha/库况移入管理员专属 /api/health/detail；/api/auth/* 与 /api/admin/users* 一律 Cache-Control: no-store；限流 429 + Retry-After（应用与 nginx 双层）
- 升级 fastapi 0.104.1 → 0.115.14（连带 starlette ≥0.40，修复 CVE-2024-47874 multipart DoS）
- 升级 python-multipart 0.0.6 → 0.0.20（修复 CVE-2024-53981 畸形 boundary CPU 空转、CVE-2024-24762 ReDoS）
- 升级 pypdf 4.2.0 → 5.4.0（累积解析死循环/资源耗尽修复，保护上传 PDF 解析入口）
- Pillow 统一取 ≥10.4 安全修复线
- 交付报告凭据脱敏（提交前安全审计）：`handoff-cn-20261121.md` / `v312-review-remediation-20261121.md` 中 4 处明文管理员/账号 B 密码改为「凭据仅运行时持有，不入库」占位（红线 §3.2：口令只在 `.env`/stdin）；全仓 `panyiyun*` 模式扫描归零
- TC-I3 信息泄露修复：移除 `RequestTimer` 对外 `X-Process-Time` 响应头（保留服务端慢请求日志）；nginx 三个命名错误块（`@rate_limited`/`@backend_down`/`@backend_timeout`）补齐 5 项安全头（location 级 `add_header` 不继承 server 级，致 429 响应缺 CSP/nosniff/XFO/Referrer-Policy/Permissions-Policy）

### Changed
- /api/documents 与 /api/textbooks 强制分页（page_size 上限 100/200，越界 422）+ 全文裁剪 + 服务端 facets 聚合 + `scope:"global"` 数据归属标注；实测 2666 篇列表 8.66s/2.79MB → 0.075s/22.5KB。前端 Library 服务端分页翻页器，管理页走 documentsApi.listAll 聚合；growth/analytics/analysis 的 days 参数 ge=1 le=365 越界 422
- nginx 站点配置重写：普通 API 快速失败（connect 3s/read 30s）+ 长任务 600s 白名单；限流拒绝 429 JSON 壳 + Retry-After；server_tokens off；gzip；X-Request-ID 全链路；CSP Report-Only
- 40+ 数据脚本的硬编码数据库口令全部迁移到 `scripts/_conn.py`（唯一连接来源，口令只从 .env 的 PG_PASSWORD 读取）
- 两份 QA 报告中的明文 DSN 脱敏
- TC 矩阵公网复验收尾（54 请求 0 5xx 0 登录失败）：匿名矩阵/RBAC 匿名写/限流 429 JSON 壳+Retry-After/安全头/no-store/HttpOnly/登出吊销全 PASS；修复两处 P3：nginx 命名错误块（@rate_limited/@backend_down/@backend_timeout）补齐安全头（location 级 add_header 不继承 server 级）、移除 RequestTimer 对外暴露的 X-Process-Time 头（TC-I3，保留服务端慢请求日志）

### Added
- `deploy/monitor_kaoyan.py` 服务器探活守护（每分钟 cron：连续 2 次失败自动重启 kaoyan/nginx + SMTP 告警，30min 冷却）；systemd 追加 PYTHONFAULTHANDLER=1
- 守护脚本可靠性加固（SRE 审查后）：monitor 加 flock 单实例锁防并发双重启、restart 超时提至 120s 并捕获 TimeoutExpired（切断「超时→状态不落盘→计数不清零→连环重启」链）、状态原子写（temp+os.replace）、5min 自愈冷却防重启风暴；harden 加 nginx 配置覆盖前备份 + nginx -t 失败自动回滚、faulthandler drop-in 幂等（已存在跳过重启）、crontab 修改前备份
- 会话/RBAC 新测试：login body 无 token、refresh 轮换+重放灭族、登出吊销（含阳性对照）、admin/user/anonymous 越权矩阵、分页边界 422；本轮后端 100+60 passed、前端 492 passed
- 工学学科评估功能上线：分片 119（4 表 2 视图）+ `scripts/import_school_eval_pg.py`（本地/服务器各入库 48 学科 / 329 院校 / 2011 评估 / 179 双一流）+ `/api/kaoyan/school-eval/*` 4 只读端点（访客可读，响应带口径 caveats）+ 前端 `/kaoyan/school-eval` 双视图页面（院校总览 / 按学科选校，joint/institute 分组不混排）；报告见 `docs/reports/school-eval-integration-20261121.md`
- `scripts/sync_quiz_chapter_exercise.py` 章节习题跨库同步（指纹去重只增不改）；810 批次 823 题同步至服务器（含经 subject_config 视图补建 8 科目）
- 外部资产并入 `data-assets/`（题库建设 85 文件 / 08工学数据包 23652 文件 / 工学院校评价库 5 文件，字节级校验；gitignore 不入库，PG 为权威）；外部审计方案 14 篇入 `docs/完善方案/`
- `scripts/_conn.py` 统一连接入口
- `requirements-dev.txt` 开发/测试依赖（本地与 CI 同源）
- pre-commit + gitleaks 提交链路密钥扫描（含大文件 >500KB 拦截）
- LICENSE (MIT + 内容版权声明) / SECURITY.md / CONTRIBUTING.md / dependabot / issue 模板

### Fixed
- 真实缺陷（ruff F823 暴露）：`routers/knowledge/documents.py` 选择题选项清洗分支内重复 `import re` 使 `re` 变为函数局部名，导致其前的 `re.sub(...)` 触发 `UnboundLocalError`（单选/多选选项去前缀必崩）；移除冗余局部 import，复用模块级 `re`
- 契约测试确定性：`tests/conftest.py` 在 import 项目模块前中和环境代理（HTTP(S)_PROXY/ALL_PROXY/NO_PROXY 及小写）。沙箱/CI 注入的 `NO_PROXY` 含裸 IPv6（`::1`）时 httpx `trust_env` 解析抛 `InvalidURL: Invalid port`，把网盘未授权接口本该的 409 打成 500，造成与源码无关的假红；测试网络环境自此确定性等价于生产
- 后端 ruff 门禁清零（本轮待提交文件）：B904 异常链补 `from e`（documents/analytics/auth 共 14 处）、B007 未用循环变量改 `_` 前缀、UP038 `isinstance((X,Y))`→`X | Y`（models 3 处）、E402 刻意中段 import 加 noqa；11 个存量格式漂移文件 ruff format 归一

### Removed
- 解除跟踪：deploy 下 14 个部署 tar.gz、数据库 dump、备份 SQL、调试截图、第三方 vendor 整仓、临时抓取产物

## [0.x] 历史版本

- 路由域化重构 + 13 门类爬虫全量覆盖 + 记忆三层 + 枚举统一（a7f92ea）
- 0854/0855 等学科全量采集、分类归纳层、多 OCR 引擎统一层
