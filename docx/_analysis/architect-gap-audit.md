# 用户新需求 × 现状核查 × 缺口 × 改造落点对照报告

> 作者：架构师 高见远（software-architect-2）
> 日期：2026-10-12
> 性质：**只读核查报告**（未改任何业务代码 / 数据库 / 未删任何东西；查库一律 `sqlite3.connect("file:...?mode=ro", uri=True)`）
> 真库：`D:\平台\database\kaoyan.db`（诱饵库 `backend-main-fastapi/data/kaoyan.db` 未使用）
> 上游输入：用户本轮 12 条功能诉求 + team-lead 逐条核查清单 + 上一轮《知识点地图构建方案》（`docx/_analysis/architect-kb-map-design.md`）

---

## 0. 一句话结论

平台**后端骨架已经很宽**（266 个路由、59 个 service、29 个前端页面），本文核查的 12 条需求里：

- **已经有、只差"接起来"的：6 条**（学科统一、公告跨校聚合、知识点刷题入口、粘贴文本出题、数据自动导入留痕、知识入库断链修复）→ 主要是"收口 + 补一个聚合端点/一个参数"，工作量小。
- **有半个、缺关键字段/页面的：4 条**（院校库筛选缺 `type`/`region`、院校介绍 `intro` 全空、招生计划页缺独立端点、历年分数缺同比数据源）。
- **数据库里一根毛都没有、要从零建的：2 条**（力扣式编程题库 + 判题沙箱；复试题库）。

**最高优先级前置项只有一个：让 `subject_config` 成为全站科目唯一来源**（否则后面所有"添加科目/覆盖 0854"都会反复反复打补丁）。

---

## 1. 核心大对照表（需求 → 现状 → 缺口 → 落点）

