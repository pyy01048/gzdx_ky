# 硕途考研平台 · 云端部署 Runbook（2C2G 轻量云端 + 本地算力节点）

> 架构：云端 VPS 跑「Nginx + FastAPI(静态同进程托管) + PostgreSQL16/pgvector」；
> 重算力（PaddleOCR:8888 / bge-reranker:8140 / Ollama:11434）常驻家中 Windows 节点，
> 经 **Tailscale** 内网被云端安全调用。云端不装 paddle/torch/FlagEmbedding/Ollama。
>
> - 云端 VPS：`60.204.223.140`（公网，当前 :80 仍是 Nginx 默认页）· Tailscale `100.72.33.1`
> - 家中算力节点：Windows · Tailscale `100.92.154.42`
> - 目标机：Ubuntu 22.04.5 · 2C/2G · 40G（已配 2G swap）

## 0. 服务器现状（部署前只读勘察结论）
- 已就绪：`nginx`(active, :80)、`postgresql`(active, 仅 127.0.0.1:5432)、`tailscaled`(active, 100.72.33.1)、`certbot`、`swap 2G`、磁盘 25%。
- 未就绪：`/opt/kaoyan` 为空（应用未部署）；无 `node/npm/docker/uvicorn`；系统 Python 3.10（依赖在 3.13 验证过，见 §3 注意）；`ufw` 关闭（依赖云安全组，仅放行 22/80/443）。

## 1. 本包内容（`server-upload/`）
- `backend-main-fastapi/`：后端全部代码 + `static/`（= 前端 `vite build` 干净产物，SPA）。
- `deploy/`：本目录配置与脚本（systemd / nginx / pg / env 模板 / 备份 / 回滚）。
- **不含**：数据、`.env`(密钥)、`node_modules`、`.venv`、日志、上传文件。

## 2. 上传与解包
```bash
# 本地（Windows）已产出：D:\平台\server-upload.tar.gz
scp server-upload.tar.gz root@60.204.223.140:/opt/kaoyan/
ssh root@60.204.223.140
mkdir -p /opt/kaoyan && cd /opt/kaoyan
tar xzf server-upload.tar.gz --strip-components=1 && rm -f server-upload.tar.gz
```

## 3. 系统依赖 + Python  venv + 安装
```bash
apt-get update && apt-get install -y python3.10-venv python3-pip
cd /opt/kaoyan/backend-main-fastapi
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
```
> 注意：需求锁定了 `rapidocr-onnxruntime==1.2.3 + onnxruntime>=1.20`（注释标注为 Python 3.13 组合）。
> 云端为 3.10，若个别轮子无 cp310 预编译包导致安装失败，二选一：
> (a) 用 deadsnakes 装 Python 3.12/3.13 再建 venv；(b) 临时放宽该 OCR 依赖版本（会牺牲云端降级 OCR，重活仍走本地节点，影响有限）。

## 4. PostgreSQL（本机，仅 127.0.0.1）
```bash
# 版本/向量扩展（Ubuntu22.04 默认 PG14；如需 PG16 用 PGDG；pgvector 需对应版本安装）
sudo -u postgres psql -tAc "SHOW server_version;"
sudo -u postgres psql -tAc "SELECT name FROM pg_available_extensions WHERE name='vector';"

# 建库 + 角色 + 向量扩展
sudo -u postgres psql -c "CREATE ROLE kaoyan LOGIN PASSWORD '<强密码>';"
sudo -u postgres createdb -O kaoyan kaoyan
sudo -u postgres psql -d kaoyan -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 建表（走项目 schema，幂等可重跑；见 backend-main-fastapi/core/pg_schema.sql 及其 applier）
cd /opt/kaoyan/backend-main-fastapi
.venv/bin/python -c "<按项目 apply_schema 入口执行建表>"   # 或 psql -f core/pg_schema.sql

# 调小参数（2C2G）：放入 conf.d 后重启
cp deploy/pg-kaoyan.conf /etc/postgresql/<ver>/main/conf.d/kaoyan.conf
systemctl restart postgresql
```

