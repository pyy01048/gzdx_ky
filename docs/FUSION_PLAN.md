# 考研备考平台 · 双方案融合实施方案

> 生成日期：2026-08-30（v2 已按用户"确认版需求+从零到一落地流程"修订）
> 适用范围：`kaoyan-study-platform/`（总目录） 由 现有 React 工程（kaoyan-agent-app） 与 参考项目（kaoyan-app FastAPI+SQLite） 融合而来

---

## 〇、最终确认版业务需求（用户确认）
1. **总体**：融合两工程。FastAPI 为唯一主业务后端，Express 仅做 CodeBuddy Agent SSE 流式代理；淘汰 localStorage 假数据，全部真实入库、真实识别、真实检测；三端响应式 PWA。
2. **驾驶舱**：移除硬编码分科阶段堆砌；目标分/当前分可手改；院校全量+专业自定义录入供 AI 推荐；精简过长蓝色 UI；第三方平台接口状态卡片+添加跳转按钮+实时监测异常提醒；今日任务看板、学习统计、薄弱项预警。
3. **任务**：阶段自定义（不强制固定四阶段）；任务列表自定义模板；AI 每日计划必须读历史任务+本地教材文档作上下文，禁止凭空生成；打卡/复盘/进度。
4. **刷题中心（新增页）**：科目/题型/章节动态联动筛选实时刷新；后端读题库；顺序/随机/专项/模考模式。
5. **错题本**：与刷题中心打通可看题库原题详情；错题回顾提醒；OCR 上传图片识别录入；AI 错题精讲（基于自有资料不幻觉）；SM-2 间隔重复；错误原因标签。
6. **AI 助手（重构废弃静态 AI 注释页）**：参考豆包对话界面；全局底层 AI 能力全页面可调用（任务文档解析/错题 OCR/计划生成/知识点讲解）；多 AI 服务商切换。
7. **文档查看（新增页·知识库）**：PDF/Word/Markdown/TXT 多格式预览；笔记编辑修改；解析脚本持久化文件、结果写 SQLite；AI 分类开关、手动扫描优先、AI 分类压低频次省 Token；预留深度学习模型接入。
8. **AI 工具箱（改造精简）**：砍冗余，只保留核心考研工具。
9. **平台联动（新增页+驾驶舱卡片）**：可添加百度网盘/Anki/墨墨/B站/XMind/圣才；授权配置；驾驶舱展示连通状态；一键跳转；异常实时提醒；当前优先百度网盘 OAuth。
10. **网盘 Pan**：用 AppID/AppKey/SecretKey 实现 OAuth；生成授权链接、拉取文件列表写库；手动扫描触发同步；AI 分类可开关控制频次；解析脚本落盘入库；预留深度学习点位。
11. **设置**：多 AI 服务商配置面板；连通性一键测试；Token 用量统计；随时切换默认模型；第三方平台凭证管理；遗忘曲线/SM-2 参数；备份配置。
12. **优先级**：P0(刷题+错题/SM-2卡片/三端PWA/主页快捷导航) → P1(AI错题精讲/可视化看板/知识库笔记/每日计划AI升级) → P2(开放API/作文批改长难句/计时模考/背诵音频)。

## 〇-1、技术栈务实化调整（对原方案的修正说明）
| 原方案 | 调整后 | 理由 |
|--------|--------|------|
| ORM：Prisma（SQLite） | SQLAlchemy 2.x（参考项目已验证） | Prisma 无 Python 官方成熟客户端，FastAPI+SQLAlchemy 生态成熟、参考项目现成可复用 |
| 校验：Zod | 后端 Pydantic v2（FastAPI 内置）、前端 TS 类型 | Zod 仅用于 Express/前端场景 |
| 日志：Winston | Express 用 Winston；FastAPI 用 logging+RotatingFileHandler | 按进程分 |
| 异步任务：BullMQ | 优先 FastAPI BackgroundTasks / APScheduler 轻量调度；预留可替换 BullMQ | BullMQ 需 Redis，2核2G 单机自用偏重；先轻量后扩展 |
| Docker + docker-compose | 提供 docker-compose.yml 与 Dockerfile（可选用），本地直接跑 | 个人自用本地跑优先 |