| # | 用户需求 | 现状（实测证据） | 缺口 | 要改/新建的文件·表·接口 | 工作量 | 前置依赖 |
|---|---------|----------------|------|----------------------|--------|---------|
| **1** | 不指定学科、覆盖 **0854 电子信息**；刷题类型可扩展（数/英/政/数电/模电/信号/光学/408）且**可添加科目** | ① `subject_config` 表**已存在**，24 行（全 `is_custom=0`，即全是内置种子，**无一行自定义**）；② `taxonomy.py` 已有完整 CRUD `POST/PUT/DELETE /api/taxonomy/subjects`；③ 前端 `SubjectManager.jsx`+路由 `/subjects` 已做；④ **但** `quiz.py`(`/subjects` 按 `quiz_questions.subject` group by)、`papers.py`(`/subjects` 同)、`documents.py`(`/subjects` 按 doc/subject count)、`kaoyan.py`(`/subjects` 读 `kaoyan_subjects` 学科表) **四个 `/subjects` 全都不读 `subject_config`**；⑤ 库中 0854 相关仅 `计算机学科专业基础408` 在跑（292 题），`信号与系统/光学/普通物理/通信原理` 几乎 0 题、0-1 文档 | ① `subject_config` 只是"科目字典"，业务表科目标签是**自由字符串**，两者未打通；② 五个 `/subjects` 口径五套，前端拿到的科目随页面而变；③ 0854 的 8 个工科学科（`kaoyan_subjects` 8 行）与 `taxonomy` 内置池对不齐；④ 新增科目后无"某科有没有题/有没有资料"的可见反馈 | 后端：`services/subject_config.py`（扩为"唯一来源"）+ 新增 `services/subject_registry.py`（统一聚合器）；改造 `routers/quiz.py:605`、`routers/papers.py:41`、`routers/documents.py:117` 三个 `/subjects` 走注册器；`routers/taxonomy.py:22` 已达标仅需对齐字段。前端：`Quiz.jsx`(193/548)、`KbMap.jsx`(47)、`SubjectManager.jsx` 统一消费同一契约 | 中（统一口径+回归 5 处） | **本方①学科统一方案**（见 §3.1）。无前置，本身即最高前置 |
| **2** | 院校库筛选：**地区 / 类型 / 标签**（对标 kaoyan.cn/school-list） | `GET /api/kaoyan/schools`（`kaoyan.py:133`）**支持** `level / province / subject_code / keyword / year / sort / page`；`kaoyan_schools` 列=`id,name,level,province,city,logo_url,intro,tags,official_url,created_at,updated_at,data_source`。**无 `type` 列、无 `region` 列**；`tags` 23/493 非空且清一色 `"yz_dwdm=10002"`（研招网单位代码，**不是筛选标签**）。前端 `KaoyanSchools.jsx` 已**前端派生** region（`REGION_MAP` 由 province 映射）+ 全量拉取再前端过滤（`无 region 字段` 注释在 64 行） | ① **缺 `type`（院校类型：综合/理工/师范/农林…）列**；② **缺 `region`（大区）列**，现由前端硬编码省份映射，脆弱；③ `tags` 是废数据（混入了 `yz_dwdm`）；④ "标签"筛选（如 双一流/强基/自划线）无数据源 | 表：`kaoyan_schools` **加列** `type VARCHAR(30)`、`region VARCHAR(30)`（原生 DDL `ALTER TABLE`，仿 `spider_notices.ensure_notices_schema` 模式，不动 ORM 基线）；`tags` 清洗（剔除 yz_dwdm，腾出真标签位）。后端：`routers/kaoyan.py:133 list_schools()` 加 `type / region / tag` Query 参数 + 过滤；新建 `scripts/backfill_school_type_region.py`（按 name 关键词规则回填 type，按 province 字典回填 region）。前端：`KaoyanSchools.jsx` 改服务端筛选（去掉前端全量派生 hack）。参考站：kaoyan.cn/school-list | 中 | 无（可独立做）。建议与 #3 同批（都要动 `kaoyan_schools`） |
| **3** | 院校介绍页 | `kaoyan_schools.intro` 字段**存在**，但**实测 0/493 非空**（`SELECT COUNT(*) WHERE intro IS NOT NULL AND intro!=''` = 0）。`get_school`（`kaoyan.py:250`）返回 `intro` 但是空串。排行字段（如 软科排名）**表中无** | ① `intro` 全空，介绍页无内容；② 无院校排名/办学规模/师资等介绍性字段 | 表：`kaoyan_schools` 或新建 `kaoyan_school_profiles`（1:1）加 `rank_soft / rank_ruanke / founded_year / school_type_detail / website`。数据：新建 `services/kaoyan/spider_school_intro.py`（各校官网简介页解析，参考 `spider_notices` 的 webplus 适配器复用）+ 兜底 `scripts/backfill_school_intro.py`（用 LLM 从已有正文字段生成 200 字简介，诚实标注 `data_source=ai_generated`）。前端：`KaoyanSchoolDetail.jsx`（overview tab，221 行）渲染 intro+排行卡 | 中大（主要在网络采集/回填） | #2（同动 schools 表，建议合并加列一次做完） |
| **4** | 招生计划页：专业 × 拟招 × 考试科目 | 表齐：`kaoyan_colleges(469) / kaoyan_majors(832) / kaoyan_admissions(832)`。`GET /schools/{id}/majors`（`kaoyan.py:278`）返回 majors（含 `exam_subjects` JSON）；`GET /schools/{id}/admissions`（`kaoyan.py:309`）join majors 返回 `enroll_count` 等。**但无独立"招生计划"聚合端点**（前端要靠两次调用前端拼）；`majors.exam_subjects` 825/832 非空（填充率高）；`admissions.enroll_count` 803/832 非空 | ① **缺 `GET /schools/{id}/enrollment-plan`**（专业×拟招×考试科目 一次返回）；② `admissions` 年份 825 行挤在 2026、6 行 2025、1 行 2099（脏数据），计划页"历年计划"无跨度；③ 考试科目是原始 JSON，未归一（如 `(101)思想政治理论` 带编号） | 后端：`routers/kaoyan.py` 新增 `GET /schools/{school_id}/enrollment-plan`（join majors+admissions，`exam_subjects` 用已存在的 `analysis/dashboard` 同款编号剥离逻辑 `re.sub(r"^\(?\d{3}\)?\s*","",s)` 归一）；清洗 `admissions.year=2099` 脏行。前端：`KaoyanSchoolDetail.jsx` 招生计划 tab 改单次调用 | 小-中 | #1（专业归一化依赖学科统一）；无强前置 |
| **5** | 历年分数 + **同比批注** | `GET /schools/{id}/scores`（`kaoyan.py:292`）已返回 `year/total_line/.../source`；`GET /analysis/trend`（`kaoyan.py:333`）已按 metric 取近 N 年。**但** `kaoyan_scorelines` 年份分布：**2026 = 788 / 810（97.3%）**，2022-2025 合计仅 22 行。即"同一所学校几乎只有 2026 一年数据" | ① **同比需要"同校 ≥2 年"的数据，现有 788/810 只有一年 → 同比数学上无法计算**；② 前端 `KaoyanSchoolDetail.jsx` 已有"超国家线 ↗N"单点差值（89 行 scoreChartOption），但没有"较去年 ↑N"的同比批注；③ 数据源 `unverified` 占 788（来源可信度低） | 数据（**前置**）：新建 `services/kaoyan/spider_scoreline_history.py` 按校抓历史复试线（各校官网历年线，参考 `spider_school` 模式）；无历史源时，改做"**跨年国家线同比**"（`milestones`/`national_line` 已有数据）作为兜底批注。后端：`GET /schools/{id}/scores` 加 `with_yoy=true` 参数，服务端算 `yoy_delta = total_line[year] - total_line[year-1]` 并返回。前端：`KaoyanSchoolDetail.jsx` 分数 tab 渲染同比箭头 | 大（瓶颈在**数据**，不在代码） | **数据先行**：没有多年线，代码写了也无数据可批注。建议降级为"国家线同比"先上 |
| **6** | 公告**随时爬取** + **首页公告栏** | 表 `kaoyan_notices(518 行, 8 校)`；爬虫 `services/kaoyan/spider_notices.py` 完整（robots 合规 + webplus JSON 适配 + HTML 回退）；`GET /schools/{id}/notices`（`kaoyan.py:993`）按校查；`GET /notices/types`（1020）类型分布；`scheduler.py:208 _kaoyan_collect_job` **每周一 06:00** 增量采（国家线+公告 max_schools=10）；`KaoyanImport.jsx` 有"公告采集"按钮→`POST /collection/refresh?source=notices` | ① **无"跨校聚合公告"端点**（现有只能按 school_id 查，无 `/notices` 全量/最新列表）；② **无首页公告栏**（`Dashboard.jsx`/`KaoyanGuide.jsx` 完全没有公告模块，grep 0 命中）；③ 518 条集中在 8 校（西安电子 296 条但全 2016-07-15 同一天，疑似解析噪声）；④ "随时爬取"已有手动入口，但**无按单校/关键词触发**的细粒度 API | 后端：`routers/kaoyan.py` 新增 `GET /notices`（全量跨校，支持 `limit/since/notice_type/keyword`，供首页）；`POST /notices/crawl`（按 `school`/`school_id` 单校即时触发，复用 `crawl_school_notices(school_names=[...])`）。清数据：清洗西电 296 条 2016-07-15 噪声。前端：新建 `components/NoticeBoard.jsx`，挂到 `Dashboard.jsx` 首页 | 中 | 无（爬虫/表都在，只缺端点+组件） |
| **7** | 知识点**全景刷题**（对标 codebrick/practice/panorama） | `GET /api/quiz/questions`（`quiz.py:18`）参数=`subject/chapter/difficulty/source/question_type/mode/q/year/paper/page`，**无 `kp_id`**；只能 `q=知识点名` 模糊匹配。`GET /taxonomy/tree`（`taxonomy.py:220`）返回 科目→章→知识点 三级树（含掌握度）。前端 `Quiz.jsx` **已有"按知识点" tab**（541 行 renderKnowledge），但它是"选科目→列**章**→按 `chapter` 刷"，**不能下钻到单个知识点 ID 出题**。表 `question_knowledge_links`（6288 行，300 个 KP 已关联）**存在但出题端没用** | ① `GET /questions` **缺 `kp_id` 参数**（按 `question_knowledge_links` join 出题）；② 前端只能下钻到"章"，不能到"知识点"；③ 无"全景"式总览（全科所有知识点一屏，带掌握度色阶）；④ 6288 条 links 未接入出题 | 后端：`routers/quiz.py:18 list_questions()` 加 `kp_id: Optional[int]`，走 `question_knowledge_links` join；`GET /taxonomy/tree` 已够，可加 `?flat=true` 返回扁平知识点列表供全景。前端：`Quiz.jsx` renderKnowledge 增加"知识点"层级（点知识点→`startWithFilter({kp_id})`）；新建 `pages/Panorama.jsx`（全科知识点全景 + 掌握度热力）路由 `/panorama`。参考站：codebrick/practice/panorama、exam-strategy | 中 | #1（科目统一后全景才完整）；`question_knowledge_links` 已存在，无前置 |
| **8** | 考频分析（对标 exam-strategy） | `knowledge_points.exam_frequency` 列存在（651 行：46 行=1、24=2、22=3、17=4、67=5，**426 行=0/NULL 未评**）；已在 `taxonomy.py`(305/360/478)、`documents.py`(276)、`error_linker.py`(439/454) 用于排序/加权。**但无独立考频聚合端点**（无法"按科目/章节看考频排行"）。`knowledge_points` **无 `year` 列**（无法按年份算考频）；`quiz_questions.year` 仅 725/9171=7.9% 非空 | ① **缺 `GET /taxonomy/exam-frequency`**（按科目/章节聚合考频，输出 TOP 高频考点）；② **按年份考频无数据基础**（KP 无 year、题 year 仅 7.9%）；③ 考频本质是"人工填的 1-5 分"，不是"从真题统计出来的"，exam-strategy 那种"近 N 年考查次数"要重算 | 后端：`routers/taxonomy.py` 新增 `GET /exam-frequency`（现有 `exam_frequency` 聚合排名，立即可做）；**真考频**需新建 `services/exam_frequency.py`：由 `question_knowledge_links` + `quiz_questions.year` 统计"某 KP 在真题里出现次数×年份"，反写 `knowledge_points.exam_frequency`。数据：`scripts/backfill_quiz_year.py`（从 `source_paper/paper` 正则提年份，把 7.9% 提升）、`scripts/backfill_exam_frequency.py`。前端：新建 `pages/ExamFrequency.jsx` | 中大（真考频依赖回填） | #7（都用 `question_knowledge_links`）；年份回填是硬前置 |
| **9** | 力扣式编程题库（C++/Python/C/Java） | **全无**：全库表清单里无任何 `problem* / submission* / judge* / code*` 表（探测 0 命中）；无判题 service；requirements 无 docker/judge；前端无页面、`App.jsx` 无路由 | **从零建**：① 题目表（题干/MD 描述/样例/难度/标签/语言）② 提交表（代码/语言/状态/耗时/内存）③ 判题执行（**沙箱**：编译 + 运行 + 超时/内存限制 + 用例比对）④ 用例表（隐藏用例）⑤ 前端题目列表/编辑器/提交结果页 | 见 **§3.2 完整设计**。新增表：`code_problems / code_problem_testcases / code_submissions / code_tags`；新增 `services/code_judge/`（沙箱，见风险评估）；`routers/code.py`；前端 `pages/CodeBank.jsx`+`pages/CodeProblem.jsx` | **大**（最高风险，工作量最大） | 无强前置，但**判题沙箱是安全红线**（见 §3.2 风险），建议最后做 |
| **10** | 复试题库 + **粘贴文本出题** + 爬取知识点 | **粘贴出题已有基础**：`POST /api/quiz/import/markdown`（`quiz.py:577`，Markdown 文本→题目，含 `_parse_markdown_questions` + `autoclassify` 规则+LLM 兜底）；`kb_import`（`routers/kb_import.py`）已做"文档→`extract_questions`→字段映射→去重标注→待确认"。**复试相关全无**：无 `fushi/retest` 表、无端点、无页面。爬取知识点：`document_analyzer.py`(201) 已有"从正文 LLM 抽知识点"能力（`extract_kp`） | ① **"复试"维度完全缺**（表/端点/页面）；② 粘贴出题**缺"人工确认"环节**（现 `import/markdown` 直接落库，用户要的是"抽取→确认→入库"，`kb_import` 有 `pending_questions`(14 行) 可复用但未接到粘贴流）；③ "爬取知识点"→LLM 抽取已存在但未与"粘贴"入口合并 | 后端：新建表 `fushi_questions`（或复用 `quiz_questions` + `is_retest` 标志，推荐后者更统一）；`routers/quiz.py:577` 增加 `?dry_run=true` 返回候选题列表 + `POST /quiz/import/confirm`（人工确认后落库）；复用 `pending_questions` 表做待确认队列。前端：`QuizBank.jsx` 增加"粘贴导入→候选题确认"步骤；新建复试 tab。**抽取链路**：见 **§3.3** | 中 | #1（复试科目要能加进 subject_config）；粘贴基础已存在 |
| **11** | 数据自动导入：采集→抽取→校验→去重→入库→留痕→回写 | `kaoyan_collection_runs(16 行)` 已有留痕表；`POST /spider/run`（`kaoyan.py:735`）爬虫+写 run；`POST /collection/refresh`（841）多源刷新；`GET/POST /collection/runs`（773/792）版本管理；`KaoyanImport.jsx` 有 3 个采集按钮（engineering/national_line/notices）。**但**：`spider/run` 只记 `added_schools`，**无抽取/校验/去重/回写步骤的留痕**；`item_type` 字段值杂（`mixed/admission+scoreline`） | ① 采集**有留痕**，但链路只到"入库条数"，缺"抽取了多少、校验拦了多少、去重合并了几条、回写了什么"；② `refresh` 各源返回结构不统一；③ 无统一"导入任务"编排（每一步产物与状态无落表） | 后端：扩展 `kaoyan_collection_runs.detail` JSON 结构规范（`{fetched, extracted, validated, deduped, inserted, updated, failed[]}`）；新建 `services/kaoyan/ingest_orchestrator.py`（统一 7 步编排，每步写 detail）；`routers/kaoyan.py` 的 `spider/run`、`collection/refresh` 改走编排器。前端：`KaoyanImport.jsx` 展示分步进度 | 中 | 无（表已存在，只缺编排与字段规范） |
| **12** | 知识入库链路完善（documents **断链**） | **重要修正 team-lead 的假设**：`documents` 表**没有 `source_path` 列**（列=`file_name/file_path/file_type/...`）；`file_path` **不是"1,846 行全空"**——实测 **1405 行是真路径**（如 `...data\storage\documents\考研资料数据集V1.0\数电资料\数电\...pdf`，且该目录**真实存在**），**441 行为 NULL**。断链真相 = ① 441 行无 `file_path`；② 1405 行路径指向 `backend-main-fastapi/data/storage/`，与 `knowledge_base/documents/`（另一套，仅 6 校目录）**两套存储并存**；③ **无 `source_path` 语义列**（无法记"原始来路"，如网盘/上传/爬取）。**已有修复器**：`services/kb_pipeline.py:226 repair_file_paths()`（按文件名重建索引回填）+ `services/kb_pipeline.py:267 reparse_empty()` + `routers/kb.py:78 POST /kb/repair-paths`。`kb_ingest.py`(196) 新入库**会**正确写 `file_path`；`kb_service.ingest_document`(548) 是主入库口 | ① 441 行 NULL 未被一次性回填（`repair_file_paths` 只在 `/kb/heal` 或手动触发时跑）；② 缺 `source_path` 列记录"来路"；③ 两套存储（`data/storage/documents` vs `knowledge_base/documents`）不统一，新老文件分家；④ 无"入库→产生 chunks→关联 KP→可检索"的一体化状态看板 | 修复：**已有 `repair_file_paths`，只差执行 + 覆盖 NULL 分支**（现逻辑 `not (d.file_path and os.path.exists(d.file_path))` 会含 NULL，可覆盖）。表：`documents` **加列** `source_path VARCHAR(500) NULL`（原生 DDL）+ `storage_root VARCHAR(30)`（标记 storage/kb_root 归属）。后端：`scripts/backfill_doc_source.py`（回填 441 NULL + 归并两套路径）；`kb_ingest`/`kb_service.ingest_document` 补写 `source_path`。前端：`Documents.jsx` 显示来路与"失踪文件"告警 | 小-中（**修复器已存在，主要是执行+补列**） | 无。**这是投入产出比最高的一条**——一行脚本能救 441 篇文档 |