## 5. 环境变量 /etc/kaoyan/backend.env（chmod 600）
按 `deploy/backend.env.template` 填写；密钥现生成：
```bash
install -d -m 700 /etc/kaoyan
openssl rand -hex 32   # → KAOYAN_SECRET_KEY
openssl rand -hex 32   # → JWT_SECRET
# PG_PASSWORD 与 §4 一致；OCR/RERANKER/OLLAMA 指向家中节点 100.92.154.42
```

## 6. systemd 常驻（2 worker，仅本机）
```bash
cp deploy/kaoyan.service /etc/systemd/system/kaoyan.service
# 静态与代码属权交给 www-data
chown -R www-data:www-data /opt/kaoyan/backend-main-fastapi/static
systemctl daemon-reload && systemctl enable --now kaoyan
systemctl status kaoyan
curl -s 127.0.0.1:8000/api/health        # 自检
```

## 7. Nginx（Tailscale 优先，公网门控）
```bash
cp deploy/nginx-kaoyan.conf /etc/nginx/sites-available/kaoyan
ln -sf /etc/nginx/sites-available/kaoyan /etc/nginx/sites-enabled/kaoyan
nginx -t && systemctl reload nginx
# 内网验证（家中/已加入同一 tailnet 的设备）：
curl -sI http://100.72.33.1/             # 应返回前端 index.html
curl -s  http://100.72.33.1/api/health   # 应返回后端健康 JSON
```
> 公网 `60.204.223.140:80` 仍为默认页——**故意不切**。公网放量需先满足上线门控（见 §9）。

## 8. 本地算力节点（家中 Windows，Tailscale 100.92.154.42）
- 安装并登录同一 tailnet 的 Tailscale；三服务**只绑 127.0.0.1/tailscale0**，ACL 仅允许云端访问。
- 常驻：任务计划程序/NSSM 开机自启 `backend-ocr-paddle`(:8888)、`backend-reranker`(:8140)、Ollama(:11434)。
- 三服务加 `X-Service-Token`（与云端 `.env` 的 `SERVICE_TOKEN` 一致）。
- 本地关机时云端自动降级：rapidocr(CPU) / 跳精排或 LLM rerank / 云大模型 / fastembed 小 bge，公网不瘫。

## 9. 公网放量门控（go/no-go，未满足不得对 80/443 开 Web）
- [ ] [11] JWT+RBAC 生效；默认管理员密码已改；管理/备份/采集/训练接口 401/403；生产关闭公开 `/docs`
- [ ] `KAOYAN_SECRET_KEY`/`JWT_SECRET` 固定并异地备份；CORS 仅正式域名
- [ ] 域名 A 记录指向本机 + **ICP 备案通过**（大陆节点；赶时间可用境外节点免备案）
- [ ] HTTPS：`certbot --nginx -d 你的域名`，自动续期验证通过
- [ ] 降级链演练：关掉家中电脑，OCR/精排/答疑/向量仍可用
- [ ] 完成后取消 `nginx-kaoyan.conf` 公网块注释并 `nginx -t && systemctl reload nginx`

## 10. 备份 / 回滚
- 备份：每日 `pg_dump -Fc kaoyan` 加密后同步异地；**同时备份 `/etc/kaoyan/backend.env` 与两个密钥**（否则网盘/AI 凭据不可解）；每月做一次隔离环境 restore 演练。
- 回滚-应用：按 git sha 保留最近 2 版发布目录，`systemctl` 的 `ExecStart` 指回旧版并 `restart kaoyan`。
- 回滚-前端：保留上一份 `static.prev`，Nginx `root` 一键切回。
- 回滚-库：破坏性变更走「扩列→双写→回填→切读→删列」，发布前自动 pg_dump，回滚先恢复快照再回退应用。

## 11. 运维要点
- 监控：外部拨测 `https://域名/api/health`；systemd 存活；内存(<85% 告警)、磁盘(>80%)、swap、证书到期、备份成败；三个算力节点在线灯。
- 日志：journald `SystemMaxUse=200M` + logrotate；关注 5xx/降级/采集失败/AI 失败率。
- 安全基线：主机仅密钥登录、非 root 跑服务（www-data）、及时补丁；CORS 收紧；旁路三端口仅 tailnet/127.0.0.1 + Token。

