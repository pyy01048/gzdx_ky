---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b229e9f4d488c81cbf8c9cf190463897_1d48a073c31911f1a05452540064ee0f
    ReservedCode1: 0WFQLj4dpQThiPPyRAJ1aUHhzNcd8sdma7DXggnC8LBFbZqiZzr4Kzw9iLko1+n4urE90DT12WdxXNf4sc7T3H1YHKMBzZfa1wNXX7XLLImzMZ7wmNMkqvfqmEBIEzryEcK8H++zdFR0Cd019DszuW2VfbvIu3/549eIaCn2Obv2T7u3EiKoINQHpjQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b229e9f4d488c81cbf8c9cf190463897_1d48a073c31911f1a05452540064ee0f
    ReservedCode2: 0WFQLj4dpQThiPPyRAJ1aUHhzNcd8sdma7DXggnC8LBFbZqiZzr4Kzw9iLko1+n4urE90DT12WdxXNf4sc7T3H1YHKMBzZfa1wNXX7XLLImzMZ7wmNMkqvfqmEBIEzryEcK8H++zdFR0Cd019DszuW2VfbvIu3/549eIaCn2Obv2T7u3EiKoINQHpjQ=
---

# 模块 B：数据库与表结构（DDL/迁移）执行报告

执行日期：2026-10-08
数据库：D:\平台\database\kaoyan.db（.env 中 DATABASE_PATH）
数据库备份：temp\backup_20261008\kaoyan.db.bak（271,400,960 字节，含 WAL checkpoint 后最新数据）

---

## B1 quiz_questions 补 10 列

**DDL（幂等，若列已存在则跳过）：**

```sql
ALTER TABLE quiz_questions ADD COLUMN year INTEGER;
ALTER TABLE quiz_questions ADD COLUMN paper TEXT;
ALTER TABLE quiz_questions ADD COLUMN external_id TEXT;
ALTER TABLE quiz_questions ADD COLUMN source_paper TEXT;
ALTER TABLE quiz_questions ADD COLUMN source_page INTEGER;
ALTER TABLE quiz_questions ADD COLUMN question_no INTEGER;
ALTER TABLE quiz_questions ADD COLUMN confidence TEXT DEFAULT 'medium';
ALTER TABLE quiz_questions ADD COLUMN answer_type TEXT DEFAULT 'objective';
ALTER TABLE quiz_questions ADD COLUMN is_available INTEGER DEFAULT 1;
ALTER TABLE quiz_questions ADD COLUMN quality TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_q_external ON quiz_questions(external_id);
```

**行数对比：** 1871 行（迁移前后不变，仅加列）
**验证：** 列数 15 → 25，10 列全部就位，唯一索引建立成功。

---

## B2 创建 question_knowledge_links（题目 ↔ 知识点多对多链路）

**DDL：**

```sql
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
);
CREATE INDEX idx_qkl_kp ON question_knowledge_links(knowledge_point_id);
CREATE INDEX idx_qkl_q ON question_knowledge_links(question_id);
```

**验证：** 表已创建，初始 0 行（数据由后续模块填充）。

---

## B3 创建 study_events（学习行为事件埋点）

**DDL：**

```sql
CREATE TABLE study_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    subject TEXT,
    chapter_id INTEGER,
    knowledge_point_id INTEGER,
    question_id INTEGER,
    session_id INTEGER,
    is_correct INTEGER,
    duration_seconds INTEGER,
    payload TEXT,
    occurred_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ev_time ON study_events(occurred_at);
CREATE INDEX idx_ev_type ON study_events(event_type, occurred_at);
CREATE INDEX idx_ev_q ON study_events(question_id);
```

**验证：** 表已创建，初始 0 行。

---

## B4 创建 milestones（规划体系里程碑）

**DDL：**

```sql
CREATE TABLE milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    start_date DATE,
    end_date DATE,
    importance INTEGER DEFAULT 2,
    action TEXT,
    pitfalls TEXT,
    is_active INTEGER DEFAULT 1,
    UNIQUE (year, name)
);
```

**验证：** 表已创建，初始 0 行。18 节点里程碑数据（报告 §8.1）待后续模块按 2027 当年日期填充。

---

## B5 knowledge_chunks 在线补 3 列（B5 在线加列，未重建表）

**DDL：**

```sql
ALTER TABLE knowledge_chunks ADD COLUMN page_start INTEGER;
ALTER TABLE knowledge_chunks ADD COLUMN page_end INTEGER;
ALTER TABLE knowledge_chunks ADD COLUMN summary TEXT;
```

**行数对比：** 迁移期间行数 25,987 → 26,040 → 26,052 → 26,264（后台全量入库进程 PID 53704 持续写入，在线加列未中断其写入，行数持续增长）。
**验证：** 列数 7 → 10，3 列全部就位，未使用重建表方式，进程写入未受影响。

---

## B6 universities.score_lines JSON → kaoyan_scorelines，废弃 universities

**迁移明细：**

| 院校 | kaoyan_schools id | 迁移分数线（年：总分线） |
|---|---|---|
| 北京大学 | 146（已存在） | 2022:340 / 2023:345 / 2024:350 |
| 浙江大学 | 15（已存在） | 2022:335 / 2023:340 / 2024:345 |
| 贵州大学 | 164（已存在） | 2022:273 / 2023:273 / 2024:273 / 2025:273 |
| 清华大学 | 223（本次补入） | 2022:350 / 2023:355 / 2024:360 |
| 复旦大学 | 224（本次补入） | 2022:338 / 2023:342 / 2024:348 |

**迁移 SQL 逻辑：**

```sql
INSERT INTO kaoyan_scorelines (school_id, major_id, year, total_line, line_type, created_at)
VALUES (?, NULL, ?, ?, 'school', CURRENT_TIMESTAMP);
ALTER TABLE universities RENAME TO universities_legacy;
```

**行数对比：** kaoyan_scorelines 0 行 → 16 行；kaoyan_schools 222 行 → 224 行（补入清华大学、复旦大学）；universities 5 行 → 已改名 universities_legacy（5 行保留，可回退）。
**废弃方式：** RENAME 保留（非 DROP），数据仍可回退恢复。

---

## 后端代码同步清单

| 文件 | 修改内容 |
|---|---|
| models.py | 删除 University 模型；QuizQuestion 补 10 列；新增 QuestionKnowledgeLink / StudyEvent / Milestone 模型；KnowledgeChunk 补 3 列 |
| main.py | 移除 University import 与 universities 种子块（种子逻辑不再写已废弃表） |
| routers/goals.py | GET /api/goals/university、POST /api/goals/university/search、GET /api/goals/strategy 数据源由 University 表迁移至 kaoyan_schools + kaoyan_scorelines，响应结构保持 186 接口不变（type←level、city←city/province，major_name/admission_ratio/difficulty 返回 null） |

**代码备份：** temp\backup_20261008\models.py、main.py、routers_goals.py、schemas.py

---

## 验证结果

| 检查项 | 结果 |
|---|---|
| 数据库结构（25 列 quiz_questions / 10 列 knowledge_chunks / 3 新表 / universities 废弃） | 通过 |
| 迁移数据（16 条分数线、2 所院校补入、universities_legacy 保留 5 行） | 通过 |
| SQLAlchemy 模型导入（models / routers.goals） | 通过 |
| pytest 全套测试 | **149 passed**（186 接口未破坏） |
| 后台进程 PID 53704 写入 | 未中断（knowledge_chunks 行数持续增长） |
*（内容由AI生成，仅供参考）*
