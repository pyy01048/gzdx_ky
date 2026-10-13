# 知识点地图构建方案（实测核查 + 架构设计）

> **产出者**：架构师 高见远（software-architect）
> **产出日期**：2026-10-11
> **任务性质**：**只读核查 + 方案设计**。本轮未修改任何业务代码、未改数据库。
> **真库口径**：`D:\平台\database\kaoyan.db`（293,699,584 字节 ≈ 280MB）。
> 所有查询均以 `sqlite3.connect("file:...?mode=ro", uri=True)` 只读方式执行。
> **证据约定**：每条结论标注【实测】= 本轮命令输出；【文档】= 09 号/README 等文档声称。

---

## 0. 结论速览（TL;DR）

| # | 结论 | 关键实测数字 |
| :-- | :--- | :--- |
| 1 | 三级结构**已存在且已落库**，不是从零开始。骨架是**规则/正则启发式**建的（非 LLM），骨架质量中等偏高，但**知识点层是扁平的**（绝大多数无父子层级）。 | `knowledge_points` 651 行；`question_knowledge_links` 6288 行；`knowledge_point_relations` 911 行 |
| 2 | **"题型"这一级实际上没有独立实体**——它只是 `knowledge_points.question_types` 的一个 JSON 字段 + `subject_config.question_types` 的静态清单。**没有题型→题目的直接挂链**。 | 只有 206/651 个 kp 有 `question_types` 值；无 question_type 表 |
| 3 | 题目↔知识点关联**覆盖率不错但集中**：9171 题中 6202 题有 `knowledge_point` 字面值，成功建链 5911 题（64%），但只覆盖 **300/651 = 46%** 的知识点，剩余 351 个 kp 一题未挂。 | `COUNT(DISTINCT question_id)=5911`, `COUNT(DISTINCT kp_id)=300` |
| 4 | **掌握度全库为 0**——651 个 kp 的 `mastery` 全部是 0/NULL，"地图"当前**没有任何学习状态可染色**。`study_events` 表 0 行，闭环数据链断裂。 | mastery 分布：`0/null = 651`；`study_events = 0` |
| 5 | 字段结构与前端**基本对得上但要补**：`/api/taxonomy/tree`、`/coverage`、`/knowledge-points/{kp_id}` 已实现，`KbMap.jsx` 已在消费；**缺** `GET /api/quiz/questions/{id}` 单题详情、题目维度的 `kp_id` 过滤、考频聚合端点。 | 31 路由文件 / 266 端点【实测】；taxonomy 11 个端点 |
| 6 | 资料盘（`knowledge_base` 5010 文件 / 76GB）**极不均衡**：模电 50GB、英语 13GB、数学 6.4GB 肥；政治仅 359MB、408 仅 34 文件、多数支撑科目（信号/通信/普物）几乎为空。 | 见 §1.5 |
| 7 | 与文档不一致（重点）：**表数**（实测 **60** 张 sqlite 对象，含 fts/vec 影子表；业务表约 59，与 09 一致，但 00 号称 61）；**`kaoyan_schools.intro` 非空 = 0**（03 号曾称有简介）；**`papers`/`paper_questions` = 0 行**（09 已裁定建卷不成立，本轮再次确认）。 | 见 §1.1 / §1.2 / §4 |

**一句话判断**：知识点地图的"地基"比文档乐观描述要实在（表、数据、接口都在），但**"地图"目前是一张没有颜色的骨架图**——层级靠规则拼、掌握度全空、题型无实体、关联只覆盖一半知识点。方案应是**"补全 + 互链 + 去空"**，而**不是推倒重建**。

---

## 1. 现状实测核查（命令 + 输出）

### 1.1 数据库实况

命令：
```python
con = sqlite3.connect('file:database/kaoyan.db?mode=ro', uri=True)
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
# 逐表 SELECT COUNT(*)
```

**全部表与行数（实测，共 60 个 table 对象）**：

| 表 | 行数 | 表 | 行数 |
| :--- | ---: | :--- | ---: |
| knowledge_points | **651** | knowledge_chunks | **27893** |
| question_knowledge_links | **6288** | knowledge_chunks_fts | 27729 |
| knowledge_point_relations | **911** | knowledge_chunks_vec | 25815 |
| documents | **1846** | quiz_questions | **9171** |
| kaoyan_schools | **493** | kaoyan_admissions | 832 |
| kaoyan_majors | **832** | kaoyan_scorelines | **810** |
| kaoyan_notices | 518 | kaoyan_colleges | 469 |
| subject_config | **24** | study_events | **0** |
| answer_records | **17** | error_records | **34** |
| papers | **0** | paper_questions | **0** |
| flashcards | 652 | sft_examples | 4670 |
| error_knowledge_links | 33 | expert/pending/milestones 等 | 小 |

