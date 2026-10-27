# ADR-003: 题目标准 schema 与校验门

## Status

Accepted（2026-10-14）

## Background

`quiz_questions` 是平台的核心资产，但当前没有标准 schema。实测数据：

- **9,096 道题中 4,710 道（52%）`options` 为空**
- **184 道题选项数为 2 / 3 / 5 / 6 / 14 的错乱状态**（选择题应为 4 个）
- **题干里混进了选项**（`"A．奇偶校验码"` 这类行被写进 `content`）
- `options` 是无约束 JSON，实际存在两种格式并存：
  - 字符串数组：`["A．奇偶校验码","B．5421BCD 码"]`（997 行）
  - JSON `null`（8,099 行）

同时，"题目来源"被塞在一个字符串里用前缀表达：

```
source = '知识库:xxx'  → 7,249 行
source = '真题:xxx'    → 1,844 行
```

这种用字符串前缀承载归类语义的做法导致归类错乱：真题被标成知识库、章节题库被标成真题。

另外，`question_type` 的实际取值与文档不符。实测分布：

```
essay  3,791
single 2,030
calc   1,284
fill   1,101
judge    868
draw      22
```

**没有 `multiple`，但有 `calc` / `fill` / `draw`。** 任何按文档臆造的枚举都会把 3,000+ 道题挡在库外。

## Decision

### 1. 选项强类型化

`options` 定为 `JSONB`，规范格式固定为对象数组：

```json
[{"key": "A", "text": "选项内容"}, {"key": "B", "text": "..."}]
```

由 PostgreSQL 函数 `is_canonical_options(jsonb)` 校验，经 `CHECK` 约束强制：

```sql
CONSTRAINT ck_quiz_questions_options CHECK (is_canonical_options(options))
```

该函数要求：值为 NULL，或为长度 2-10 的数组，且每个元素都是含 `key` 与 `text` 的对象。这直接消灭 14 项错乱与"数组 / 对象混存"两类问题。

> 用函数而非内联表达式，是因为 CHECK 约束里不允许子查询与聚合，无法直接对数组逐元素校验。

### 2. 来源正交双列

不再用字符串前缀表达归类，改为两个正交、职责单一的列：

| 列 | 类型 | 职责 |
|---|---|---|
| `source_kind` | `source_kind` ENUM | **权威归位列**：`past_exam` / `textbook` / `chapter_exercise` / `mock_exam` / `ai_generated` / `user_created` / `external_import` |
| `source_label` | `TEXT` | **纯展示标签**：原始字符串去掉前缀后的剩余部分，不参与任何筛选逻辑 |

配套派生列与约束：

```sql
is_past_exam BOOLEAN GENERATED ALWAYS AS (source_kind = 'past_exam') STORED
CONSTRAINT ck_quiz_questions_past_exam_year
    CHECK (source_kind <> 'past_exam' OR year IS NOT NULL)
```

`is_past_exam` 让真题筛选可以直接走索引；"真题必须有年份"这条约束则防止归类修正后年份丢失。

历史数据迁移函数：`migrate_legacy_source_kind()`。

### 3. 分层治理：CHECK 硬拒 + 触发器软标

这是本次设计的关键取舍。**不是所有问题都该在写入时抛异常。**

- **硬拒（CHECK）** —— 结构性问题，不可协商：
  - 选项结构（`is_canonical_options`）
  - 难度 1-5
  - 年份 1980-2100
  - 答案置信度 0-1
  - 真题必须有年份

- **软标（BEFORE INSERT/UPDATE 触发器 `trg_quiz_questions_gate`）** —— 内容质量问题，写入 `validation_errors` 并置 `validation_status='warn'`：
  - 题干洁净度（`check_stem_clean`：过短 / 混入 A. B. 选项行）
  - 题型与选项一致性（`check_options_consistency`：单选题不足 4 项、主观题带选项等）
  - 缺答案 / 缺解析
  - 客观题答案置信度 < 0.8（禁止自动判分）

**理由**：存量 9,096 道题里有大量内容质量问题。若全部写成 CHECK，ETL 在导入第一步就会失败，且报错信息是"违反约束 ck_xxx"，无法直接指导修复。改为软标后，脏数据能先入库、再被 `v_question_health` 量化、再批量修，治理过程可见可控。

### 4. 枚举按实测取值定义

`question_type` ENUM 按实测分布定义，容纳 `calc` / `fill` / `draw`：

```
single | multiple | judge | fill | calc | essay | draw | proof | other
```

同时新增 `stage` 语义拆分（实测发现的隐藏冲突）：

| 枚举 | 取值 | 来源列 |
|---|---|---|
| `prep_stage` | `basic` / `intensive` / `sprint` / `retest` | `tasks.stage`（备考阶段） |
| `exam_stage` | `初试` / `复试` | `documents.stage`（考试轮次） |

两者都含"复试"但语义完全不同：前者是备考时段，后者是考试轮次。**合并会引入静默语义错误**，故拆成两个枚举。

## Consequences

### 正面

- 选项结构、难度、年份、置信度等结构性错误在库层被硬拦，不再靠应用层自觉。
- 来源归类从"字符串约定"变成"受约束的枚举列"，真题/教材题混用问题从根上消除。
- 内容质量问题可量化（`v_question_health`），治理有明确验收口径。
- 枚举按实测数据定义，不会把存量题目挡在库外。

### 负面 / 代价

- **软标不阻止脏数据入库**，只做标记。若后续无人跟进 `warn` 清零，治理等于没做。必须把"warn 数归零"作为迁移验收项。
- 触发器在每次题目写入时执行，带来轻微写入开销；批量导入 9k 道题时会有可感知的额外耗时。
- `source_label` 与 `source` 兼容列在过渡期并存，需明确谁读谁写。
- `is_past_exam` 是 `GENERATED` 列，PG 不允许手工写入，批量修数据时必须先改 `source_kind` 再让它重算。

## Related ADRs

- ADR-001: 数据库底座从 SQLite 迁移到 PostgreSQL 17
- ADR-002: 科目口径收敛为单一权威源
