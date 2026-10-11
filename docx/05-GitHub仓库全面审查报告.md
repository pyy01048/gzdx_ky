# GitHub 仓库全面审查报告（pyy01048/gzdx_ky）

> 审查对象：`https://github.com/pyy01048/gzdx_ky`（main 分支，HEAD `218c5a4`）
> 审查时间：2026-10-11 ｜ 审查方式：完整克隆至 `C:\Users\33884\AppData\Local\Temp\gzdx_review` 逐项扫描
> 结论先行：**仓库能跑、有真数据、有测试，但存在 1 个高风险（无鉴权）、4 个中风险（分支分叉、文档垃圾入库、巨型文件、本地与线上不同步）、一批卫生问题**。按当前状态直接部署或交给 GLM 续写都会越写越乱，需要一次结构性治理。

---

## 一、仓库是什么（审查基线）

| 项 | 实际值 | 说明 |
| :--- | :--- | :--- |
| 仓库 | `pyy01048/gzdx_ky` | 就是本地 `D:\平台` 的 origin |
| 规模 | 416 文件 / 9.3MB / 13.8 万行代码 | 前端 99 文件、后端 210 文件、docx 85 文件 |
| 后端 | FastAPI，31 个 router、30+ 个 service | `routers/` 1.3 万行、`services/` 1.3 万行 |
| 前端 | React18+Vite5+Zustand+HashRouter，32 页面+17 组件 | 多个千行级巨型页面 |
| 测试 | 后端 21 个测试文件、前端 5 个测试文件 | 覆盖尚可但前端 e2e 只有 1 个文件 |
| 数据 | **真数据未入库**（.gitignore 挡护良好） | 这是优点，数据库/模型/密钥都没有入库 |

## 二、最严重的问题（按风险排序）

### 🔴 高风险 1：全部 31 个后端路由无鉴权
扫描结果：`routers/` 下 31 个路由文件**全部没有** `Depends(get_current_user)` / 登录依赖（main.py 中 `Depends` 出现 0 次）。
- 这意味着：**任何能访问到 8000 端口的人（局域网内任何设备、公网暴露后任何人）都能调用所有接口**——包括删除题目、修改题库、读写 AI 配置、上传/下载文件。
- 配合 `启动-局域网.bat`（手机可访问、自动放行防火墙），风险被放大：同一 WiFi 下任何人都能读写你的数据。
- **判断**：个人单机自用可以接受，但只要开局域网模式就有实际风险。颠覆性重写的第一优先级就是**加一层简单的口令/Token 鉴权**。

### 🟠 中风险 2：线上与本地已经分叉成两条开发线
- 本地 `D:\平台` 的 git 历史被压成**单个初始提交** `1764f01`（"V11 代码快照"）。
- 远程 `main` 领先本地 2 个提交：`adbafc3`（"V10 择校升级：改考雷达+分数全景+自动调整+通知中心"，+1702 行，**含 `scripts/gh_auth_setup.py` 等新文件**）+ `218c5a4`（docs 标记）。
- 本地 `D:\平台` 工作区还有 **20+ 个未提交的 M/D 文件**（九轮迭代的改动全部未提交）。
- **后果**：线上仓库的内容 ≠ 你本地正在跑的内容。用户看到 GitHub 上"问题太多"，部分原因就是**线上版本比你本地落后/不同**——你本地修好的东西线上没有，线上多出来的东西你本地没见过。
- **需要你决策**：以哪条线为准？建议以本地为准（本地有九轮修复 + 真数据），把线上那 2 个提交评估后合入或弃用。

### 🟠 中风险 3：docx 目录 85 个文件大量"历史垃圾"入库
docx 下实际是：`docx/`（7 文件）+ `archive/`（6）+ `archive/early-probes/`（7）+ `archive/early-probes/docx-images/`（23）+ `archive/superseded-blueprints/`（2）+ `archive/v6.0-superseded/`（18）+ `figures/`（5）+ `images/`（11）+ `_audit/`（6）。
- 这些是 V6/V7 时期的旧报告、探测稿、图片、审计文件——**与当前代码无关的历史包袱**。
- 推上 GitHub 后任何人 clone 都会看到这些过期文档，容易造成误导（用户自己就是被误导者之一）。
- **建议**：docx 保留当前权威 5 篇（README + 00~04）+ 必要的 images，其余历史文件从仓库移除（本地保留或进回收站）。

