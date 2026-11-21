# V3.12 后台评审整改报告（2026-11-21）

对照《V3.12-后台评审报告-V4.0路线图.md》（加权 ≈3.4/10）与《V3.12-后台测试标准与移交手册.md》（TC-A~J / G1-G12）逐项整改。本报告只记实测数字与可复现证据；部署后复验数据在 §8 追加（append-only）。

## 1. P0 灭火

### B-01 后端整体挂起 / 无快速失败 — 已修复（代码+本地实测，部署待执行）

根因取证（两处事件 loop 炸弹，均在 async def 里跑同步重活）：

| 位置 | 旧行为 | 修复 |
|---|---|---|
| `main.py /api/health` | async def 内同步调 `kb_health_snapshot()`（~10s DB+向量库探测），每次探活阻塞整个 worker 事件 loop；监控/评审高频探活 → 全站假死 | 公开 health 改为零 DB 的 `{"status":"ok","version":...}`；重探测移到 **鉴权** 的 `/api/health/detail`（sync def → 线程池，30s TTL 缓存） |
| `routers/knowledge/documents.py` 列表 | async def 一次性加载 **2666 篇全文**（2.79MB / 8.66s），阻塞 loop | sync def + 强制分页（page≥1，page_size 1~100，默认 20）+ `defer(Document.content)`；摘要/长度改 DB 侧 `length/substr`；facets 用 GROUP BY 聚合（29 组）替代全量拉取 |

本地实测（真实 2666 篇开发库，2026-11-21 02:20）：

- `GET /api/documents?page=1&page_size=20` → **200 · 0.075s · 22.5KB**（评审基线 8.66s / 2.79MB，~115× 提速 / ~124× 减重）
- `page_size=101` / `page=0` → **422**；`/api/textbooks?page_size=5` → 200 · 0.013s · 2KB（total 26）
- `/api/health` → `{"status":"ok","version":"3.0.0"}`（无 git_sha / 库表行数）；匿名 `/api/health/detail` → **401**，管理员 → 200 含 git_sha/kb

nginx 快速失败（`deploy/nginx-kaoyan.conf` 重写，待部署）：普通 API connect 3s / read+send 30s（原 600s 无 fast-fail）；长任务白名单保留 600s（AI SSE / storage 扫描 / netdisk 同步 / kb ingest / documents 批处理正则）。429/502/503/504 一律 JSON 错误壳（原 nginx 默认 HTML 503 是评审「无爆破防护」误判的直接来源）。`server_tokens off`、gzip、X-Request-ID 生成+透传+回写。

守护加固（待部署）：`deploy/monitor_kaoyan.py`（stdlib，每分钟 cron：app 连续 2 次探活失败 → systemctl restart kaoyan + SMTP 告警，30min 冷却；nginx-only 失败 → restart nginx）；systemd 追加 `PYTHONFAULTHANDLER=1`（worker 静默死亡留栈）。既有 MemoryHigh=850M/MemoryMax=1150M/Restart=always 保留。

### B-03 登录响应体明文回传 access_token — 已修复并实测

`_session_payload` 只回 `user / must_change_password / email_verified`；token 单通道 HttpOnly Cookie。本地实测 login 响应体 keys = `['email_verified','must_change_password','user']`，断言 `access_token not in body` 进测试（`test_login_body_carries_no_token`）。refresh 响应同样无 token。

### B-02 全站 HTTP 明文 — 准备就绪，阻塞在用户决策

裸 IP 无法签发受信证书（Let's Encrypt 不支持 IP；大陆节点需 ICP 备案）。nginx conf 已保留一键升级的域名 TLS 块 + 收尾清单（TLS 生效后移除 `COOKIE_SECURE=0` 过渡开关 + 启用 HSTS）。**需用户裁定：是否有域名/是否备案，或改走 Tailscale-only（方案 B，零成本全程 WireGuard 加密）**。历史知情决策（2026-10-18 个人使用暂不备案）已记录在 conf 头部。