---

## 附录 B. 2026-10-18 第二轮变更（已同步云端）

**同步到服务器的运行时文件**（tests/scripts 按部署策略不上生产）：
- `services/ocr_router.py`：status 的 label 改走类属性（不再构造 4 个后端对象）；
  router 单例创建即起**后台预热线程**（守护线程，fire-and-forget）；
  `is_available` 加**按后端名探测锁**（预热线程与首个请求不再双重初始化 ONNX 引擎，
  实测竞态 9.7s → 7.9s，稳态 0.01s）。
- `utils/compute_nodes.py`：算力节点探活**并行化**（ThreadPoolExecutor）+ connect
  收紧 1.5s + `COMPUTE_PROBE_TIMEOUT` 环境变量可调总超时。
- 删除服务器 `/opt/kaoyan/backend-main-fastapi/alembic.ini`（死配置，url 还是 sqlite）。

**本地侧资产**（未上传，随下轮发布带上）：
- `tests/conftest.py`：`db_schema` 改 session 级 autouse（测试库与生产同构）。
- `scripts/project_healthcheck.py`：新增「运行时无盘符字面量路径」门禁（26 项全 PASS）；
  CREATE TRIGGER 幂等判定改为认 `DROP TRIGGER IF EXISTS` 守卫。
- `requirements.txt`：`httpx>=0.27,<0.29`；删 `ollama` 包（无 import，且强拉 pydantic≥2.9 冲突）。

**验证**：全量 pytest 980+ passed / 7 skipped / 1 xfailed（契约测试满载计时偶发，
对应路由预算已按同类惯例放宽：`/api/kb/ingest/status` 25s、`/api/admin/system/compute-nodes` 15s）；
前端 vitest 358/358；healthcheck 26/26。

---

## 附录 C. 2026-10-18 公网开放（个人使用决策，已生效）

**用户决策**：暂不备案、暂不上 HTTPS，个人使用，直接开放公网 IP 登录。

**开放前校验（全部通过才执行）**：
- `AUTH_ENABLED`/JWT 双 token 生效：未带 token 请求 `/api/documents` → **401**
- 登录页可达（200）；`JWT_SECRET`/`KAOYAN_SECRET_KEY`/`ADMIN_INITIAL_PASSWORD` 均已设置
- 管理员首登强制改密机制在位

**执行的变更**（本地 `deploy/nginx-kaoyan.conf` 已同步为同一版本）：
1. 站点改为 `listen 0.0.0.0:80 default_server;` + `[::]:80 default_server;`，
   `server_name 100.72.33.1 60.204.223.140 _;` —— 内网与公网同一站点
2. 禁用 nginx 默认欢迎站点（备份在服务器 `/root/nginx-default.bak`）
3. 新增登录路径限流：`location ~ ^/api/(auth|users)/(login|register|refresh)`
   burst=3（应用层已另有登录限流，双保险防公网爆破）

**公网验证（从外网直连 60.204.223.140，实测）**：
- `/` → 200（title：硕途 · 考研学习平台）
- `/api/health` → ok，db healthy，pgvector-hnsw
- `/api/documents`（无 token）→ 401  ← 鉴权生效，公网不裸奔
- `/login` → 200；安全响应头齐全

**已知情残留风险**（个人使用场景接受，将来域名备好案后按附录 B 的
HTTPS 块一键升级）：HTTP 明文传密码（建议 20 位以上强密码）；
大陆节点未备案，云厂商/运营商可能干扰 80；IP 非固定。

---

## 附录 D. 2026-10-18 修复「登录后进不了主页」（真实缺陷，已上线）

**症状**：密码正确、登录接口返回 200，但卡在登录页/进不了主页。