---

## 2. 逐条验收标准

| # | 验收标准（可测量） |
|---|------------------|
| 1 | ① 全站 5 个 `/subjects` 返回**完全一致**的科目集合；② 在 `SubjectManager` 新增科目「信号与系统2」后，`quiz/papers/documents/kaoyan` 四个页面下拉**立刻**能看到；③ `subject_config` 中出现 `is_custom=1` 的行；④ 0854 的 8 个工科学科全部可在刷题类型里选到 |
| 2 | ① `GET /schools?region=华东&type=理工` 返回正确子集（服务端过滤）；② `kaoyan_schools.region` 非空 ≥490（现有 province 491 非空）；③ `type` 非空率 ≥80%；④ `tags` 中 `yz_dwdm=` 前缀清零 |
| 3 | ① `documents`/`schools.intro` 非空率从 0 → ≥60%（493 校中 ≥300 有简介）；② 院校详情 overview 显示简介 + ≥1 个排行字段；③ AI 生成的简介 `data_source` 标注清晰、不冒充官方 |
| 4 | ① 存在 `GET /schools/{id}/enrollment-plan` 单端点；② 任意 985 校返回 ≥1 行「专业 × 拟招 × 考试科目」；③ `admissions.year=2099` 脏行清零；④ 考试科目去除 `(101)` 前缀编号 |
| 5 | ① 对**有 ≥2 年数据**的校，`GET /schools/{id}/scores?with_yoy=true` 返回 `yoy_delta`；② 前端显示"较去年 ↑N"批注；③ 若全库无 ≥2 年数据，则首页/详情显示"国家线同比"兜底批注（诚实：不伪造） |
| 6 | ① `GET /notices?limit=20` 返回跨校最新公告；② `POST /notices/crawl?school=贵州大学` 返回新增条数且写 `kaoyan_collection_runs`；③ 首页 `Dashboard` 出现公告栏且点击跳原文；④ 西电 296 条噪声清理 |
| 7 | ① `GET /quiz/questions?kp_id=123` 返回该知识点关联题（走 `question_knowledge_links`）；② 前端可从"科目→章→**知识点**"三级下钻并开始练习；③ 全景页 `Panorama.jsx` 一屏展示全科知识点 + 掌握度色阶 |
| 8 | ① `GET /taxonomy/exam-frequency?subject=数字电子技术` 返回频次排行；② 高频考点 TOP 与人工直觉一致（抽样验证）；③ 若实现真考频，`exam_frequency` 由真题统计反写，且可解释（附出现年份） |
| 9 | ① 支持 4 语言（C++/Python/C/Java）提交；② 提交返回 `AC/WA/TLE/MLE/CE/RE` 状态；③ **沙箱：超时 3s、内存 256MB、禁网络、禁文件系统越权**；④ 隐藏用例不可被前端读到；⑤ 连续提交不拖垮服务器 |
| 10 | ① `POST /quiz/import/markdown?dry_run=true` 返回**候选题列表**不落库；② `POST /quiz/import/confirm` 确认后落库；③ 复试 tab 可用；④ "爬取知识点"从粘贴文本 → LLM 抽 KP → 确认入 `knowledge_points` |
| 11 | ① `collection_runs.detail` 含 `{fetched, extracted, validated, deduped, inserted, updated, failed}` 全字段；② 任一次采集可在"数据管理"页看到分步结果；③ 采集失败可定位到具体步骤 |
| 12 | ① `documents.file_path` NULL 从 441 → ≤50；② 新增 `source_path` 列且新入库自动写；③ `POST /kb/repair-paths` 幂等可重复执行；④ `knowledge_base` 状态页显示"失踪文件"计数为 0 |