### 🟠 中风险 4：9 个超长巨型文件（千行级）
| 文件 | 行数 | 问题 |
| :--- | :--- | :--- |
| `frontend/src/pages/Planner.jsx` | 1292 | 页面内塞了计划+日历+复习全部逻辑 |
| `frontend/src/pages/Documents.jsx` | 1236 | 文档库+上传+解析+知识库全部逻辑 |
| `backend-main-fastapi/routers/kaoyan.py` | 1191 | 院校主路由，几乎含所有择校接口 |
| `frontend/src/pages/Quiz.jsx` | 1103 | 刷题主页面（已知历史复杂） |
| `backend-main-fastapi/services/ai_service.py` | 1001 | AI 服务巨石 |
| `frontend/src/pages/KaoyanSchools.jsx` | 989 | 院校列表巨石 |
| `backend-main-fastapi/services/ai_router.py` | 923 | AI 路由巨石 |
| `backend-main-fastapi/models.py` | 888 | 全部 61 表模型挤在一个文件 |
| `backend-main-fastapi/routers/documents.py` | 837 | 文档路由巨石 |

- **影响**：任何 AI（包括 GLM）续写这类文件时上下文窗口被占满，容易"改了 A 漏了 B"；人工 review 也几乎不可能逐行过。
- **颠覆性重写的核心动作之一**：把千行级文件按功能拆成 200~400 行的模块（后端拆 router/service/schema，前端拆页面+组件+hook）。

## 三、中等卫生问题（不致命但必须修）

### 3.1 无前端 lockfile 之外的另一半问题：依赖版本老旧
- `requirements.txt` 用 `==` 锁定（好），但版本偏旧：`fastapi==0.104.1`（2023-11）、`pydantic==2.5.2`、`numpy==1.26.4`——2026 年再看已落后两个大版本，有已知 CVE 修复没吃到。
- 前端 `package.json` 全部 `^` 范围（`echarts ^5.6.0`、`react ^18.3.1` 等），但 **package-lock.json 已入库**——构建实际是可复现的，这是优点；建议保持并定期 `npm audit`。

### 3.2 SQL 拼接风险点 16+ 处
扫描到 `execute(text(f"..."))` 模式分布在 `kaoyan_ext.py:63/66`、`db_optimizer.py:147/156`、`kb_service.py:388/392/396`、`learner_profile.py:178`、`search_service.py:326/349/372` 等。
- 多数是**参数已内联但值来自白名单**或排序字段，未必能注入；但**没有一处做了统一封口**，属于"靠自觉"型风险。颠覆性重写时应统一改为参数绑定或白名单校验。

### 3.3 前端 console.log 残留 13+ 处
`Words.jsx`(4)、`useStore.js`(4)、`Cards.jsx`(2)、`Tasks.jsx`(1)、`EChart.jsx`(1)、`ErrorBoundary.jsx`(1)、`smoke.test.jsx`(1)。线上运行的代码不应带调试输出（尤其 useStore 全局 store 里的）。

### 3.4 TODO/FIXME 38 处
集中在 `quiz.py`（8 处）、`kb_import.py` 等。其中一部分是"已知待办"，一部分是"临时绕过"——需要逐条判定是补做还是删除。

### 3.5 eval/exec/subprocess 23 处
分布在 `migrate.py`、`setup_local_models.py`、`test_merged_model.py`、`check_train_env.py`、`eval_qa_model.py` 等——**全部是训练/诊断/迁移脚本，不是运行时代码**，风险可控；但应明确标注"仅本地开发用"并和运行时服务隔离。

### 3.6 路径拼接 2 处
`tools/create_shortcuts.py:60/61`——桌面快捷方式脚本，用户输入路径拼接，建议用 `Path` 规范化。

### 3.7 `scripts/gh_auth_setup.py` 在仓库里
智谱清言那批提交新增了 GitHub 推送认证脚本（把 PAT 写入 `~/.git-credentials`）。**这个脚本不属于产品功能**，是你（或 AI）为了 push 仓库临时加的，不应留在项目里——它把"向 GitHub 推送"这个开发动作硬编码进了产品仓库。

## 四、智谱清言那批提交（adbafc3）的质量评估——比预期好