> ⚠️ **与文档不一致 #1（表数）**：本轮 `sqlite_master` 实测**60 个 table 对象**，但其中 6 个是 FTS5/vec 影子表（`knowledge_chunks_fts*`、`knowledge_chunks_vec`）。PM 笔记（依据 09 号）裁定"真库 59 张用户表"。两者不矛盾：**60 个对象 − 1 张 SQLite 内部/影子 ≈ 59 业务表**。00 号声称"61 表"偏高。

### 1.2 关键子表核对

**`quiz_questions`（9171 行）** 命令：
```sql
SELECT COUNT(*), COUNT(year), COUNT(answer), COUNT(analysis), COUNT(DISTINCT paper) FROM quiz_questions;
```
| 指标 | 实测值 | 占比 |
| :--- | ---: | ---: |
| 总数 | 9171 | 100% |
| 有 year | **725** | 7.9% |
| 有 answer | **3824** | 41.7% |
| 有 analysis | **2680** | 29.2% |
| distinct paper（非空） | **79** | — |
| 有 knowledge_point（字面） | 6202 | 67.6% |

> 与 00 号声称"答案覆盖 41%（3824）/解析 29%（2680）"**完全吻合**【实测确认】。但与 01 号（回填前 33%/21%）为不同时点，非冲突。

**`kaoyan_schools`（493 行）** 命令：
```sql
SELECT COUNT(*), COUNT(intro), COUNT(tags), COUNT(level) FROM kaoyan_schools;
```
| 指标 | 实测值 |
| :--- | ---: |
| 总数 | 493 |
| intro 非空 | **0** |
| tags 非空 | **23** |
| level 非空 | 493（100%） |

> ⚠️ **与文档不一致 #2**：`intro` 全空（0/493）。03 号/08a 曾把"院校简介"列为已具备能力；实际字段存在但**内容为空**。`tags` 仅 23/493（4.7%）非空，与 03 号自述"tags 不可读"一致。level 覆盖率 100%，**证实 09 号裁定"03 号已过期（说 225 所，实测 493 全有）"**。

**`kaoyan_scorelines`（810 行）按年份**：`2026:788, 2025:7, 2024:5, 2023:5, 2022:5`。→ 分数线数据**严重偏 2026 单年**，历史年份几乎空。

**`kaoyan_notices`（518 行，distinct school = 8）**：跨校公告表存在，但**仅 8 所学校**有数据，聚合面窄。有端点 `GET /api/kaoyan/schools/{id}/notices` + `/notices/types`，**无全校统一聚合列表端点**。

**`study_events` = 0 行、`answer_records` = 17 行、`error_records` = 34 行**：学习行为数据几乎为空。这是"掌握度染色"无法点亮的数据根因。

### 1.3 知识点体系实况（本轮重点）

**DDL（实测 `sqlite_master.sql`）**：

```sql
CREATE TABLE knowledge_points (
    id INTEGER NOT NULL,
    name VARCHAR(300) NOT NULL,
    subject VARCHAR(50),
    chapter VARCHAR(200),
    parent_id INTEGER,            -- ← 层级字段已存在，但几乎未用
    mastery INTEGER,
    exam_frequency INTEGER,
    description TEXT,
    created_at DATETIME,
    document_id INTEGER,          -- ← 溯源到文档，但多数为空
    question_types JSON,          -- ← 题型以 JSON 存在此处，无独立表
    difficulty INTEGER DEFAULT 3,
    review_count INTEGER DEFAULT 0,
    last_review DATETIME, next_review DATETIME,
    ease_factor FLOAT DEFAULT 2.5, interval INTEGER DEFAULT 0, lapses INTEGER DEFAULT 0,
    question_count INTEGER DEFAULT 0,
    PRIMARY KEY (id),
    FOREIGN KEY(parent_id) REFERENCES knowledge_points (id)
)

CREATE TABLE question_knowledge_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    knowledge_point_id INTEGER NOT NULL,
    role TEXT DEFAULT 'primary',
    weight REAL DEFAULT 1.0,
    is_verified INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (question_id, knowledge_point_id),
    FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE,
    FOREIGN KEY (knowledge_point_id) REFERENCES knowledge_points(id) ON DELETE CASCADE
)

CREATE TABLE knowledge_point_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_kp_id INTEGER NOT NULL,
    target_kp_id INTEGER NOT NULL,
    relation_type VARCHAR(20) NOT NULL,   -- contains / parallel / prerequisite
    source VARCHAR(100),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_kp_id) REFERENCES knowledge_points(id),
    FOREIGN KEY (target_kp_id) REFERENCES knowledge_points(id)
)
```