---

## 3. 三个重点方案

### 3.1 学科统一方案：让 `subject_config` 成为唯一来源

**问题本质**：`subject_config` 是"字典表"，但业务表（`quiz_questions.subject`、`documents.subject`、`error_records.subject`）存的是**自由字符串**，五个 `/subjects` 端点各查各的。用户"添加科目"后，题目不会自动归到新科目，新科目在刷题页也可能不出现。

**方案（三选一，推荐 A）**：

- **方案 A（推荐，零数据迁移）**：新建 `services/subject_registry.py` 作为**聚合器**，唯一职责 = 合并「`subject_config` 字典」+「业务表实际出现的 subject」，对外提供 `list_subjects(db) -> [{subject, is_custom, question_count, doc_count, error_count, has_data}]`。
  - `routers/quiz.py:605`、`papers.py:41`、`documents.py:117` 三个 `/subjects` 全部改为 `return subject_registry.list_subjects(db)`。
  - `taxonomy.py:22` 已实现类似逻辑，抽取其 `q_rows/e_rows` 到 registry 复用。
  - **不迁移数据**：新科目出现在"可选科目"里，`question_count=0`，用户往里导题自然就有了。
  - 契约统一：前端只认 `{subjects:[{subject, ...counts}]}`。

- 方案 B（重）：业务表加 `subject_id` 外键，全量迁移——**不推荐**（破坏自由字符串容错，且 9171 题迁移风险大）。
- 方案 C（弱）：只改前端聚合——治标不治本，端点仍五套口径。

