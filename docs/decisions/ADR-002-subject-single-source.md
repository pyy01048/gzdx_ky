# ADR-002: 科目口径收敛为单一权威源

## Status

Accepted（2026-10-14）

## Background

项目里"科目"这个概念存在三张口径不一致的表，加上散落在 18 处代码里的硬编码中文科目字符串：

| 表 | 行数 | 表面用途 |
|---|---|---|
| `subject_config` | 28 | 科目 → 章节 / 题型配置 |
| `kaoyan_subjects` | 8 | 学科代码 / 门类 |
| `subject_prototypes` | 18 | 科目原型向量（用于分块学科分类） |

初看会认为这是"同一个概念的三种写法"，只要合并成一张表即可。**实测数据否定了这个前提。**

### 实测证据

`kaoyan_subjects` 的实际内容：

```
code='0803', name='光学工程',         category='工学'
code='0808', name='电气工程',         category='工学'
code='0812', name='计算机科学与技术', category='工学'
code='0854', name='电子信息(专硕)',   category='工学'
```

这是**研招网的招生学科代码**，属于"报考专业所属学科"口径，回答的是"这个专业归哪个学科门类管"。

`subject_prototypes` 的实际内容：

```
政治 / 英语 / 数学 / 电路 / 数字电子技术 / 模拟电子技术 /
信号与系统 / 通信原理 / 普通物理 / 真题综合 / 中医综合 ...
```

这是**备考科目**，回答的是"用户学什么、刷什么题"。

两者不是同一维度，且无法一一对应：例如"电路"既是电气工程（0808）的科目，也是电子科学与技术（0809）的科目。强行合并成一张表，只会把"学科门类"这一列污染成不可判定值。

`subject_config` 则是第三类问题：它把**备考科目**和**招生学科**混装在同一张表里（既有"电路"也有"电气工程"），并且存在同一概念的多种写法（`光学` / `光学与工程光学` / `光学工程`、`电路` / `电路分析`、`计算机基础` / `计算机科学与技术`）。

## Decision

**不合并成一张"万能科目表"，而是按概念拆成正交的两张权威表 + 一张映射表。**

1. `subjects` —— **备考科目**唯一权威源（教学 / 出题口径）。
   - 主键 `id BIGSERIAL`，权威引用键 `code VARCHAR(32) UNIQUE`（如 `politics` / `english` / `circuit`）。
   - 承载原 `subject_prototypes` 的科目语义 + 原 `subject_config` 的配置语义。
   - `legacy_names JSONB` 保留历史中文名数组，供 ETL 归档。
   - `parent_id` 支持"专业课 → 子模块"两级结构。

2. `disciplines` —— **招生学科**唯一权威源（原 `kaoyan_subjects` 更名对齐）。
   - 保留 `code` / `category`（工学）/ `parent_code` / `exam_overlap`。

3. `subject_discipline_links` —— 两者**多对多**映射，带 `is_primary` 用于一科对多科时的默认归类。

4. `subject_aliases` —— 收敛 18 处硬编码。别名 → 科目，**多对多**（`UNIQUE(alias, subject_id)` 而非 `UNIQUE(alias)`），因为 `数模电`（186 篇文档）同时指向"数字电子技术"与"模拟电子技术"；靠 `is_primary` 消歧。

5. **业务表全部改外键。** `documents` / `knowledge_chunks` / `knowledge_points` / `quiz_questions` / `tasks` 等均加 `subject_id BIGINT REFERENCES subjects(id) ON DELETE SET NULL`，同时保留原 `subject` 文本列作为兼容列（由 ETL 回填），让存量路由可以增量迁移而不是一次性大爆炸切换。

6. **章节独立成表** `subject_chapters`，把 `subject_config.chapters` 的 JSON 数组升级为可关联实体，支持按章节聚合统计。

### ETL 别名映射表（已实测，照此执行）

| 历史写法 | 映射到权威 code | 出现位置 |
|---|---|---|
| `公共课-数学` | `math` | documents 31 行 |
| `公共课-政治` | `politics` | documents 3 行 |
| `公共课-英语` | `english` | documents 1 行 |
| `408` | `cs408` | documents 8 行 |
| `数模电` | `digital_electronics` + `analog_electronics`（双映射） | documents 186 行 |
| `光学` / `光学与工程光学` | `optics` | subject_config |
| `电路` / `电路分析` | `circuit` | documents 22 行 |
| `电气工程` / `电子科学与技术` / `控制科学与工程` / `计算机科学与技术` / `软件工程` / `电子信息` / `信息与通信工程` / `光学工程` | 归 `disciplines`（非 subjects） | subject_config |

## Consequences

### 正面

- 科目口径从"三处各自为政"变成"一处定义、处处引用"，消除 18 处硬编码。
- 招生学科与备考科目解耦，`电路 → 电气工程 / 电子科学与技术` 这种一对多关系可以被正确表达，而不是靠猜。
- 章节从 JSON 升级为实体后，可按章节统计题目数 / 掌握度，此前做不到。

### 负面 / 代价

- **迁移期存在双写认知负担**：`subject_id` 与 `subject` 两列并存，开发时容易写错列。必须在 Phase 2 结束时移除 `subject` 兼容列，否则两套口径会重新漂移。
- `subject_aliases` 允许一个别名命中多行，解析时必须带 `is_primary` 过滤，否则会随机取到非预期科目。
- 存量 `subject_config` 里混入的学科门类数据在拆分时需要人工判定归属，无法全自动。

## Related ADRs

- ADR-001: 数据库底座从 SQLite 迁移到 PostgreSQL 17
- ADR-003: 题目标准 schema 与校验门