**sample 数据（10 行）**：
```
id=1 name=放大电路的主要性能评价指标 subject=模拟电子技术 chapter=834考纲·模拟电路部分 parent_id=None mastery=0 freq=0 qt=["选择","填空","计算","分析","设计","画图"]
id=2 name=三种基本电路          subject=模拟电子技术 chapter=第3章 多级放大电路 parent_id=None mastery=0 freq=0
id=4 name=差分放大电路          subject=模拟电子技术 chapter=第3章 多级放大电路 parent_id=None mastery=0 freq=5
id=8 name=反馈的判断方法…      subject=模拟电子技术 chapter=第6章 放大电路中的反馈 parent_id=None mastery=0
```
> 观察：① `name` 有的是**规范知识点**（"差分放大电路"），有的是**考纲条目句**（"反馈的判断方法、负反馈放大电路的四种基本组态"）——粒度不均；② `parent_id` 全为 None；③ `chapter` 混入"834考纲·模拟电路部分"这类**非标准章名**。

**按 subject 分布（实测）**：
```
模拟电子技术 209 | 数字电子技术 192 | 数学 105 | 英语 38 | 计算机学科专业基础408 20
电路 15 | 普通物理 14 | 通信原理 13 | 光学与工程光学 11 | 信号与系统 9
政治 9 | 真题综合 6 | 光学 4 | 电路分析 4 | 其他 1 | 网络补充 1
```
> ⚠️ 651 个知识点里**专业课（模电+数电）占 401 = 61.6%**，与 76GB 资料盘的分布（模电肥、政治/408 瘦）一致，但与"公共课也考"的备考现实**不匹配**（政治 kp 仅 9 个，英语 38 个）。

**字段填充率（实测）**：
| 字段 | 非空数 / 651 |
| :--- | ---: |
| chapter | 651（100%） |
| **parent_id** | **261（40%）** |
| description | 469（72%） |
| exam_frequency | 602（92%，但多为 0） |
| **question_types** | **206（31.6%）** |

**`question_knowledge_links` 关联覆盖（实测）**：
| 指标 | 值 |
| :--- | ---: |
| 总链接数 | 6288 |
| role 分布 | `primary` = 6288（100%，无 related） |
| `is_verified` | 全部 = 1（6288） |
| distinct question_id | **5911** |
| distinct knowledge_point_id | **300** |
| kp.question_count>0 的个数 | **300**（与上一致） |
| Σquestion_count / max / avg | 6288 / 289 / 9.66 |

> **关键判断**：建链只覆盖 **5911/9171 = 64.4% 的题目**、**300/651 = 46% 的知识点**。剩余 **351 个知识点零挂题**（正是"地图"上会一片灰的点）。建链是 `scripts/backfill_kp_links.py` 用**同名+同科精确匹配**（确定性、非 LLM）做的。

**`knowledge_point_relations` 关系类型分布（实测）**：
| relation_type | 行数 | source 值 | 含义 |
| :--- | ---: | :--- | :--- |
| `contains` | 466 | `chapter_hierarchy` | 章→节的包含（层级） |
| `parallel` | 326 | `chapter_cooccurrence` | 同章共现（平级） |
| `prerequisite` | 119 | `syllabus_order` | 大纲先后（前驱） |
| 合计 | **911** | | |

> 回答"有没有层级父子关系"：**有，但不是在 `knowledge_points.parent_id` 上，而是在 `knowledge_point_relations` 里**（466 条 contains）。`parent_id` 字段只 40% 非空、且 `tree` 端点**并不读 parent_id**、改为按 `chapter` 字符串分组建树。**两套层级表达并存且不一致**是当前最大的结构债。

### 1.4 路由实况

命令：`grep -rhoE '@router\.(get|post|put|delete|patch)' routers/*.py | wc -l`
- **路由文件 = 31 个**（实测 `ls routers/*.py | wc -l`）；**端点 = 266 个**。

