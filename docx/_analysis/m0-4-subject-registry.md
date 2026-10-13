# M0-4 学科统一收口（Subject Registry）

> 依据 `docx/11` §5.1 方案 A（零数据迁移）。目标：把 `subject_config` 字典确立为**唯一权威**，
> 让分散的 4 个 `/subjects` 端点口径一致，且**不破坏任何既有响应契约**。

## 一、问题（改造前实测）

`subject_config` 表（24 行内置字典）本应是唯一权威，但 4 个 `/subjects` 端点各查各的业务表：

| 端点 | 原数据源 | 问题 |
|------|----------|------|
| `routers/quiz.py:605` | `quiz_questions.subject` group by | 看不到字典里"已配置但无题"的科目 |
| `routers/papers.py:41` | `quiz_questions.subject` group by | 同上 |
| `routers/documents.py:117` | `documents.subject` group by | 口径与题库页不一致 |
| `routers/taxonomy.py:22` | `SubjectConfig` 表 + 自算计数 | 已是超集，但计数逻辑与其他页复制粘贴、易漂移 |

结果：同一"科目集合"在不同页面看到的不一样；字典配好但未录数据的科目（如 **0854 电子信息**）在题库/资料页不可见；
业务表里出现过但字典没有的**脏科目**（真库实测有 `专业课`：4 题 / 3 条活跃错题）被静默漏掉。

## 二、方案（零数据迁移，最小变更）

新增 `services/subject_registry.py` 作为**唯一科目聚合器**：

- **科目集合** = `subject_config` 字典全部行（唯一权威）
  **+** 业务表里出现过但字典没有的科目（以 `unregistered=True` 带出，**不漏数据**）。
- 计数口径：`question_count`（`quiz_questions`）、`error_count`（`error_records`，仅 `status='active'`）、
  `document_count` / `chunk_count`（`documents` / `knowledge_chunks`）。
- 播种：先 `taxonomy.ensure_subject_config_seeds(db)`（仅空库首建，不复活已删行），
  再对存量非空库**定向补种 M0-4 新增的 4 个工科科目**（仅当表里确实没有该名），
  最后 `taxonomy.load_configured_subjects(db)` 刷新缓存。
- **不新增数据库列、不迁移数据**（新科目 `question_count=0` 属正常）。

### 0854 覆盖

核对发现：`kaoyan_subjects` 表有 8 个工科学科（0803/0808/0809/0810/0811/0812/0835/0854），
但 `taxonomy.EXT_SUBJECTS` 只对齐了其中 4 个（0808/0809/0811/0835），**缺 0803 光学工程、0810 信息与通信工程、
0812 计算机科学与技术、以及 0854 电子信息（专硕）**。

处理：以**新增种子**方式补入 `taxonomy`（`EXT_SUBJECTS` + `CHAPTERS` + `QUESTION_TYPES`），
不手改数据库、不复活已删行。补后 `taxonomy.ALL_SUBJECTS` 由 24 → 28。

## 三、改动文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `services/subject_registry.py` | **新增** | 唯一科目聚合器：`list_subjects` / `subject_filter_list` / `unregistered_subjects` / `ensure_subject_registry_seeds` |
| `services/taxonomy.py` | 修改 | `EXT_SUBJECTS` 增补 4 个工科；`CHAPTERS` / `QUESTION_TYPES` 补对应条目（合计 24→28 科目） |
| `routers/taxonomy.py` | 修改 | `GET /subjects` 的 `subjects` 字段改由注册器生成；移除冗余查询；清理无用 import |
| `routers/quiz.py` | 修改 | `GET /api/quiz/subjects` 数据源改注册器，**响应结构不变** |
| `routers/papers.py` | 修改 | `GET /api/papers/subjects` 数据源改注册器，**响应结构不变** |
| `routers/documents.py` | 修改 | `GET /api/documents/subjects` 数据源改注册器，**响应结构不变** |

**全部改动不触碰前端**：现有 `Quiz.jsx` / `KbMap.jsx` / `SubjectManager.jsx` 不改也能正常显示。

## 四、向后兼容性（硬承诺）