我抽读了 `services/kaoyan/score_insight.py`（306 行）：
- **优点**：模块 docstring 写清了三个能力与和既有 recommend 的职责区分；正态置信估计明确标注"估算，绝不冒充精确位次"；数据口径注释专业。
- `reform_detector.py`（291 行）、`KaoyanNotices.jsx`（221 行）、`test_kaoyan_ext.py`（213 行）从规模和命名看是正经实现，且 App.jsx 已注册 3 个新路由（`schools/:id`、`recommend`、`notices`）。
- **结论**：这批提交**质量合格**，可以评估合入本地；但它带进了 `gh_auth_setup.py` 这个"开发工具混进产品仓库"的问题。

## 五、验证与测试现状

| 层 | 情况 | 评价 |
| :--- | :--- | :--- |
| 后端 pytest | 21 个测试文件 | 覆盖良好（quiz/kaoyan_ext/kb_import/agentic/circuit 等都有） |
| 前端 vitest | 5 个测试文件（contract/robustness/smoke/pages.smoke） | 有基础，但缺组件级测试 |
| 前端 e2e | 只有 `e2e/` 1 个文件 | **严重不足**——刷题/择校/AI 三条主链路没有浏览器级回归 |
| 构建 | 前端 build 通过（此前实测） | 正常 |

## 六、颠覆性重写方案（分层，按优先级）

> 原则：**不动真数据、不重写历史、一次只推一条线**（这是本项目反复踩过的坑）。

### P0 · 止血（1 天，必须最先做）
1. **加鉴权**：后端加简单口令（.env 里一个 `APP_TOKEN`，前端首次输入存 sessionStorage，中间件校验；局域网模式必须强制）。全部 31 个 router 挂一个依赖即可。
2. **统一分支**：以本地 `D:\平台` 为准，评估 `adbafc3`（智谱清言那批）后合入或选择性采纳；`gh_auth_setup.py` 移出仓库。
3. **清理 docx 入库垃圾**：仓库 docx 只留权威 5 篇 + 必要图片，历史文件从 git 移除（本地文件保留）。

### P1 · 结构治理（2~3 天）
4. **拆巨型文件**：`kaoyan.py`(1191)、`documents.py`(837)、`ai_service.py`(1001)、`ai_router.py`(923) 按功能拆成 200~400 行模块；`models.py`(888) 按领域拆（quiz/kaoyan/kb/ai）。
5. **前端拆页**：`Quiz.jsx`(1103)、`Documents.jsx`(1236)、`Planner.jsx`(1292)、`KaoyanSchools.jsx`(989) 拆成 页面容器 + 业务组件 + hook。
6. **SQL 统一封口**：所有 f-string SQL 改为参数绑定或白名单；搜索排序字段加枚举校验。

### P2 · 质量硬化（2 天）
7. **清理调试残留**：13 处 console.log、38 处 TODO/FIXME 逐条判定（补做/删除/标注）。
8. **前端 e2e 补齐**：Playwright 覆盖刷题提交、院校筛选、AI 问答三条主链路。
9. **依赖升级评估**：fastapi/pydantic/numpy 升到当前稳定版并跑全量回归；`npm audit` 处理前端告警。

### P3 · 可选增强（按需）
10. 鉴权升级为真正的用户体系（如果你要开放给别人用）——但你的定位是个人备考，口令鉴权足够。

## 七、给 GLM/智谱清言续写的"不再越写越乱"约束（新增）

在你之前那份提示词基础上，**针对这次审查再加 5 条**：
1. **只改被指名的文件**，任何拆分/重构必须先给出"拆分前文件→拆分后模块"映射表经确认后执行；
2. **禁止把开发工具/推送脚本写进产品仓库**（如 gh_auth_setup 这类）；
3. **docx 只维护权威 5 篇**，不再新增/保留历史报告；
4. 每个千行级文件动手前先列"这个文件里有哪些功能"清单，防止漏改；
5. 所有新接口**必须**挂鉴权依赖（除非明确说明是公开接口）。

---

## 附：本次审查扫描命令摘要（可复现）

```
git clone --depth 5 https://github.com/pyy01048/gzdx_ky.git C:\...\gzdx_review
# 规模: 416 文件 9.3MB；敏感文件: 仅 themeTokens.js(误报)
# 鉴权: routers/ 31 文件 Depends 0 次
# 巨型文件: 9 个 >800 行
# SQL拼接: 16+ 处；console.log: 13 处；TODO/FIXME: 38 处
# eval/exec/subprocess: 23 处(均为训练/诊断脚本)
# docx: 85 文件(大量 archive/images 历史垃圾)
# 测试: 后端 21 文件 / 前端 5 文件 / e2e 1 文件
```