**0854 覆盖**：把 `kaoyan_subjects` 8 个工科学科（0803/0808/0809/0810/0811/0812/0835/0854）**保证**都在 `subject_config`（`taxonomy.EXT_SUBJECTS` 已含 6 个，核对补 `0854 电子信息` 专硕口径）。`ensure_subject_config_seeds()` 幂等播种，老库补跑一次即可。

### 3.2 力扣式编程题库：从零建的完整设计

**表结构草案**（新增，全部原生 DDL 或 ORM 基线新增，不动既有表）：

```sql
-- 题目
CREATE TABLE code_problems (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE,              -- URL 用短名
  title TEXT NOT NULL,
  difficulty TEXT,               -- easy/medium/hard
  description_md TEXT,           -- Markdown 题干
  input_spec TEXT, output_spec TEXT,
  sample_json TEXT,              -- [{input, output, explain}]
  hint TEXT,
  subject TEXT,                  -- 关联 subject_config（如 数据结构/计算机学科专业基础408）
  kp_id INTEGER,                 -- 关联 knowledge_points（复用 #7 链路）
  languages TEXT,                -- ["cpp","python","c","java"]
  is_retest INTEGER DEFAULT 0,   -- 是否复试题（复用 #10）
  created_at DATETIME
);
-- 测试用例（含隐藏）
CREATE TABLE code_problem_testcases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  problem_id INTEGER NOT NULL,
  input TEXT, expected_output TEXT,
  is_sample INTEGER DEFAULT 0,   -- 1=公开样例, 0=隐藏
  score INTEGER DEFAULT 1
);
-- 提交
CREATE TABLE code_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  problem_id INTEGER NOT NULL,
  language TEXT NOT NULL,        -- cpp/python/c/java
  code TEXT NOT NULL,
  status TEXT,                   -- AC/WA/TLE/MLE/RE/CE/PENDING
  passed_cases INTEGER, total_cases INTEGER,
  time_ms INTEGER, memory_kb INTEGER,
  compile_output TEXT,
  created_at DATETIME
);
CREATE INDEX ix_code_sub_problem ON code_submissions(problem_id, created_at);
```