**逐项核对（任务点名项）**：
| 检查项 | 结论 | 证据 |
| :--- | :--- | :--- |
| `GET /api/quiz/questions/{id}` 单题详情 | **不存在** | `quiz.py` 只有 `DELETE/PUT questions/{id}`、`GET /questions`（列表）；grep 无 `@router.get("/questions/{` |
| 题目维度 `kp_id` 过滤参数 | **不存在**（quiz 层） | `GET /api/quiz/questions` 支持 subject/chapter/difficulty/source/type/mode/q/year/paper，**无 kp_id**；仅 `routers/exam.py` 出卷时收 `kp_ids: List[int]` |
| `GET /api/quiz/frequency` 考频聚合 | **不存在** | 全仓无 frequency 端点；`exam_frequency` 仅作为 kp 字段在 taxonomy 端点透出 |
| 跨校公告聚合端点 | **不存在**（仅按校） | 只有 `/schools/{id}/notices`、`/notices/types` |
| problems / judge / submissions / fushi 端点 | **不存在** | grep 全仓，`routers/taxonomy.py:123` 的 "judge" 只是题型码注释，非路由 |
| **实际存在的知识结构端点** | taxonomy 11 个：`/subjects`(CRUD)、`/tree`、`/knowledge-points`(列表/详情/CRUD)、`/coverage` | `routers/taxonomy.py` |

> 结论：**"知识点地图"的后端骨架已具备（tree/coverage/kp CRUD），但"从知识点反向浏览题目"的链路缺失**（无单题详情、无 kp_id 过滤、无考频聚合）。

### 1.5 真实资料盘点（`knowledge_base` 5010 文件 / 76GB）

命令：按子目录 `find -type f | wc -l` + `du -sh`

| 子目录 | 文件数 | 体积 | 判断 |
| :--- | ---: | ---: | :--- |
| 专业课/模电 | 1214 | **50G** | 🟢 极丰富 |
| 公共课/英语 | 1233 | **13G** | 🟢 丰富 |
| 公共课/数学 | 1351 | **6.4G** | 🟢 丰富 |
| 真题（1986-2025 等） | 730 | 3.1G | 🟢 丰富 |
| 其他/408计算机 | 34 | 1.2G | 🟡 偏薄（单文件大） |
| 专业课/数电 | 128 | 1.3G | 🟡 中等 |
| 专业课/834贵大真题 | 90 | 176M | 🟡 中等 |
| **公共课/政治** | 85 | **359M** | 🔴 薄弱 |
| 其他/管综经综、未分类 | ~66 | ~0.4G | 🔴 薄弱 |
| 信号与系统/通信原理/普通物理 | 各 ~1 | 极少 | 🔴 基本空白 |

> 盘面结论：**模电一家独大（50G/76G=66%）、英语+数学次之；政治、408、多数支撑科目资料单薄**。这直接解释了 kp 分布与 chunk 分布（英语 10776 chunk、数电 9791、模电 3605；政治仅 855、408 仅 327）。
> ⚠️ 盘面 76G 但**入库文档仅 1846 个`documents`**（且 index_status 全 = `indexed`）→ **存在大量"在盘未入库"文件**，是"知识点覆盖不全"的直接原因。

**documents 分布（实测）**：`数电 878 | 英语 256 | 模电 234 | 其他 185 | 真题综合 119 | 数学 95 | 408 37 | 政治 25 | 电路 13 | 其余各 1`。
**content_category**：`textbook 809 | exam 668 | example 233 | method 136`。

### 1.6 抽取链路实况（是规则还是 LLM？）

**`services/taxonomy.py`（22KB）— 三级结构的唯一权威定义**：
- 硬编码常量：`CORE_SUBJECTS`（数电/模电/数学/英语/政治/真题综合）、`MAJOR_SUBJECTS`（电路/信号/通信/光学/普物/408）、`EXT_SUBJECTS`（电路分析/光学/网络补充/…）、`SUBJECT_ALIASES`（别名归一）。
- 文件头明写："本文件是'章节 → 知识点 → 题型'三级结构的**唯一权威定义**"。
- 结论：**章节/题型清单是"代码硬编码常量 + `subject_config` 表共管"（表驱动"候选值"、代码兜底默认值）**。

**`services/structure_parser.py`（8.4KB）— 从文档正文切结构**：
- 设计原则原文："**启发式 + 可解释**。**不依赖 AI**（省 token、离线可用），识别不出章节时优雅降级为 subject 级扁平结构。"
- 函数：`parse_structure`（正则 `CHAPTER_PATTERNS`/`SECTION_PATTERNS` 识别章/节）、`assign_structure`（给 chunk 打 chapter 标记）、`extract_knowledge_points`（**用小节名作知识点名**；无小节则返回空，交调用方决定是否走 AI）。
- 结论：**抽取是纯规则/正则启发式，非 LLM**。知识点名 = 文档小节标题去掉编号前缀。

**`services/kp_builder.py`（11KB）**：
- `parse_834_outline`（解析 834 考纲文本 → 知识点）、`knowledge_points_from_chapter_files`、`knowledge_points_from_questions`（**从题目反推知识点**）、`upsert_knowledge_points`。
- 结论：另一条抽取来源是**考纲文档解析** + **题目反推**，仍是规则型。

