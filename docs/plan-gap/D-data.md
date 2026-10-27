# D 数据冷启动盘点：实测与核验

日期：2026-10-18　仓库：D:\平台　约束执行：全程只读（未写库、未跑导入/清洗脚本、未装依赖、未启动/重启任何服务）
注：任务指定路径 .zwork/plan-gap/ 被平台保留禁写，本报告改放 docs/plan-gap/。

---

## 0. 连库方法（凭证脱敏）

- 连接参数读自 backend-main-fastapi/.env：DATABASE_BACKEND=postgresql，主机 127.0.0.1，端口 5432，库 kaoyan，用户 kaoyan（密码不记录）。
- Python 驱动实测缺失：PATH 上 python 3.13.15 与 D:\Anaconda\python.exe 对 psycopg / psycopg2 的 importlib.util.find_spec 均为 False；D:\Anaconda\envs 目录下无任何环境。requirements.txt:5 声明 `psycopg[binary]==3.2.10`——**声明与当前可找到的解释器不匹配**（后端实际用哪个解释器运行，待证，见 §6）。
- 按预案降级 psql CLI：D:\pgsql\pgenv\Library\bin\psql.exe（路径来自 .env 的 PG_BIN_DIR），单连接一次 `SELECT '表名', count(*) FROM 表 UNION ALL …`（21 张表），`-tA` 纯值输出，只读。
- 连接密码经环境变量 PGPASSWORD 在进程内设置，未落任何文件。

## 1. D1 数据量实测（2026-10-18，kaoyan@127.0.0.1:5432）

| 表 | 行数 | 表 | 行数 |
|---|---:|---|---:|
| subjects | 37 | kaoyan_schools | **0** |
| subject_chapters | 244 | kaoyan_majors | **0** |
| knowledge_points | 500 | kaoyan_scorelines | **0** |
| quiz_questions | **0** | kaoyan_admissions | **0** |
| papers | **0** | documents | 135 |
| paper_questions | **0** | knowledge_chunks | 4,024 |
| code_problems | **0** | chunk_vectors | **0** |
| words | **0** | goals | 1 |
| word_decks | **0** | tasks | **0** |
| flashcards | **0** | users | 1 |
| error_records | **0** | | |