**判题链路（service 分层）**：

```
routers/code.py
  GET  /api/code/problems          列表（难度/标签/科目筛选）
  GET  /api/code/problems/{id}     详情（**不含**隐藏用例）
  POST /api/code/submit            {problem_id, language, code} → 入队
  GET  /api/code/submissions/{id}  轮询判题结果

services/code_judge/
  __init__.py     judge_submission(submission_id)
  runners.py      按语言编译+运行（cpp: g++ -O2; c: gcc; java: javac/java; python: python3）
  sandbox.py      ⚠️ 安全核心：见风险
  comparer.py     输出比对（容忍行尾空格/末尾换行）
```

**⚠️ 判题沙箱风险（必须正视，是安全红线）**：

| 风险 | 后果 | 缓解 |
|------|------|------|
| 用户提交 `os.system("rm -rf /")` / fork 炸弹 | 服务器被毁 | **必须**在隔离环境跑：首选 **Docker/Podman 一次性容器**（`--network=none --memory=256m --cpus=1 --pids-limit=64 --read-only`），无 Docker 则 Linux `nsjail`/`firejail`；**Windows 开发机无隔离 → 只能本地白名单语言 + 强烈不推荐生产** |
| 死循环 / 超时 | 占满 CPU | `subprocess` + `timeout`（如 3s）+ 进程组 kill；Docker `--stop-timeout` |
| 内存爆炸 | OOM | `resource.setrlimit(RLIMIT_AS)`（Linux）+ Docker `--memory` |
| 读取隐藏用例 | 作弊 | 用例注入用 stdin，**文件系统只挂载当前用例**，容器只读 |
| 编译期执行 | 编译即攻击 | 编译也在沙箱内，`--cap-drop=ALL` |