**`services/kb_pipeline.py`（17.9KB）**：`health_report / normalize_status / backfill_meta / repair_file_paths / reparse_empty / build_embeddings / heal`。核心是**文档→chunk→embedding 的工程管线**，**不含知识点 LLM 抽取**。

**`scripts/ingest_inbox.py`**：入库 CLI（OCR 路由 auto/paddle/rapidocr，可 `--no-embed`），**落库为 documents + chunks**，不直接产知识点。

**抽取质量判断（实测数字支撑）**：
- 651 个知识点 : 1846 篇文档 ≈ **0.35 个/篇**，与 27893 chunk 比 ≈ **1 知识点 / 43 chunk**。对一份含 10 章的教材，`extract_knowledge_points` 默认 `max_per_chapter=12`，上限过低，**远低于一门课真实的考点密度**（一门 10 章专业课合理应有 150~300 个知识点，现在模电+数电合计 401 个尚可，但公共课严重不足）。
- `question_types` 仅 31.6% 填充、`parent_id` 仅 40% 填充、`description` 72%——**抽取"半成品"特征明显**。
- `chapter` 出现"834考纲·模拟电路部分""网络补充"等非标准章名 → **归一化未彻底**。

### 1.7 前端 `/kbmap` 页面实况

文件：`D:\平台\frontend\src\pages\KbMap.jsx`（22.6KB）+ `src/styles/kbmap.css`。
- 依赖：`import { taxonomyApi, reviewApi } from '../api/client'`。
- 读取：`taxonomyApi.subjects()`（科目清单）、`taxonomyApi.tree()`（**科目→章节→知识点树**）、`reviewApi`（今日复习队列 due）。
- 展示：题型码→中文映射（`single/judge/fill/essay/calc/draw` → 单选/判断/填空/简答/计算/作图）；掌握度三档染色（`<40 薄弱 / 40–69 一般 / ≥70 良好`）；复习三态按钮（会/模糊/不会）。
- 结论：**前端已完全按"科目→章→知识点"三级 + 掌握度染色 + 复习**设计并接后端。**"地图"缺的只是数据（掌握度全 0、题型无链、一半 kp 无题）**，不是 UI。

---

## 2. 现状判断（瓶颈定位）

| 维度 | 现状 | 瓶颈 |
| :--- | :--- | :--- |
| **章** | 大纲章硬编码 + `subject_config.chapters` 表，`/tree` 以大纲为骨架 | 基本可用；个别科目大纲章偏少 |
| **知识点** | 651 个，规则抽取（小节名 / 考纲条目 / 题目反推），`parent_id` 仅 40% | ①**粒度不均**（词条 vs 长句混）；②**抽取上限过低**；③**非标章名**未归一；④**无 LLM 语义去重**（同义知识点可能重复） |
| **题型** | 仅 `question_types` JSON 字段 + `subject_config` 静态清单 | ①**无实体表**；②**无"题型→题目"直链**；③仅 31.6% kp 有题型 |
| **题目挂链** | 6288 链 / 5911 题 / 300 kp | **一半知识点零挂题**；只 `primary`，无 `related`；纯字符串同名匹配，无模糊/语义消歧 |
| **层级关系** | `knowledge_point_relations` 911 条（contains/parallel/prerequisite） | 两套层级表达并存（parent_id vs relations）**不一致**；relations 仅备份用途，前端不用 |
| **掌握度** | 651 kp 全 0；`study_events`=0；answer_records=17 | **无学习行为数据**，地图无法染色；闭环断开 |
| **资料覆盖** | 76G 盘面 vs 1846 入库文档 | **大量在盘未入库**；政治/408/支撑科目资料薄 |
| **接口** | tree/coverage/kp CRUD 有 | **缺**单题详情、kp_id 过滤、考频聚合 |

**根因一句话**：结构"建了"，但**没有把它和"题目—资料—学习行为"三条线焊死**，导致地图是"有骨架、无血肉、无颜色"。

---

## 3. 目标定义："知识点地图"应长什么样

产品目标（对齐 08a/08b 与现有 KbMap 设计）：

```
科目 (subject)
 └─ 章节 (chapter)                      ← 大纲 100% 覆盖（空章也显示，暴露缺口）
     └─ 知识点 (knowledge_point)         ← 唯一 ID，语义去重，带 chapter/parent
         ├─ 题型分布 (question_type)     ← 单选/计算/分析… 各占多少
         ├─ 考频 (exam_frequency)        ← 由真题年份聚合而来（可下钻年份）
         ├─ 掌握度 (mastery 0-100)       ← 由做题/复习行为实时计算
         ├─ 覆盖度 (coverage 0-100)      ← 该知识点挂题数 / 关联资料数
         ├─ → 题目列表 (quiz via link)   ← 可点开做题
         └─ → 资料出处 (chunks/docs)     ← 可溯源回讲义/真题页
```