解读（按证据强度排序）：
- **题库/刷题链路全空**：quiz_questions / papers / paper_questions / error_records / flashcards = 0，刷题、错题、卡片、模考功能在当前库上是空转。
- **院校库全空**：kaoyan_schools / majors / scorelines / admissions = 0，/kaoyan/* 五个页面（schools/map/scatter/compare/detail）只能渲染空态。
- **向量链路断**：knowledge_chunks=4,024 但 chunk_vectors=0 —— 分块在、嵌入不在，RAG 检索第 3 路（向量）为空，只余关键词路径。
- **单词库空**：words / word_decks = 0。
- 有数据的是：科目骨架（37/244/500）、文档与分块（135/4,024）、goals 1 行、users 1 行。
- 出入提示：.env:31-32 自述「2026-10-14 已切换 PostgreSQL，迁移率 99.74%」，但院校/题/词/向量多为 0——迁移 PASS ≠ 冷启动数据就位（源 SQLite 库是否含这些数据待证）。

置信：确定（一手实测，单连接直查）。

## 2. D2 双轨现状 —— 判定：未收敛（双轨并存）

后端：
- routers/exam.py:16 `router = APIRouter(prefix="/api/exam", tags=["组卷模考"])`
- routers/papers.py:17 `router = APIRouter(prefix="/api/papers", tags=["组题网"])`
- main.py:279 挂 papers.router；main.py:283 挂 exam.router → **双前缀并存且同时挂载**。
- codebank.py:24 `prefix="/api/codebank"`，挂载于 main.py:253；code_oj.py:13 `prefix="/api/code"` **未挂载**——main.py:280 注释原文「代码上机 OJ 暂不挂载：判题要起子进程跑用户代码，2C2G 节点扛不住」→ 有意下线、代码保留。

前端：
- App.jsx:59 lazy 加载 ExamCenter；App.jsx:148 `<Route path="/exam" element={<ExamCenter />} />` → **独立 /exam 一级路由存在**。
- 子路由齐全：App.jsx:150 `/exam/year/:year`、151 `/exam/paper/:paper`、152 `/exam/:year/:paper`、153 `/exam/:year/:paper/:qno`（后三者挂 Quiz，深链可收藏/分享）。
- ExamCenter 数据源不走 /api/exam：ExamCenter.jsx:36-38 调 `quizApi.papersIndex({ source_kind: 'exam' })` / `quizApi.years(...)`（即 /api/quiz/*）；全前端对 /api/exam 的引用仅测试文件 test/client.contract.test.js:211（'/exam/blueprints'）；/api/papers 的消费入口在 api/client.js:716-722（papersApi：build/save/list/detail/delete/exportPdf）。

结论：后端 /api/exam 与 /api/papers 双轨并存；前端 /exam 独立入口已成型但走 quiz 数据源，/api/exam 实际无 UI 消费（仅测试触达）；codebank 单轨在用，code_oj 已写好未启用。

## 3. D3 表归属错位 —— 判定：未解决

- **flashcards 仍定义在错题文件**：core/models/errors.py:97 `class Flashcard(BigIntPKMixin, TimestampMixin, Base):`，`__tablename__ = "flashcards"`，文件 `__all__` 含 Flashcard；聚合导出 core/models/__init__.py:47 `from .errors import ErrorKnowledgeLink, ErrorRecord, Flashcard`。
- **netdisk_files 仍定义在单词杂项文件**：core/models/words_misc.py:76 `__tablename__ = "netdisk_files"`（类 NetdiskFile）；__init__.py:87-95 从 words_misc 导入。
- 加重项（超出检查点但同属技术债）：legacy models.py:674 `class Flashcard(Base)`、models.py:525 netdisk_files 与 core/models 分片**双定义并存**；业务路由现役的是 models.py（routers/flashcards.py:10 `from models import Flashcard`；main.py:20 `from models import (...)`），orm_aliases.py:1-27 头注自述 models.py 为业务路由读写路径、兼容别名待 ADR-002 Phase 2 移除。
- 对照：core/models/__init__.py:3-16 文档串自述按 core/sql/ 分片号归位（errors.py=050 错题/卡片、words_misc.py=070 单词/网盘），即错位是「按 SQL 分片号」的既成约定，但域归属上卡片≠错题、网盘≠单词。

## 4. D4 快赢项（前端文案/空态）—— 判定：5 项已解决，1 项部分，1 项有残留

1. **Words 空库伪装成功 → 已解决**。Words.jsx:371-386：`queue.length === 0 && (stats?.total || 0) === 0` 时渲染「还没有学习单词」+ 引导（导入单词 / 前往词库管理），373 行注释原文「空库不能说‘已完成’：这是最容易被误读成‘今天任务做完了’的假成功态」；「今日单词已全部复习完成」仅出现在 total>0 且无到期（Words.jsx:392-393），语义成立。
2. **CodeBank「重点」repeat → 已解决（本文件），同款模式残留他处**。CodeBank.jsx:11-13 注释记录旧实现 bug 并改为 `STARS = (n) => '★'.repeat(...)+'☆'.repeat(...)`（210 行筛选 chip 同步改）。残留：components/ModelSelectPanel.jsx:191-193（`'重点'.repeat(m.chinese)` 等）、pages/Words.jsx:245（`{'重点'.repeat(stars)} 熟悉度`）、pages/KaoyanSchools.jsx:127（星级展示）。
3. **五页空态**：
   - /insights 已解决：Insights.jsx:77-80 总空态 EmptyState「还没有学习数据」+ 分图空态 191/207/215（暂无答题记录/错题标签/学习时长，各带引导语）。
   - /kaoyan/map 已解决：KaoyanMap.jsx:23-25 对 200+空响应体做防御；105-106 空态二分「院校库还没有数据：导入院校与分数线后…」/「该年份没有可展示的省份数据」。
   - /kaoyan/scatter 已解决：KaoyanScatter.jsx:24-26 同款防御；107-108「院校库还没有招生数据：导入后这里会按库里的真实年份出图」。
   - /textbooks 已解决：Textbooks.jsx:206-211 空态「暂无教材数据：目录内容全部来自后端，导入资料后自动按科目归组」（207 行注释说明此前写死科目文案的问题）。
   - /kaoyan/compare **部分**：有 LoadingState（249 行「对比中…」）与 ErrorState+重试（250），有未命中收集 notFound（112-114）与「请至少选择 2 所院校」toast（128-129）；但**无 EmptyState 组件、无「院校库为空」的全局引导**，0 选中且无结果时页面仅剩页首说明文字 + 搜索框——结合 D1 kaoyan_schools=0，用户落地即面对无任何反馈的搜索框。
4. **KaoyanSchoolDetail 404 引导 → 已解决**。KaoyanSchoolDetail.jsx:106 加载中态；107 `const notFound = loadError.status === 404`；114 标题二分「未找到该院校 / 院校详情加载失败」；117 「院校 ID「id」不在院校库中，可能已被删除或链接有误。」；121 `<Link className="btn primary" to="/kaoyan/schools">返回院校库</Link>`；非 404 才给重试按钮（122-125）。
5. **倒计时统一 → 已解决（goals 为权威源）**。Dashboard.jsx:228-246：后端 summary.countdown 为唯一权威（services/exam_calendar.py 单点判定 phase），前端 settings.examDate 优先实时更新，`cd?.is_default` → 标「预估」（245-246、698-699），不再写死 12/21；KaoyanSchools.jsx:201-212 注释「主考试日期走 utils/exam 的单一口径：后端 Goal → 本地设置 → 未配置（渲染空态）」，659-662 天数统一走 examDaysLeft（注释明言避免首页 427 天 vs 院校库 426 天分裂）；后端 exam_calendar.py:155-162 `resolve_for_db(goal)`：Goal.exam_date 权威，无 Goal 走 default_exam_year 兜底且必须标预估（6-8 行注释回顾了此前三处各算各的打架史）。goals 表实测 1 行，链路有真数据可读。附加：KaoyanSchools.jsx:683-685 支持本地自定义考试倒计时（localStorage），属功能而非债。

## 5. D5 冷启动资产在仓 —— 判定：已解决（13/13 在仓、非空壳）

实际位置在 backend-main-fastapi/ 子目录（仓库根无 pipeline/；根 scripts/ 仅 organize_knowledge_base.py）：

pipeline/（backend-main-fastapi/pipeline/）：
- exam_bank_extractor.py（353 行 / 15.4KB）
- question_schema.py（271 行 / 12.4KB）
- import_textbooks.py（137 行 / 7.2KB）
- textbooks_seed.json（349 行 / 12.9KB）
- run_pipeline.py（257 行 / 14.2KB）
- build_vectors.py（130 行 / 6.5KB）

scripts/（backend-main-fastapi/scripts/）：
- import_exam_questions.py（205 行）、import_kb_data.py（261 行）、smart_ingest.py（247 行，另有 services/smart_ingest.py 副本）、migrate_kaoyan.py（51 行）、six_province_import_plan.py（337 行）、fill_chsi_schid.py（155 行）、clean_seed_fakes.py（88 行）

同类治理脚本实存清单（本次全部未执行）：backend-main-fastapi/scripts/ 下 clean_admissions_dirty / clean_cross_source_dups / clean_document_text / clean_document_watermarks / clean_documents_empty / clean_draft_marks_all / clean_flashcards / clean_garbage_ai_answers / clean_inline_hex / clean_junk_chunks / clean_knowledge_points / clean_notices_noise / clean_placeholder_docs / clean_quiz_draft_marks / clean_quiz_media_quality / clean_quiz_options / clean_quiz_quality / clean_quiz_questions / clean_seed_fakes（19 个）+ scripts/datasource/clean_kp_noise.py、scripts/datasource/dedupe_schools.py、scripts/dedupe_answer_candidates.py、scripts/dedupe_notices.py（4 个）+ pipeline/clean_sft_data.py（1 个），共 24 个；server-upload/backend-main-fastapi/ 内有整套同名部署副本（未计入）。

结论：缺口在「没跑/没导」，不在「没写」——与 D1 的全 0 现状互为印证。

## 6. 待证项（未定位，附查法）

1. 后端实际运行解释器：两个候选 Python 均无 psycopg，但后端显然在连 PG。查 services/startup_manager.py 与 启动.bat 的 PYEXE 选择逻辑，或运行期进程命令行。
2. /api/exam 的去留：无 UI 消费、仅测试触达。查 docs/ 内 ADR/变更记录确认它是否待接管 /exam 数据源或待删。
3. chunk_vectors=0 的原因：build_vectors.py 在仓但未跑出结果；确认 embedding 模型资产是否就位（backend-main-fastapi/data/ 被 .gitignore，本机是否存在需查）。
4. 「迁移率 99.74% PASS」与院校/题/词全 0 的出入：对照 database/ 下 SQLite 源库行数与 scripts/migrate_kaoyan.py 的迁移范围，确认是源库本就空还是迁移跳表。

## 7. 建议的下一步

1. 灌数据优先：按 scripts/six_province_import_plan.py → import_exam_questions.py / import_kb_data.py 顺序补院校库与题库（当前 0 行是冷启动最大缺口）。
2. 跑 pipeline/run_pipeline.py + build_vectors.py，补 4,024 个 chunk 的向量缺口（检索链路恢复）。
3. 双轨决断：/api/exam vs /api/papers 取舍（前端现状 = /exam 页面走 quiz/papers-index + papersApi，exam router 悬空）。
4. 模型归位：Flashcard/NetdiskFile 移出 errors.py / words_misc.py（或以 ADR 形式确认按分片号豁免），并排期 models.py 与 core/models 双定义的收口（orm_aliases.py 自述待 ADR-002 Phase 2）。
5. 补 /kaoyan/compare 的空库 EmptyState 与「院校库为空」引导。