**结论**：判题功能**技术上可行但风险等级 = 高**。诚实建议：**若目标环境是个人 Windows 本机**，先做"**代码存储 + 人工判题/AI 判题（LLM 比对）**"的轻量版，**不要**上真沙箱编译执行；真沙箱（Docker）留到有 Linux 服务器时再做。工作量：轻量版 中；真沙箱 大。

### 3.3 知识入库 `source_path` 断链修复方案

**断链真相（已实测，纠正上游假设）**：
1. `documents` **无 `source_path` 列**（不是"1,846 行 source_path 全空"）。
2. `file_path`：**1405 行真路径 + 441 行 NULL**（不是"全无"）。
3. 1405 行指向 `backend-main-fastapi/data/storage/documents/...`，**目录真实存在**，可解析。
4. 真正断的是：① 441 行 NULL；② 两套存储并存（`data/storage/documents` vs `knowledge_base/documents`）；③ 无"来路"字段。

**修复方案（分工明确，低风险）**：

- **第 1 步（零开发，最高性价比）**：跑现成的 `services/kb_pipeline.py repair_file_paths()`（或 `POST /api/kb/repair-paths`）。它的判断是 `not (d.file_path and os.path.exists(d.file_path))`，**NULL 也被判为 broken**，会尝试按 `file_name` 在 `data/storage/` 索引里找回 → 能救回一部分 441。
- **第 2 步**：新建 `scripts/backfill_doc_source.py`：① 对 `repair_file_paths` 没找回的，扩展到 `knowledge_base/documents/` 也纳入索引（`_find_storage_roots` 加一条）；② 仍找不到的，标记 `file_path='__MISSING__'` 并出名单（诚实：不装死）。
- **第 3 步**：`documents` 加列 `source_path VARCHAR(500)`（记录原始来路：`netdisk:xxx` / `upload:xxx` / `spider:xxx`）+ `storage_root VARCHAR(30)`（`data_storage` / `kb_root`）。改 `kb_ingest.ingest_file`(196) 与 `kb_service.ingest_document`(548) 入库时写这两列。
- **第 4 步**：`Documents.jsx` 加"失踪文件"告警计数 + 显示来路；`kb_pipeline.health_report()` 增加 `missing_files` 指标。

**验收**：NULL 从 441 → ≤50；`source_path` 列存在且新入库自动写；`/kb/repair-paths` 幂等。

---

## 4. 必须先做的前置项（顺序建议）

| 顺序 | 前置项 | 为什么必须先做 | 命中需求 |
|------|--------|--------------|---------|
| **P0-1** | **学科统一（§3.1 方案 A）** | 所有"加科目/覆盖 0854/复试科目/编程题库归类"都依赖它；它是 5 个端点的收口，做完前其余科目相关改造会反复返工 | #1 #7 #8 #10 #9 |
| **P0-2** | **`documents` 断链修复（§3.3 第1-2步）** | 一行脚本救 441 篇文档，投入产出最高；且"知识入库完善"是 #7/#8/#10 的数据地基 | #12 #7 #8 |
| **P1-1** | **年份回填**（`quiz_questions.year` 7.9% → 提升；`scorelines` 多年数据采集） | #5 同比、#8 按年考频**都没有数据基础**，代码写了也是空批注；数据先行 | #5 #8 |
| **P1-2** | **`kaoyan_schools` 加 `type`/`region` 列**（一次性 DDL + 回填） | #2 筛选、#3 介绍页同表改造，合并做一次省事 | #2 #3 |
| **P2** | **判题沙箱（§3.2 风险）** | 安全红线，且无 Linux 环境时只能做轻量版；建议**最后做** | #9 |
| **P2** | 前端首页公告栏 + 全景页 + 考频页 | 纯展示层，后端就绪后可并行 | #6 #7 #8 |

---

## 5. 关键命令输出证据（原始留档）