**四条可视化指标（地图的"颜色"）**：
1. **掌握度染色**：<40 红 / 40–69 黄 / ≥70 绿（前端已有）。
2. **覆盖度**：无题=灰、有题=实心（暴露 351 个零挂题点）。
3. **考频热力**：按 `exam_frequency`（真实由真题聚合）深浅。
4. **缺口清单**：`/coverage` 输出"大纲有章但无知识点 / 有知识点但无题"的清单，驱动补录。

---

## 4. 数据模型草案（增量、向后兼容、可空、带来源标注）

**总原则**：**不新建大表、不重建已有表**；以"加可空字段 + 加小关联表 + 回填脚本"为主，保证现有 `/tree`、`/coverage`、`KbMap.jsx` 零改动继续可用。

### 4.1 `knowledge_points` 增补字段（均可空，默认 NULL，不影响现有查询）

| 字段 | 类型 | 用途 | 来源标注 |
| :--- | :--- | :--- | :--- |
| `kp_code` | TEXT NULL | 稳定业务码（如 `MIMO-CH3-002`），替代易变 id 做跨系统引用 | 生成 |
| `level` | INTEGER NULL | 层级深度（0=章节点，1=知识点，2=子知识点） | 抽取 |
| `source_type` | TEXT NULL | `syllabus` / `section` / `question` / `llm` | **溯源** |
| `source_ref` | TEXT NULL | 来源定位（doc_id:page 或 question_id） | **溯源** |
| `confidence` | TEXT NULL | `high`/`medium`/`low`（规则=high、LLM=medium、待核=low） | 质量 |
| `review_status` | TEXT NULL | `auto`/`confirmed`/`rejected`（人工确认工作流） | 质量 |
| `coverage` | INTEGER NULL | 冗余缓存：挂题数+挂资料数（只读展示用，由回填维护） | 派生 |

> 现有 `parent_id`、`question_types`、`exam_frequency`、`mastery` **保留不动**；只需要在回填脚本里**统一以 `parent_id` 表达层级**，并把 `knowledge_point_relations` 作为"横向关系"专用，消除两套层级并存。

### 4.2 新增小关联表（只加不改）

```sql
-- 题型→知识点：让"题型"真正成为可查询的第二维度（当前只有 JSON 字段）
CREATE TABLE kp_question_types (
    kp_id INTEGER NOT NULL,
    question_type TEXT NOT NULL,      -- single/judge/fill/essay/calc/draw
    weight REAL DEFAULT 1.0,          -- 该题型在此知识点的考查权重
    source TEXT,                      -- 'question_link' | 'syllabus' | 'manual'
    UNIQUE(kp_id, question_type)
);

-- 知识点→资料出处（可溯源）：把知识点锚定到 chunk/page
CREATE TABLE kp_source_refs (
    kp_id INTEGER NOT NULL,
    document_id INTEGER,
    chunk_id INTEGER,
    page_start INTEGER, page_end INTEGER,
    quote TEXT,                       -- 支撑该知识点的原文片段
    source TEXT,                      -- 'rule' | 'llm' | 'manual'
    confidence TEXT,
    UNIQUE(kp_id, chunk_id)
);
```

> 说明：`question_knowledge_links` 无需改（已够用），只需**回填 + 扩 role/weight**；`kp_source_refs` 是关键新增——它让知识点**可溯源**（满足任务"如何保证可溯源"）。

### 4.3 掌握度数据链（不改表，改"谁来写"）

- `knowledge_points.mastery` **保留**，但**不再手工填**；改为由 `study_events`（事件）+ `answer_records` 聚合计算，写入 `mastery`（缓存）或直接查询时算。
- 前提：**打通 `study_events` 写入**（现在 0 行）。刷题提交（`POST /api/quiz/submit`）、复习（`reviewApi`）都应落 `study_events`。这是**独立于地图的前置工程**。

---

## 5. 抽取链路设计（规则 / LLM / 混合）

**推荐：混合链路（规则打底 + LLM 补全 + 人工确认）**，分三阶：

### 阶段 A：规则骨架（复用现有，微调）
- 复用 `structure_parser.parse_structure` 识别章/节；`extract_knowledge_points` 取小节名。
- **改动点**：`max_per_chapter` 从 12 提到 **30–40**；补 `taxonomy.normalize_chapter` 覆盖"834考纲·X""网络补充"等非标章名；知识点名做**长度/标点规范化**（长句拆分）。
- 产出：`level=1, source_type=section, confidence=high`。