**根因（双重）**：
1. ~~nginx 限流误伤 refresh~~（附录记录已修，非本项）；
2. **真凶：网盘授权失效返回 401，与 session 过期撞码**。首屏 hydrate 会顺带拉
   `/api/netdisk/files`；未绑定百度网盘时后端按设计返回 401 + action=reauthorize，
   前端 request 层对 401 执行「刷新 token 后重试」的全局 session 修复：
   refresh 200 → 重试 → 再 401 → `auth:required` 事件 → AuthContext 置 anon →
   **整个应用被踢回登录页**。nginx 访问日志实证：login 200 → netdisk 401 ×2 →
   refresh 200 → 再无后续请求。

**修复（三处 + 回归测试）**：
- 后端 `routers/netdisk.py`：授权失效 401 → **409** + `code=NETDISK_AUTH_EXPIRED`
  + `action=reauthorize`（409=资源状态冲突，不再被 session 机制误消费）；
  404/502 映射不变。
- 前端 `pages/Pan.jsx`：授权失效判断改为 `e?.data?.action === 'reauthorize'`
  （兼容旧 401）。
- 前端 `api/client.js`：新增 `NO_REFRESH_PREFIXES=['/netdisk/']`——整域 401
  都不触发全局 session 修复（防御未来其他第三方 401 来源）。
- `tests/test_netdisk.py` 新增 `TestHttpErrorMapping`（4 例）：授权类必须 409、
  不存在类必须 404、网关类必须 502——锁死状态码语义，防回归。

**浏览器实测（Playwright 无头 Chromium，公网 60.204.223.140）**：
- 登录 → 强制改密 → 主页 `/#/` 全流程走通；
- 主页完整渲染：导航 3 组、17 张卡片、考研倒计时 62 天、今日任务/周报/学习工作台；
- `/api/netdisk/files` → **409**，用户**留在主页**（修复前会被踢回登录页）；
- 无 console 错误、无页面异常（两条 401 是 anon 状态正常探测）。

**验证基线**：后端 pytest 33 passed（netdisk）；前端 vitest 358/358
（注意：与 pytest 全量并行跑会因负载出现假性超时失败，需串行）。

## 附录 E. 2026-10-18 修复「科目管理删除科目无效」+ 全功能写路径巡检

**症状（用户实测）**：设置页删除内置科目（如「中医综合」）→ 接口返回 200「科目配置已删除」，
但刷新列表该科目又回来（假成功）。

**根因**：`services/taxonomy.py::ensure_subject_config_seeds` 采用「按缺失补齐」：内置科目
（ALL_SUBJECTS = CORE+MAJOR+EXT+CROSS）被删后，下一次 GET /api/taxonomy/subjects 触发列表构建 →
该函数判定科目「缺失」→ 重新 INSERT。该函数的 docstring 声称「不会复活用户删掉的行」——
承诺与实现不符，且无测试守护。

**修复（墓碑机制）**：
- 新分片 `core/sql/106_subject_removals.sql`：建 `subject_removals(subject PK, removed_at)` 墓碑表；
  已接入 `core/pg_schema.sql`（`\ir sql/106_subject_removals.sql`）。
- `services/taxonomy.py`：新增 `load_subject_removals / mark_subject_removed / unmark_subject_removed`，
  `ensure_subject_config_seeds` 播种前跳过墓碑；表不可读时安全降级（返回空集，不 500）。
- `services/subject_registry.py`：`_seed_missing_engineering_subjects` 同样跳过墓碑。
- `routers/taxonomy.py`：删除/改名（旧名是内置）→ 记墓碑；显式重建（POST）→ 清墓碑
  （墓碑只挡自动补齐，不挡用户主动加回）。

**验证**：
- 本地：`tests/test_taxonomy_subjects.py` 新增 `test_delete_builtin_not_resurrected`
  （删→查不复活、显式播种不补回、显式重建可加回、测试自清理）；
  全量 taxonomy/subject/goal 相关 96 passed；healthcheck 27/27（含「所有 SQL 分片被引用」）。
- 服务器：公网 API 复现——删除「中医综合」后列表 37→36 且不复活；
  复原（清墓碑+GET）后正确回到内置（is_custom=False）。