### 5.1 科目体系

```
subject_config 行数: 24  (全部 is_custom=0，无自定义)
内置科目：信号与系统/光学/光学与工程光学/其他/控制科学与工程/操作系统/政治/数字电子技术/
数学/数据结构/普通物理/模拟电子技术/电子科学与技术/电气工程/电路/电路分析/真题综合/
网络补充/英语/计算机基础/计算机学科专业基础408/计算机网络/软件工程/通信原理

quiz_questions 实际 subject 分布：
  模拟电子技术 4227 / 数字电子技术 3608 / 政治 814 / 计算机学科专业基础408 292 /
  英语 93 / 真题综合 66 / 数学 54 / 其他 13 / 专业课 4
documents 实际 subject 分布：
  数字电子技术 878 / 英语 256 / 模拟电子技术 234 / 其他 185 / 真题综合 119 / 数学 95 /
  计算机学科专业基础408 37 / 政治 25 / 电路 13 / 通信原理 1 / 网络补充 1 / 普通物理 1 / 信号与系统 1
```

### 5.2 院校库

```
kaoyan_schools 行数: 493
列: id,name,level,province,city,logo_url,intro,tags,official_url,created_at,updated_at,data_source
level 分布: 双非 371 / 211 61 / 985 37 / 双一流 23 / 一本 1
province 非空 491 ; intro 非空 0 ; tags 非空 23（样例 '"yz_dwdm=10002"'）
有无 type 列: False ; 有无 region 列: False
```

### 5.3 招生/分数

```
kaoyan_colleges 469 / kaoyan_majors 832 / kaoyan_admissions 832 / kaoyan_scorelines 810
majors.exam_subjects 非空 825 ; admissions.enroll_count 非空 803
admissions 年份: 2025=6 / 2026=825 / 2099=1
scorelines 年份: 2022=5 / 2023=5 / 2024=5 / 2025=7 / 2026=788
scorelines source: csv_sample 6 / school_official 16 / unverified 788
```

### 5.4 公告

```
kaoyan_notices 518 行, distinct school_id = 8
  上海交通大学 22(无日期) / 北京大学 46 / 桂林电子科技大学 48 / 清华大学 8(无日期) /
  电子科技大学 65 / 西安电子科技大学 296(全 2016-07-15) / 贵州大学 14 / 重庆邮电大学 19
```

### 5.5 知识点/考频/刷题

```
knowledge_points 651 ; exam_frequency: None 49 / 0 426 / 1 46 / 2 24 / 3 22 / 4 17 / 5 67
knowledge_points 无 year 列
quiz_questions 9171 ; year 非空 725(7.9%) ; chapter 非空 5006 ; knowledge_point 非空 5924 ;
  analysis 非空 2680 ; question_knowledge_links 6288 ; distinct kp linked 300
```

### 5.6 编程题库/复试（全无）

```
探测 problem*/submission*/judge*/code*/fushi*/retest* 表：0 命中
单条路由总数：266（grep @router.get|post|put|delete 命中数）
main.py 注册 30 个 router
```

### 5.7 documents 断链

```
documents 行数 1846 ; 列 = id,file_name,file_path,file_type,size,index_status,
  knowledge_point_count,parse_progress,content,created_at,updated_at,subject,doc_type,
  structure_level,ocr_used,content_category   ← 无 source_path 列
file_path 取值分布: (NULL) 441 / 真路径 1405  (无"字符串None")
真路径样例: D:\平台\backend-main-fastapi\data\storage\documents\考研资料数据集V1.0\数电资料\数电\...
  该目录真实存在 ✓
index_status: indexed 1846(全) ; structure_level: document 78/flat 953/ocr 299/structured 516
knowledge_chunks 27893

已存在修复器: services/kb_pipeline.py:226 repair_file_paths()
  + services/kb_pipeline.py:267 reparse_empty()
  + routers/kb.py:78 POST /kb/repair-paths
knowledge_base/ 结构: inbox/{政治,数电,模电} ; documents/2026/{政治,数学,数电,未分类,模电,英语}
  ; meta/manifest.jsonl(77 行) ; .processed_files.json(224 键)
```

### 5.8 已有可复用能力（避免重复造轮子）

```
粘贴文本出题: POST /api/quiz/import/markdown (quiz.py:577) + autoclassify
文档→候选题: routers/kb_import.py (extract_questions→映射→去重→pending_questions 14 行)
调度: services/scheduler.py (复习 08:30 / 网盘每小时 / 自检 07:30 / 择校采集 每周一06:00)
采集留痕: kaoyan_collection_runs 16 行 + POST /spider/run + /collection/refresh + /collection/runs
```

---

*本报告为纯只读核查，未改动任何业务代码、数据库或删除任何文件。所有数据来自 `D:\平台\database\kaoyan.db`（只读连接）与源码静态阅读。*