| 端点 | 保持不变的响应结构 |
|------|-------------------|
| `GET /api/quiz/subjects` | `{"total": N, "items": [{"subject", "question_count", "error_count"}]}` |
| `GET /api/papers/subjects` | `{"items": [{"subject", "count"}]}` |
| `GET /api/documents/subjects` | `{"total_documents", "total_chunks", "subjects": [{"name", "document_count", "chunk_count"}]}` |
| `GET /api/taxonomy/subjects` | `subjects` + 旧字段 `core` / `extension` / `question_type_pool` / `doc_types` 全保留 |

## 五、验证命令与输出

### 5.1 四端点科目集一致性（真库 `D:\平台\database\kaoyan.db`）

```bash
cd D:/平台/backend-main-fastapi
"D:/Anaconda/python.exe" -c "
import asyncio
from database import SessionLocal
from routers import taxonomy, quiz, papers, documents
db = SessionLocal()
j1 = asyncio.run(taxonomy.list_subjects(db=db))
j2 = asyncio.run(quiz.quiz_subjects(db=db))
j3 = asyncio.run(papers.paper_subjects(db=db))
j4 = asyncio.run(documents.list_subjects(db=db))
s1={s['subject'] for s in j1['subjects']}; s2={s['subject'] for s in j2['items']}
s3={s['subject'] for s in j3['items']}; s4={s['name'] for s in j4['subjects']}
print('counts:', len(s1), len(s2), len(s3), len(s4), 'ALL_EQUAL=', s1==s2==s3==s4)
print('0854 电子信息 in set:', '电子信息' in s1)
"
```

**输出：**

```
counts: 29 29 29 29 ALL_EQUAL= True
0854 电子信息 in set: True
```

> 29 = 24 原有字典 + 4 新增工科（电子信息/信息与通信工程/计算机科学与技术/光学工程）+ 1 未登记脏科目（`专业课`）。

### 5.2 未登记脏科目被带出（不漏数据）

```bash
"D:/Anaconda/python.exe" -c "
from database import SessionLocal
from services import subject_registry
db = SessionLocal()
print(subject_registry.unregistered_subjects(db))
"
# 输出：['专业课']   （真库中：4 题、3 条活跃错题）
```

### 5.3 pytest

```bash
"D:/Anaconda/python.exe" -m pytest tests/test_taxonomy_subjects.py -q
# 8 passed
```

全量：`"D:/Anaconda/python.exe" -m pytest tests/ -q`

```
320 passed, 1 skipped, 1 xfailed, 21 warnings in 206.17s (0:03:26)
```

> 改造前基线为 `319 passed + 1 failed`（该 fail 正是 `test_seed_idempotent_and_builtins_present`，
> 因注册器一度带出未纳入 `ALL_SUBJECTS` 的新工科所致）。将 4 个工科加进 `taxonomy.ALL_SUBJECTS`
> 后，**320 全绿**。末尾的 `PermissionError ... pytest-current` 是 Windows pytest 临时目录清理的
> 既有怪癖（atexit 阶段），与本次改动无关，进程退出码为 0。

## 六、遗留问题 / 需前端配合确认

1. **新科目在 `SubjectManager.jsx` 新增后是否其它页可见**：由于四端点已统一走注册器，
   在科目管理页新增一个自定义科目后，`quiz/papers/documents` 三页**无需改动**即可看到
   该科目（`question_count=0`）。建议前端验收：在科目管理页新增一个自定义科目 → 刷新
   刷题中心/组卷/资料页，确认科目出现在筛选下拉。
2. **`专业课`（未登记脏科目）**：注册器已带出（`unregistered=True`）避免漏数据；
   如需归一，建议由数据侧决定（本任务遵循"零数据迁移"，**未**改写任何业务表科目标签）。
3. **`routers/kaoyan.py` 的 `/api/kaoyan/subjects`** 走独立的 `kaoyan_subjects` 学科表
   （择校数据中心的学科分类，语义不同），**未纳入**本次收口，属预期。
4. 本任务**未**新增数据库列、**未**迁移数据、**未**使用 `git add -A`。

## 七、备份

改前已备份真库：`database/kaoyan_backup_before_m0-4_registry_20261012_002320.db`。