**写路径巡检（代表性抽样，公网）**：
- 院校增删：POST 创建 200 → DELETE 软删除 200 → DB 确认 `enabled=false & deleted_at 非空`（102 分片软删除列就位）✅
- 网盘账号创建：422（缺字段校验，路由+表+token 加密可达，非 500）✅
- 试卷保存：400（score 检查约束，路由+表可达，非 500）✅

**安全加固（2026-10-18 续）**：上条"SQL+traceback 暴露前端"隐患已修复。
`utils/exceptions.py` 在全局 `http_exception_handler` 统一脱敏含 SQL 标记的 `detail`
（替换为正文"操作失败，请检查输入或稍后重试"，原文写服务端日志），并新增
`SQLAlchemyError` 处理器兜底未捕获数据库异常。单点收敛，覆盖全部 `detail=str(e)` 路由。
回归测试 `tests/test_error_sanitizer.py`（4 passed，直调真实注册处理器）。

**网盘 401/409 契约对齐（2026-10-18 续）**：`routers/netdisk.py` 刻意返回 **409**（非 401），
否则 401 被全局鉴权拦截误判"登录过期"→ 踢回登录页。契约测试与
`test_document_file_stream.py` 曾误登记 401，已对齐为 409 并写明原因。

**清理**：物理删除复现用测试账号 zztest / repro001 / repro002 / adminui01（users 表无外键，安全）；
`uitest01` 此前已不存在。管理员账号仅剩 `pyy`。

## 附录 F. 2026-10-18 写路径深入测试（6 类，E2E 公网验证）

**方法**：临时建 admin 账号 `e2e_test`（PBKDF2 哈希直插 `users` 表，密码用纯标准库生成 +
heredoc 防 shell `$` 展开，规避 `$240000$` 被 bash 当位置参数展开），逐模块打公网 API 验证
「路由可达 + 不 5xx + 副作用真生效」，测完物理删除该账号。

| 模块 | 结论 |
|---|---|
| 题库 CRUD | POST 创建 / PUT 更新**真生效**（入库、列表可查）✅；DELETE 受物理删除保护拦截 |
| 目标/章节 | PUT 科目配置、PUT 届数（exam-calendar）全 **200**，测后还原原始配置 ✅ |
| 组卷 | POST /api/papers/build、/save 全 **200**（save 的 items[].question_id 外键必填）✅ |
| FSRS 复习 | POST /api/review/submit 空库 404「知识点不存在」（预期，非 bug） |
| 代码 OJ | **路由未在 `main.py` include** → `/api/code/*` 全 404/405，功能完全不可用（暂缓挂载，非"坏"） |
| AI 答疑 | POST /api/ai/chat 无 API key → 500（**已脱敏不含 SQL/堆栈**，预期行为） |

**真修复 —— 删题 500 不友好**：
- `routers/quiz.py::delete_question` 调 `require_physical_delete_enabled("quiz_questions")`，
  该闸门默认拦截（防误删真题，有意设计）。但 `PhysicalDeleteBlocked`（继承 RuntimeError）未被专用
  handler 接住，落到通用 Exception 兜底 → 返回 **500"服务器内部错误" + detail.type=PhysicalDeleteBlocked**，
  管理员看不出原因。
- **修复**：`utils/exceptions.py` 注册 `PhysicalDeleteBlocked` 专用 handler → 返回 **403 友好拒绝**
  （"删除保护已启用，设置 KAOYAN_ALLOW_PHYSICAL_DELETE=1 后重试，且需先备份"），保留保护语义、
  不泄露内部类型名。已部署 + `systemctl restart kaoyan`，复验 500→403。
- ⚠️ **决策点**：物理删除保护默认开，管理员**仍无法删题**。是否开放（设 env）或提供软删除
  （`quiz_questions.is_available` 已存在该字段）替代，需产品决策。

**OJ 决策点**：`code_oj` 未挂载是「2C2G 不挂载判题引擎，暂缓」的有意状态。是否 include 启用需用户决策
（且判题引擎本身未挂载，include 后 submit 仍会因引擎缺失失败）。

**回归**：全量 pytest 994 passed / 3 skipped / 1 xfailed，0 failure；healthcheck 27/27。