## 〇-2、落地目录（feature-first）
```
kaoyan-study-platform/
├── frontend/                     # 现有 React 工程迁移到此
├── backend-agent-proxy/          # Express 仅 CodeBuddy Agent SSE 流式转发
├── backend-main-fastapi/         # FastAPI 主业务后端（routers/services/models 移植）
└── docker-compose.yml / README.md
```
说明：为保证"现有已验证 React 工程"不被破坏，先**复制** kaoyan-agent-app → frontend/ 作为基座，原地小步改造；参考后端整体**复制**到 backend-main-fastapi/，先跑通再按 feature 细化。

---

## 一、现状诊断

### 1.1 当前 React 工程（kaoyan-agent-app）
- 前端：Vite + React 18 + Zustand（localStorage 持久化）+ HashRouter，档案纸美学，明/暗双主题，三端响应式
- 页面：Dashboard / Tasks / Pomodoro / Schedule / Notebook / Assistant / Pan / Words / Cards / Settings
- 后端：Express + TS，仅提供 CodeBuddy Agent 流式对话 + 百度网盘 OAuth 代理 + 学习数据快照
- **根本缺陷**：全部业务数据来自 `src/store/useStore.js` 的 SEED 静态示例数据，页面"看着有数据，实际是假的"，无法真实识别与检测；无真实题库、无院校库、无文档解析入库、网盘靠前端手填。

### 1.2 参考项目（kaoyan-app）
- 后端：FastAPI + SQLAlchemy + SQLite，**真实数据库**，完整 REST 接口
  - 模块：dashboard / tasks / quiz（题库+刷题+提交判分+自动收错题）/ errors（错题本+OCR+AI精讲）/ goals（目标+院校搜索+AI备考策略）/ flashcards（SM-2 卡片+艾宾浩斯）/ documents（上传+解析+知识点+生成题目）/ netdisk（百度网盘 OAuth+文件列表+手动同步+自动分类+平台配置+连接测试）/ ai（多服务商 CRUD+统一对话+作文批改+长难句+计划生成+真题规律）/ customization（快捷链接+系统设置）
  - services：ai_service（豆包/DeepSeek/通义/OpenAI/Claude 多服务商降级）、netdisk_service、ocr_service、review_scheduler（间隔复习调度）
- 前端：Vue3 + Element Plus + Pinia（作为功能参考，**不直接移植**，仅移植接口能力到 React）

### 1.3 用户核心诉求（本次融合必须解决的）
| # | 诉求 | 对应解决方案 |
|---|------|--------------|
| 1 | 大量界面静态、数据虚假 | 引入真实后端（SQLite），所有页面改真实 API 数据 |
| 2 | 仪表盘目标分/当前分可自改 | Goal 表支持任意字段编辑，前端可编辑 |
| 3 | 院校选择需全量+专业自定义 | University 表扩充 + 自定义专业，供 AI 推荐 |
| 4 | 任务阶段自定义、任务列表可自定义 | Task 增加 stage 自定义 + 任务模板自定义 |
| 5 | AI 每日计划基于历史任务与教材 | ai/generate-plan 结合任务库+文档知识库生成 |
| 6 | 刷题题型选择动态联动题目列表 | Quiz 接口支持 subject/chapter/difficulty 筛选 |
| 7 | 错题本/刷题需接口查题库详情 | errors 关联 quiz questions，详情接口 |
| 8 | AI 注释界面参考豆包重做 | AI Assistant 改为对话式（参考豆包），去掉无效页 |
| 9 | 新增文档查看界面（多类型+笔记书写） | Documents 接口 + 前端查看/笔记 |
| 10 | AI 工具箱大改去冗余 | AITools 精简为：作文批改/长难句/错题精讲/计划生成 |
| 11 | 平台联动：多平台+主页接口展示+实时监测 | PlatformConfig 多平台配置 + 连接测试 + 主页卡片 |
| 12 | 网盘动态实时获取、脚本入库、手动扫描分类 | netdisk 服务 + 识别脚本写入数据库 + 手动 sync |
| 13 | 结合 Core 功能优先级清单 | 按 P0/P1/P2 分阶段落地 |
| 14 | 融合 TRAE 参考项目方案 | 以上全部 |