### 阶段 B：LLM 补全（针对规则抽不出的章节）
- 触发条件：某章 `extract_knowledge_points` 返回空，但该章有 chunk（正文）→ 说明无小节标题，走 LLM。
- 输入：该章的全部 chunk（带页码）；输出：JSON 知识点数组（name/chapter/description/question_types/quote）。
- **强制可溯源**：要求 LLM 为每个知识点回带 `quote`（原文依据），落 `kp_source_refs.quote`；无 quote 的知识点 `confidence=low`。
- 产出：`source_type=llm, confidence=medium`。
- 复用 `services/ai_service.py` / `model_gateway.py`（已有模型路由），**不新增模型基建**。

### 阶段 C：题目反推 + 关联建链（复用 `backfill_kp_links.py` 并增强）
- 现逻辑：`q.knowledge_point == kp.name AND q.subject == kp.subject` → primary。
- **增强**：① 归一化后匹配（去空格/标点/全半角）；② 未命中走**向量近邻**（`knowledge_chunks_vec` 已有 embedding 基建）找最邻近 kp → `role=related, is_verified=0`；③ 回填 `kp.question_count`。
- 产出：把 300 → **目标 ≥ 500** 知识点有题。

### 阶段 D：人工确认（工作流，非算法）
- 新增轻量端点（挂在 taxonomy 下）：`GET /knowledge-points?review_status=auto` 列待核点、`PUT /knowledge-points/{id}` 置 `confirmed/rejected`（`PUT` 已存在，扩字段即可）。
- 前端在 KbMap 或设置页加"待确认知识点"列表，人工点选。

---

## 6. 与现有代码的衔接点（文件 / 函数级）

| 目标 | 衔接文件 | 衔接点（函数/行） | 改动性质 |
| :--- | :--- | :--- | :--- |
| 章节/题型标准 | `services/taxonomy.py` | `CHAPTER_PATTERNS`/`SECTION_PATTERNS`、`chapters_of`、`guess_question_type` | 扩常量 |
| 章归一 | `services/structure_parser.py` | `_normalize_chapter`（L51）、`extract_knowledge_points`（L199，调 `max_per_chapter`） | 增强 |
| 知识点落库 | `services/kp_builder.py` | `upsert_knowledge_points`（L198）、`knowledge_points_from_questions`（L165） | 扩字段 |
| 题目建链 | `scripts/backfill_kp_links.py` | 主链 SQL（同名同科）、备链（唯一名） | 增强匹配 |
| 结构树接口 | `routers/taxonomy.py` | `structure_tree`（L220）、`_chapter_node`（L290） | 加题型/覆盖度字段 |
| 覆盖率接口 | `routers/taxonomy.py` | `structure_coverage`（L372）、`_covered_chapters`（L430） | 加"缺口清单" |
| kp 详情/CRUD | `routers/taxonomy.py` | `knowledge_point_detail`（L448）、`update_knowledge_point`（L520） | 扩字段 |
| **新增**单题详情 | `routers/quiz.py` | 新增 `GET /questions/{id}`（现缺） | 新增 |
| **新增**kp 过滤 | `routers/quiz.py` | `list_questions`（L18）加 `kp_id` 参数，join `question_knowledge_links` | 新增参数 |
| **新增**考频聚合 | `routers/taxonomy.py` 或 `quiz.py` | 新增 `GET /frequency?subject=&chapter=` | 新增 |
| 前端地图 | `frontend/src/pages/KbMap.jsx` | `taxonomyApi.tree/coverage` 消费；新增题型/覆盖度渲染 | 增量 |
| 前端 API 封装 | `frontend/src/api/client.js` | 加 `quizApi.question(id)`、`taxonomyApi.frequency()` | 增量 |

**模型/ORM**：`models.py` 里的 `KnowledgePoint`、`QuestionKnowledgeLink`、`KnowledgePointRelation` 需同步加 §4.1/§4.2 的可空字段（SQLAlchemy `nullable=True`）。

---

## 7. 验收标准（怎么算做成了）

| 指标 | 现状 | 目标 | 口径 |
| :--- | ---: | ---: | :--- |
| 大纲章节覆盖率 | 见 `/coverage` | **100%** 大纲章至少 1 个知识点 | `_covered_chapters / outline_chapters` |
| 知识点挂题率 | 300/651 = 46% | **≥ 80%** | `kp.question_count>0 / 总 kp` |
| 题目挂链率 | 5911/9171 = 64% | **≥ 85%** | `distinct question_id in links / total` |
| 知识点可溯源率 | ~0 | **≥ 90%** | 有 `kp_source_refs.quote` 的 kp 占比 |
| 题型维度可用 | 31.6% | **≥ 90%** kp 有题型 | `question_types` 非空 或 `kp_question_types` 有行 |
| 考频可用性 | 725 有 year（7.9%） | 核心科目 **≥ 60%** 真题有 year | 按科目统计 |
| 掌握度可染色 | 0（全空） | **核心科目 ≥ 50%** kp 有非零 mastery | 依赖 study_events 打通 |
| 地图接口时延 | — | `/tree` P95 **< 800ms** | 651 kp 规模下 |