## 2. P1 整改

| 评审项 | 整改 | 证据 |
|---|---|---|
| 爆破防护 503 非 429 | 应用层 LoginRateLimiter（5 次失败/300s 窗/900s 锁）本就存在；nginx `limit_req_status 429` + JSON 壳 + `Retry-After`；应用 429 也带 `Retry-After`（login/register/forgot 三处） | `test_login_rate_limit...` 断言 `Retry-After>0`；nginx 部署后复验 |
| /health 泄露 git_sha+库表行数 | 公开 health 零 DB 脱敏；detail 仅管理员 | 上文实测 |
| /documents 无分页 | 强制分页 + 字段裁剪 + facets；管理页需要全量时前端 `documentsApi.listAll` 循环（100/页，上限 100 页） | 上文实测；Library.jsx 服务端分页 + 翻页器 |
| 12/70 端点 404「契约漂移」 | **取证结论：真实漂移 = 0**。12 个路径（/api/cards、/api/notebook、/api/pan、/api/hub/overview、/api/knowledge、/api/insights、/api/subjects、/api/admin/overview、/api/admin/subjects、/api/admin/quality、/api/admin/quiz-bank、/api/admin/model）在 frontend/src 全量 grep **零调用**——评审按页面名猜的 URL。真实调用如 Insights→`statsApi.overview()`、Hub→`tasksApi.*`。T10 反向守卫（224+ 条调用逐条对照 OpenAPI）本轮全绿 | `test_frontend_api_surface.py` passed；grep 证据见 §7 |
| /documents+/textbooks 匿名 200 | **按 2026-11-20 访客扩容决策保留只读公开**（/library、/textbooks 是 public 页面）；写操作全部收敛管理员（见 §3）。信封新增 `"scope":"global"` 显式标注数据归属（评审 B-08 的轻量落地；/api/library/* vs /api/me/* 命名空间拆分属 V4.0 决策项，不盲改） | RBAC 矩阵测试：匿名读 200 / 匿名写 401 / 普通用户写 403 |
| 新用户「数据爆满」 | 根因即全局库被误读为个人数据。scope 标注 + 个人域（/api/tasks 等）保持 401 门控；空态即交付原则不变 | push_update 部署验证同时断言 documents 200 + tasks 401 |
| refresh 无轮换/吊销 | 迁移 120 `auth_sessions` 表：每次登录一行会话（sid），refresh 携带一次性 jti，刷新即轮换；**旧 jti 重放 → 吊销整行 + token_version 自增（全家族失效）**；登出只吊销本会话（其他设备不受影响）；改密/重置/禁用仍全量失效；无 sid 旧 token 14 天过渡放行 | 3 个新测试 + 本地真库实测（§4） |
| 参数边界静默截断 | growth/analytics/analysis 的 days 全部 `Query(ge=1, le=365)` | 实测 days=0/366 → 422，days=30 → 200 |
| /auth/me 无 Cache-Control | 新中间件：/api/auth/* 与 /api/admin/users* 一律 `Cache-Control: no-store` | 实测响应头 no-store |
| 无 X-Request-ID | nginx 生成 `$request_id` → 透传后端 + 回写响应头（全链路） | 部署后复验 |

## 3. 整改中新发现的真洞（评审未点名）

**12 个 documents 写端点完全无鉴权**——匿名可 `DELETE /api/documents/{id}`、触发解析/OCR/标注。已逐个挂 `require_admin`：parse / generate-quiz / DELETE / ocr / analyze / extract-knowledge-points / extract-questions / preview-questions / confirm-questions / classify-chunks / chunks/{id}/label / archive。upload 保持 require_verified_email；parse-all 等批处理原本已 admin。

## 4. 会话安全本地实测（真实开发库，非 mock）

```
login pyy/<凭据仅运行时，不入库> → 200，body 无 token，2 条 HttpOnly cookie
refresh                   → 200，jti 轮换（新旧 refresh 不同）
重放旧 refresh（裸 Cookie 头）→ 401「登录已失效，请重新登录」（重放吊销分支）
随后新 refresh            → 401（家族已吊销）
重新登录 → logout         → 200
登出前窃取的 access 重放   → 401（服务端会话吊销，非仅清 cookie）
```

## 5. 测试与构建（本轮全部实跑）

| 套件 | 结果 |
|---|---|
| tests/test_auth.py + test_email_auth.py + test_document_file_stream.py + test_subject_vocab_alignment.py + test_guest_access.py | **100 passed**（168s） |
| tests/test_api_contract.py + test_frontend_api_surface.py + test_ingest_rename_e2e.py + test_chunk_mirror_sync.py + test_doc_rename_write_through.py | **60 passed, 1 skipped** |
| 前端 vitest 全量 | **50 文件 / 492 passed** |
| `npm run build` | ✓ 5.07s（产物已入 backend static/） |

新增测试：login body 无 token / refresh 轮换+重放灭族 / 登出服务端吊销 / RBAC 越权矩阵（admin-only GET 用户 403 匿名 401、documents 写守卫、访客白名单 200、health 无泄露、分页 422 边界）。

**假绿陷阱（已修并记录）**：`http.cookiejar` 对显式 `domain="testserver"`（无前导点）做严格域匹配会**静默丢 cookie**——重放测试的 401 一度是「没带 token」而非「吊销生效」。改用裸 `Cookie` 头 + 断言错误消息区分分支 + 登出测试加阳性对照（登出前窃取 token 必须 200）。

## 6. 部署清单（待执行，含服务器侧动作）

1. `deploy/push_update.py`（已更新：health 校验改 status/version；迁移 120 单文件补跑兜底——存量库无账本时 --all-pending 会 baseline 跳过新脚本）
2. nginx conf scp → sites-available → `nginx -t` → reload
3. monitor_kaoyan.py → /opt/kaoyan/ + root crontab 每分钟
4. systemd unit 追加 `Environment=PYTHONFAULTHANDLER=1` → daemon-reload
5. **账号 B（id=15，15772585486）密码重置**（新密码经 `ACCOUNT_B_PW` 环境变量 → SSH stdin，**不入库/不落盘**；评审 401 的直接原因；服务器侧执行，token_version 自增）
6. 部署后按 TC 矩阵低压复验（红线：≤5 次失败登录、不拉 /documents 全量、5xx/挂起停手 15min）

## 7. 契约漂移取证命令（可复现）

```bash
# 12 个被评审点名的路径，前端零调用：
for p in cards notebook pan hub/overview knowledge insights subjects \
         admin/overview admin/subjects admin/quality admin/quiz-bank admin/model; do
  grep -n "'/$p'" frontend/src/api/client.js   # 全部空
done
grep -rn "fetch('/api" frontend/src --include=*.js*  # 仅 utils/api.js 的 /api/ai/chat[/stream]，均存在
```

## 8. 部署后复验（append-only）

### 8.1 2026-11-21 公网只读抽验（60.204.223.140）

部署事实：并行「中枢/品牌化」工作流经 `deploy/push_update.py` 将同一工作树推上服务器（本整改集随之上线，`120_auth_sessions` 生效——refresh 路由可达且 500 未现）。当日以只读探针复验：

| 检查 | 结果 |
|---|---|
| GET /api/health | `{"status":"ok","version":"3.0.0"}`，零 DB 探活 ✓ |
| GET /api/documents?page=1&page_size=1 | 200，0.084s，3.4KB（整改前基线 8.66s / 2.79MB 整表）✓ |
| GET /api/documents?page_size=101 | 422 ✓（分页上限已在线上强制） |
| GET /api/health/detail（匿名） | 401 ✓ |
| nginx 层 | `Server: nginx`（server_tokens off）、`X-Request-ID` 每请求注入、CSP Report-Only、`/api/auth/*` 响应 `Cache-Control: no-store` ✓ |
| POST /api/auth/login（pyy） | 200；响应体 `"token"` 出现次数 0（仅 user/must_change_password/email_verified）；Set-Cookie×2：`kaoyan_access` HttpOnly/Max-Age=1200/Path=/、`kaoyan_refresh` HttpOnly/Path=/api/auth，均 SameSite=strict ✓ |
| POST /api/auth/refresh（无 Cookie） | 401 缺失分支 JSON ✓ |
| GET /api/auth/me（带 Cookie）→ POST /api/auth/logout | 200 → `{"success":true}` 200 ✓ |

### 8.2 尚未复验（剩余）

- 限流 429 JSON 壳 + Retry-After 的公网触发（避开登录失败 ≤5 次红线，未主动打满）。
- TC-A~J 全矩阵与 G1-G12 门禁逐条签字、RBAC 越权矩阵公网复验、账号 B 重置后首登。
- `monitor_kaoyan.py` cron 心跳与 systemd `PYTHONFAULTHANDLER=1`（`deploy/harden_20261121.py` 尚未执行）。
- G10 干净 git_sha：本轮变更未提交，生产标识仍 `-dirty`（提交受阻于 pre-commit ruff 存量门禁，修复清单见交接报告 `handoff-cn-20261121.md`）。
- B-02 已按用户裁定关闭：维持公网 HTTP（Cookie 因此无 `Secure` 位，知情决策，见 §9.1）。

### 8.3 2026-11-21 公网 TC 矩阵复验（CN 续测）

只读复验，探针 `D:\研途\.review_evidence\tc_matrix_probe.py`（stdlib urllib、无代理、常规 ≤2 req/s），证据 `D:\研途\.review_evidence\tc_matrix_20261121.json`（260 项：endpoint/method/status/耗时/判定）。红线全程遵守：登录失败 **0** 次（pyy 正确凭据 2 次登录均 200）；documents `page_size≤20`；唯一 burst 用于 429 触发（匿名只读端点）；全程 **0 个 5xx**，未触发停手条款。**账号 B（15772585486）另组重置中，本轮禁测——首登/普通用户越权矩阵（D2/D3）待补。**

**总计：PASS 237 / NOTE 13 / SKIP 8 / FAIL 2**（2 个 FAIL 同根因，见下方新发现 F-1，P3 级）。

| # | 复验项（TC） | 实测值 | 阈值 | 判定 |
|---|---|---|---|---|
| 1 | D1 全端点匿名 GET 矩阵（api_map 208 条，8 条外部 OAuth/凭据类跳过，200 条实测） | 401×97、404×88（POST-only/评审猜测路径，JSON 壳）、200×15 **全部落在访客/公开白名单**（health、auth/status、documents(+subjects)、textbooks×3、kaoyan/schools、taxonomy×4、papers、quiz/papers-index、quiz/years）；受保护端点匿名 200 = **0** | 白名单外 100% 401/403（404/405 无泄露亦计合格） | ✅ PASS |
| 2 | 写端点匿名探测（不执行写） | `DELETE /api/documents/999999999`→**401**；`POST …/parse`（空体）→**401**；`POST /api/documents/ocr`（真实 OCR 写面，空体）→**401**；textbooks 路由仅 GET：OPTIONS/POST/DELETE→405 无写面；`/{id}/ocr` 无 POST 路由→405 | 401（鉴权先行，请求体不处理）；2xx 即红 | ✅ PASS（无 2xx） |
| 3 | 分页/参数边界 | documents `page_size=101`→422、`page=0`→422；textbooks `page_size=201`→422；growth/timeline、analysis/profile、analytics/traces 的 `days=0/366`：匿名 401（门控）→ pyy 会话 **422×6** | 422 | ✅ PASS |
| 4 | health 脱敏 | `/api/health`=`{"status":"ok","version":"3.0.0"}` 无 git_sha/kb/行数；`/api/health/detail` 匿名 **401**、pyy(admin) **200** 含 `git_sha=26b9bdd-dirty` | 公开零泄露；detail 仅管理员 | ✅ PASS（dirty 见 G10） |
| 5 | 限流 429（J1） | 40 请求 burst（8 并发，匿名 `documents?page_size=1`）→ 200×22 + **429×18**；429 体=`{"code":"RATE_LIMITED","message":…,"detail":{"retry_after":1}}`，`Retry-After: 1` | 429 JSON 壳 + Retry-After>0 | ✅ PASS |
| 6 | nginx 头 | `Server: nginx` 无版本 244/244；`X-Request-ID` 244/244；CSP Report-Only 243/244；`/api/auth/*` `Cache-Control: no-store` 25/25；nosniff/XFO 243/244 | 每请求齐全 | ⚠️ 243/244（缺失的 1 个=429 响应，F-1） |
| 7 | pyy 会话链路（C3/C4/C5/C6） | login 200 body keys=`[email_verified,must_change_password,user]`，"token" 出现 **0**；HttpOnly Cookie×2（SameSite=strict，Path/Max-Age 正确）；me 200=pyy/admin；伪造 Bearer→401；refresh 200 **jti 轮换**（新旧 refresh 不同）；**旧 refresh 重放→401「登录已失效」+ 新 refresh 亦 401（家族吊销）**；重登→logout 200→登出前窃取的 access 重放 **401**（服务端吊销，阳性对照登出前 200） | 全链 PASS | ✅ PASS |
| 8 | 数据归属（E3） | documents 信封 `"scope":"global"` ✓；匿名 `/api/tasks` **401** ✓ | scope 标注 + 个人域门控 | ✅ PASS |
| 附 | A1/A2 可用性 | 静态+health 双 200（health 30–68ms）；90s 采样 **6/6=200** | 6/6 | ✅ PASS |
| 附 | G2/G3 性能压缩 | documents 20/页=**5.1KB**，5 样本 63–91ms（P95≈89ms）；`Accept-Encoding: gzip`→`Content-Encoding: gzip` | P95<300ms、<200KB | ✅ PASS（低压抽样，非 20 次基线） |
| 附 | F5/F6 契约 | `/api/openapi.json` 404；未知 `/api/*`→JSON 404（非 index.html） | 404 JSON | ✅ PASS |

**新发现（本轮唯一真实问题，P3）**：nginx `@rate_limited` 命名 location 自带 `add_header`（Retry-After/X-Request-ID），按 nginx 继承规则**不再继承 server 级安全头** → 429 响应缺 CSP-Report-Only/nosniff/X-Frame-Options/Referrer-Policy/Permissions-Policy（244 个响应中仅此 1 个；`@backend_down`/`@backend_timeout` 同理，本轮未触发 5xx 未实测）。JSON 壳与 Retry-After 本身正常。修复：三个命名 location 内补齐安全头或抽公共 include。另记录：POST-only/方法不匹配统一回 404 JSON（非 405），无泄露，仅语义备注。

**G1–G12 门禁逐条**：

- [x] **G3 令牌**：login/refresh body 无 token，HttpOnly Cookie 单通道 ✅
- [x] **G5 越权（匿名面）**：200 路径矩阵受保护端点 0 个匿名 200；documents/ocr 写面匿名 401 ✅（普通用户×admin 403 矩阵**待补**：账号 B 另组重置中）
- [x] **G6 性能**：分页强制（422 边界）+ 5.1KB/页 + P95≈89ms + gzip ✅（textbooks 默认 page_size=100 超 ≤50 口径，但 total=26 响应≈2KB，风险可忽略，备注）
- [x] **G7 契约**：沿用 §2 T10 取证漂移=0；本轮 404 均为评审猜测路径/前端路由，非前端调用 ✅
- [x] **G12 错误处理**：401/404/422/429 全部 JSON `{code,message}`；0 个 5xx、0 个 HTML 错误页 ✅
- [ ] **G1 可用性（部分）**：A1/A2 全绿、0 5xx；故障注入 ≤5s / kill 自愈 ≤60s / 并发 50 压测需服务器权限与授权——**待补**
- [ ] **G4 防爆破（部分）**：nginx 层 429+Retry-After 实测 ✅；应用层 5 次失败锁未公网触发（红线禁止用登录失败打限流）——**待补**
- [ ] **G8 数据初始化（部分）**：scope:global + 个人域 401 ✅；新用户空态 E1 / 账号 B 首登——**待补（账号 B 另线）**
- [ ] **G9 安全头（部分）**：243/244 齐全；CSP 仍 Report-Only（转强制待一周观察）；429 响应缺头见 F-1；HSTS 随 G2 豁免
- [ ] **G10 部署卫生**：实测 `git_sha=26b9bdd-dirty`——**待补/另线处理**（pre-commit ruff 存量门禁，见 handoff-cn-20261121.md）
- [ ] **G11 可观测（部分）**：X-Request-ID 244/244 ✅；monitor_kaoyan.py cron 心跳/告警演练——**待补/另线处理**（harden_20261121.py 未执行）
- [ ] **G2 传输**：**知情豁免**（用户裁定维持公网 HTTP，§9.1；无 TLS/HSTS/Cookie Secure）

### 8.4 第二重独立复验 + 盲点补测（2026-11-21 11:46–11:53，tc-matrix-prober）

与 §8.3 相互独立的第二轮公网复验（探针 `D:\研途\.temp\v312_recheck_probe.py`，httpx，54 请求 = 53 矩阵 + 1 聚焦复核），**0 个 5xx、0 次登录失败**，55 条断言全 PASS。结论与 §8.3 一致（匿名矩阵/RBAC 写面 401/只读路径 405、强制分页 422、gzip、login 无 token 体 + HttpOnly×2 + no-store、logout 吊销、429 JSON 壳 `{"code":"RATE_LIMITED",…,"detail":{"retry_after":1}}` + `Retry-After: 1`、CORS 恶意 Origin 不回显、openapi/未知 API 404 JSON）。证据 `v312_recheck_results.json`（无凭据值）。

**补 §8.3 盲点——refresh 无 Cookie 分支**：§8.3 item7 验的是「带 Cookie 的 jti 轮换 + 旧 refresh 重放家族吊销」，未单测「完全无 Cookie」。本轮聚焦补测：全新无 cookie 客户端 `POST /api/auth/refresh` → **401** `{"code":"UNAUTHORIZED","message":"登录已过期，请重新登录"}` + `Cache-Control: no-store`。缺失分支正确。
> 诚实留痕：探针初版此项误判 FAIL——共享 `httpx.Client` cookiejar 自动带上登录存的 `kaoyan_refresh`（Path=/api/auth），「无 Cookie」名不副实致服务端正确返 200。已修探针（`client.cookies.clear()`）+ 全新客户端聚焦复核取 401 证据。**非服务端回归**。

**F-1（§8.3 唯一真实问题）修复已落代码**：nginx `@rate_limited`/`@backend_down`/`@backend_timeout` 三个命名 location 已补齐 5 项安全头（CSP-Report-Only/nosniff/XFO/Referrer-Policy/Permissions-Policy），解决 location 级 `add_header` 不继承 server 级问题。**待 `nginx -t` 服务器侧校验 + reload 生效**（随 P1 加固）。另 P3①：`RequestTimer` 对外 `X-Process-Time` 头已移除（保留服务端慢请求日志），**待随 P0 提交后重新部署生效**（当前生产仍见该头）。

**G10 复查口径**：两轮均实测生产 `git_sha=26b9bdd-dirty`。干净 sha 需 P0 原子提交 → `gen_version.py` 重新生成 `_version.py` → 重新部署，三步缺一不可；提交本身受阻于 pre-commit ruff 存量门禁（修复清单见 `handoff-cn-20261121.md`）。G1/G4/G8/G11 服务器侧项随 P1 加固一并验收。

### 8.4 2026-11-21 收尾补遗（CN，append-only）

**账号 B 重置 + 首登 + RBAC 矩阵（G5/G8 闭环）**：

- `deploy/reset_account_b.py` 根因修复：脚本从 `/opt/kaoyan/incoming/` 运行时 sys.path[0] 是脚本目录而非 cwd，`from database import ...` 必炸；已加 `sys.path.insert(0, str(Path.cwd()))`（保持 stdin 读密码、不落盘设计）。
- 服务器执行重置成功：`[OK] 账号 B 密码已重置（id=15），旧会话已全部失效`（token_version 自增），脚本已 `shred -u`。
- 首登实测：login 200，body keys=`[email_verified,must_change_password,user]`（无 token），`must_change_password=false`，role=user；`/api/auth/me` 200 且 `Cache-Control: no-store`；logout 200。
- 普通用户×管理员越权矩阵（账号 B 会话，7/7 PASS）：`/api/health/detail`、`/api/admin/users`、`/api/admin/users/roles`、`DELETE /api/documents/{id}`、`POST /api/documents/{id}/parse` 均 **403**；个人域 `/api/tasks` 200；公共库 documents 200。

**F-1（429 缺安全头）根因修复闭环（G9 缺口关闭）**：

- 取证：线上 `/etc/nginx/sites-available/kaoyan` 为旧版（13170B，`@rate_limited` 仅 Retry-After/X-Request-ID），仓库工作树版（15128B）三个命名 location 已含全套安全头——线上与仓库漂移。
- 处置：仓库版重新 sftp 部署 → `nginx -t` 通过 → reload。复测 burst 429：CSP-Report-Only/nosniff/X-Frame-Options/Referrer-Policy/Permissions-Policy/Retry-After/X-Request-ID **7/7 齐全**。`/media/images/` 通路不受影响（不存在路径正确 404）。

**守护链路确认（G11 部分闭环）**：

- monitor cron 每分钟准点（journalctl CRON 条目实证），state 心跳 75s 内推进，`app_fails:0 / nginx_fails:0`，无自愈触发；探活成功静默写 state 属设计行为。
- `systemctl cat kaoyan` 含 faulthandler drop-in（`Environment=PYTHONFAULTHANDLER=1`）；直连 8000 与经 nginx 80 的 `/api/health` 均 200。

**门禁状态更新**：G5 ✅（匿名面+普通用户面全闭环）；G8 账号 B 首登 ✅（新用户空态 E1 仍待产品侧验收）；G9 429 缺口 ✅（CSP 转强制仍待一周观察）；G11 心跳 ✅（告警演练待补）；G1/G4 故障注入/应用层锁定演练、G10 干净 git_sha 仍待补（G10 依赖本轮 git 提交+部署）。

## 9. 未决事项

1. **B-02 TLS**：已裁定（2026-11-21 用户）——维持现状（知情 HTTP），不做 TLS/80→443/HSTS；Cookie 保持无 `Secure` 位。
2. **G10 干净 git_sha**：用户已授权提交；实际提交仍受阻于 pre-commit ruff 存量门禁（105 errors，含 vendored ECDICT Python2 文件解析失败）。修复清单与既有暂存状态见 `handoff-cn-20261121.md` §3-§4。
3. Wave 2 命名空间拆分（/api/library/* vs /api/me/*）与 API 版本化（/api/v1）：V4.0 路线图决策项，本轮不做破坏性重构。