---

## 二、融合架构决策

### 2.1 技术基座
```
前端（保持当前 React 工程）
  ├─ src/store/useStore.js   → 保留为 UI 状态，业务数据改由 API 层拉取
  ├─ src/api/                → 新增 API 客户端（对接 FastAPI）
  └─ src/pages/*             → 逐页改造为真实数据驱动

后端（引入参考项目 FastAPI 能力）
  ├─ backend/                → 从参考项目移植 FastAPI + SQLite
  │    ├─ main.py            → 挂载全部 router，启动建表 + 种子数据
  │    ├─ models.py          → Goal/University/Task/QuizQuestion/ErrorRecord/
  │    │                       Flashcard/Document/NetdiskFile/PlatformConfig/AIProvider/
  │    │                       CustomLink/StudySession/StudyStats/KnowledgePoint
  │    ├─ routers/           → dashboard/tasks/quiz/errors/goals/flashcards/
  │    │                       documents/netdisk/ai/customization
  │    └─ services/          → ai_service/netdisk_service/ocr_service/review_scheduler
  ├─ server/                 → 保留 Express 仅作 CodeBuddy Agent 流式代理（HTTP 转发给 FastAPI）
  └─ 部署：2核2G → FastAPI(uvicorn) + SQLite + 前端静态构建产物
```

### 2.2 前后端通信
- FastAPI 默认端口 `8000`，CORS 全开
- React 前端通过 `src/api/` 统一请求层访问 `http://<host>:8000/api/...`
- Express 的 CodeBuddy Agent（端口 `3001`）保留为 AI 助手引擎，DeepTools 等 AI 功能可走 Agent 或 FastAPI /api/ai
- 开发期 Vite 代理 /api -> 8000 与 /agent -> 3001 分离；生产期静态产物由 FastAPI 托管

### 2.3 数据模型映射（参考项目 models.py）
| 领域 | 表 | 说明 |
|------|-----|------|
| 目标 | Goal | 考试日期/总分目标/各科目标/院校/专业/备注（均可编辑） |
| 院校 | University | 全量院校库：名称/类型/城市/专业/分数线/报录比/难度 |
| 任务 | Task | 标题/科目/类型/阶段(可自定义)/状态/优先级/截止/艾宾浩斯复习 |
| 题库 | QuizQuestion | 题干/选项/答案/解析/科目/章节/知识点/难度/来源/题型 |
| 错题 | ErrorRecord | 关联题目/我的答案/正确答案/错误原因/科目/掌握度/复习调度/标签 |
| 卡片 | Flashcard | 正面/背面/知识点/艾宾浩斯 SM-2 调度 |
| 文档 | Document | 文件名/类型/路径/解析状态/知识点数/笔记 |
| 网盘 | NetdiskFile | 网盘文件 fs_id/名称/路径/类型/分类/播放进度 |
| 平台 | PlatformConfig | 平台名/凭证/同步开关/上次同步/扩展字段 |
| AI | AIProvider | 服务商/地址/模型/密钥/默认/降级优先级 |
| 链接 | CustomLink | 主页快捷导航 |
| 统计 | StudySession / StudyStats | 学习时长/趋势 |

### 2.4 页面融合矩阵
| 当前 React 页面 | 融合后数据源 | 改造点 |
|----------------|--------------|--------|
| Dashboard | /api/dashboard + /api/netdisk/platform-configs | 倒计时/今日任务/统计/薄弱预警；平台卡片+添加按钮；目标分可编辑 |
| Tasks | /api/tasks + /api/tasks/ai-generate | 阶段自定义、任务模板、AI 计划（基于历史任务） |
| Pomodoro | 保留本地 + /api (StudySession 落库) | 学习时长上报真实统计 |
| Schedule | 保留本地课程表 | 可扩展为接口 |
| Notebook（错题本） | /api/errors + /api/quiz/questions | 真实错题、题库详情、错题回顾提醒、AI 精讲 |
| Assistant（AI 助手） | Express Agent + /api/ai | 豆包式对话界面重构，去无效页 |
| Pan（网盘） | /api/netdisk | OAuth 授权、手动 sync 入库、分类、播放 |
| Words | 保留本地 SM-2 | 可对接 /api/flashcards |
| Cards | /api/flashcards | 艾宾浩斯复习 |
| Settings | /api/settings + /api/ai/providers | AI 服务商管理真实化 |
| **新增** 刷题中心 Quiz | /api/quiz | 题型/科目/章节动态筛选题目列表 |
| **新增** 文档查看 Documents | /api/documents | 多类型查看+笔记书写 |
| **新增** 平台联动 Platforms | /api/netdisk/platform-configs | 多平台配置+连接测试+主页卡片 |
| **新增** AI 工具箱 AITools | /api/ai | 精简为四个核心功能 |