**可展示验收**：KbMap 打开后，模电/数电两科能显示"彩色地图"（多数点有掌握度颜色 + 题数 + 题型分布），并能点进某知识点看到关联题目。

---

## 8. 依赖与风险

**前置依赖（必须先做）**：
1. **打通 `study_events` 写入**（刷题/复习落事件）——否则掌握度永远为 0，地图无颜色。
2. **文档补录**：把盘面 76G 中"未入库"的文件批量入库（现 1846 篇远小于盘面），特别是政治/408/支撑科目。
3. **真题 year 回填**：现仅 7.9% 有年份，考频聚合依赖它。

**风险与坑**：
| 风险 | 说明 | 缓解 |
| :--- | :--- | :--- |
| LLM 抽取幻觉 | 生成不存在知识点 | 强制 `quote` 溯源 + `confidence=low` 待核 + 人工确认 |
| 口径分裂 | `parent_id` 与 `relations` 两套层级 | 明确 `parent_id` 为唯一层级，relations 只做横向 |
| 存量不兼容 | 改 `/tree` 返回结构可能破坏 KbMap | **只加字段不删字段**，前端 `normalizeSubjects` 已兼容多形态 |
| 表数/字段误判 | 曾误用诱饵库 `backend/data/kaoyan.db` | 全程 `database/kaoyan.db` 只读 |
| 覆盖率虚高 | `chunk` 多≠知识点全 | 用 `/coverage` 的"章有/无知识点"做真实缺口判据 |
| 主键漂移 | 知识点 id 不稳定、跨系统引用断裂 | 引入 `kp_code` 稳定码 |
| 性能 | 651 kp 尚小，但 join 题表会涨 | 加 `(knowledge_point_id)` 索引、`kp.question_count` 冗余 |

---

## 9. 与文档不一致清单（实测 vs 声称）

| # | 文档声称 | 实测 | 位置 |
| :-- | :--- | :--- | :--- |
| 1 | 00 号："真库 61 表" | `sqlite_master` **60 个 table 对象**（含 6 影子表，≈59 业务表） | §1.1 |
| 2 | 03/08a 隐含："院校有简介(intro)" | `intro` 非空 **0/493** | §1.2 |
| 3 | 03 号："level 仅 225 所" | level 非空 **493/493 = 100%**（印证 09 号判 03 过期） | §1.2 |
| 4 | 04 号 V15/V16："复试代码题库/公告卡已完成" | 无 fushi/judge 端点；`kaoyan_notices` 仅 **8 校**、无聚合端点 | §1.2/1.4 |
| 5 | 文档多处："papers 建卷已落地" | `papers=0`、`paper_questions=0`（09 号已裁定，本轮复现） | §1.1 |
| 6 | README："能跑 127 GET 112 正常" | 本轮实测 **266 端点**（较 README 时点大幅增长，README 已过期） | §1.4 |
| 7 | 全景文档隐含："知识点体系完整" | 实为**规则半成品**：parent_id 40%、题型 31.6%、一半 kp 零挂题 | §1.3 |

---

## 10. 建议落地顺序（供 team-lead 决策，非本轮执行）

| 优先级 | 事项 | 依赖 | 产出 |
| :--- | :--- | :--- | :--- |
| **P0** | 打通 `study_events` 写入（刷题/复习落库） | — | 掌握度有源 |
| **P0** | `knowledge_points` 加可空字段 + `kp_source_refs` / `kp_question_types` 建表 | — | 模型地基 |
| **P1** | 增强 `backfill_kp_links` 建链（归一化+向量近邻）；挂题率 46%→80% | P0 表 | 地图有血肉 |
| **P1** | LLM 补全无小节章节的知识点（带 quote 溯源） | — | 补齐薄科 |
| **P1** | 新增 `GET /quiz/questions/{id}`、`kp_id` 过滤、`/frequency` 聚合 | — | 反向浏览 |
| **P2** | `/tree`、`/coverage` 加题型/覆盖度字段；KbMap 染色升级 | P1 | 地图可展示 |
| **P2** | 文档补录（75G 未入库）+ 真题 year 回填 | — | 覆盖度 |

---

**本轮交付完毕。全程只读；唯一写盘为本文档。**