---

## 三、分阶段实施计划（按用户优先级清单）

### Phase 1 — P0 核心必做（先落地）
1. 移植 FastAPI 后端至 `output/kaoyan-agent-app/backend/`，跑通数据库建表 + 种子数据 + 全部接口
2. 前端新增 `src/api/` 请求层，Dashboard 接入真实数据（倒计时/今日任务/统计/平台卡片）
3. 目标设置：院校全量库 + 专业自定义 + 目标分/当前分可编辑
4. 任务管理：阶段自定义 + 任务模板 + 列表自定义
5. 新增刷题中心：题型/科目/章节动态筛选 → 题目列表联动
6. 错题本接入真实接口 + 题库详情 + 错题回顾提醒
7. 网盘：OAuth 授权 + 手动同步脚本入库 + 手动分类（防 token 消耗）

### Phase 2 — P1 进阶提效
8. AI 每日计划（基于历史任务 + 知识库教材）
9. 错题 AI 精讲 + 知识点答疑（/api/errors/{id}/ai-analyze）
10. 学习数据可视化看板（驾驶舱统计/趋势）
11. 个人知识库：文档上传 + 解析入库 + 笔记书写 + 查看

### Phase 3 — P2 扩展可选
12. API 开放（Key 鉴权）
13. AI 作文批改 / 长难句分析（AITools）
14. 模拟考场计时模考
15. 背诵音频生成（文本转语音缓存）

### Phase 4 — 深度学习接入预留
- netdisk 识别脚本已结构化入库（NetdiskFile 表），后续替换为本地/云端深度学习分类模型
- documents 解析预留 KnowledgePoint 抽取接口，可升级为 RAG 向量检索

---

## 四、关键技术要点

### 4.1 网盘（防 token 消耗）
- OAuth 授权一次拿 access_token + refresh_token 存库（PlatformConfig）
- **手动扫描**：用户点击"扫描/同步"才调用 `get_file_list`，结果写入 NetdiskFile（fs_id 去重）
- **手动分类**：默认按扩展名/关键词本地规则分类，不调用 AI（AI 分类作为可选开关，避免 token 消耗）
- 文件列表优先读本地库，实时 API 仅在显式刷新时调用

### 4.2 AI 计划生成
- `/api/tasks/ai-generate` 读取 Goal + 未完成任务 + 教材/文档知识库摘要，作为 prompt 上下文
- 输出结构化计划并可直接"导入为任务"

### 4.3 数据库
- SQLite 单文件 `backend/data/kaoyan.db`，2核2G 无压力
- 启动时 `_init_sample_data()` 插入示例院校/任务/题目/错题/平台配置/快捷链接

### 4.4 三端响应式 PWA
- 保持当前 React 的响应式框架与档案纸美学
- build 后由 FastAPI 托管静态产物，PWA manifest 保留

---

## 五、验收标准
- [ ] 所有页面数据来自真实 API，重启不丢失（SQLite 持久化）
- [ ] 仪表盘目标/院校/专业可编辑，倒计时真实计算
- [ ] 刷题选择科目/章节/题型后题目列表实时变化
- [ ] 错题本可查看题库原题与解析，支持 AI 精讲
- [ ] 网盘可授权并手动扫描真实文件入库、可分类
- [ ] 文档可上传解析并查看、书写笔记
- [ ] 平台联动可配置多平台、主页展示接口状态、可测试连接
