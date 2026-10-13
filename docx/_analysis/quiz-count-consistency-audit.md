# 题库计数点核查：`is_junk` 口径一致性（M1-1g）

> 目标：找出全项目"直接 count 全量题目"的地方，判定哪些**用户可见统计**需排除
> `is_junk=1`、哪些是**内部审计**不需排除。数据库 `D:\平台\database\kaoyan.db`。

## 0. 背景
M1-1f 已把 319 条 OCR 碎片题标记 `is_junk=1`。列表端点 `GET /api/quiz/questions`
已默认排除。若不统一口径，会出现"题库总数 9171 但可刷 8852"的前后端不一致。

## 1. 已修复（本轮）
| 位置 | 端点 | 修复 |
|---|---|---|
| `routers/quiz.py` `quiz_stats` | `GET /api/quiz/stats` | `total_questions` + `subject_distribution` 排除 `is_junk=1`；新增 `include_junk` |
| `routers/quiz.py` `list_questions` | `GET /api/quiz/questions` | 改用共享过滤；`include_junk` |
| `routers/quiz.py` `quiz_frequency` | `GET /api/quiz/frequency` | paper/chapter/kp 三维题数均排除 junk；新增 `include_junk` |
| `routers/quiz.py` `papers_index` | `GET /api/quiz/papers-index` | 套卷题数/科目分布排除 junk；新增 `include_junk` |
| `routers/quiz.py` `years_index` | `GET /api/quiz/years` | 年份×科目题数排除 junk；新增 `include_junk` |
| `routers/quiz.py` `quiz_sections` | `GET /api/quiz/sections` | 章节题数排除 junk；新增 `include_junk` |
| `services/subject_registry.py` `_count_by_subject` | `GET /api/quiz/subjects` 等 | 新增 `exclude_junk=True`（默认），题目科目计数排除 junk |

**共享 helper**：新增 `services/quiz_query.visible_quiz_filter(query, include_junk=False)`，
列表与各统计端点统一调用，杜绝口径再漂移。

## 2. 真库实测对照表（排除 junk 前 → 后）
> 注：实测时库总题数为 9174（另一工程师并发导入了 3 题），junk=319，非 junk=8855。

| 端点 | 指标 | 含 junk（修前口径） | 排除 junk（修后默认） | 差值 |
|---|---|---:|---:|---:|
| `GET /api/quiz/questions` | total（全库） | 9174 | **8855** | −319 |
| `GET /api/quiz/questions` | total（模电） | 5008 | **4863** | −145 |
| `GET /api/quiz/stats` | total_questions | 9174 | **8855** | −319 |
| `GET /api/quiz/frequency?dimension=chapter` | 章节题数之和 | 5006 | **4954** | −52 |
| `GET /api/quiz/papers-index` | 套卷题数之和 | 3008 | **2881** | −127 |
| `GET /api/quiz/years` | 年份题数之和 | 725 | **684** | −41 |
| `GET /api/quiz/sections` | 章节题数之和 | 5006 | **4954** | −52 |
| `GET /api/quiz/subjects` | question_count 之和 | 9171* | **8855** | −316* |

\* subjects 修前口径为 9171（该端点此前基于旧快照；现随库实时）。

- 全部端点传 `include_junk=true` 时可复原"含 junk"数值，向后兼容。
- junk 中仅 52 条有 chapter、41 条有 year，故 frequency/sections 与 years 的差值为 52/41。

## 3. 全项目计数点核查结论（分类）

### 3.1 用户可见的题库统计 —— **已全部排除 junk（本轮完成）**
| 文件 | 端点/函数 | 处理 |
|---|---|---|
| `routers/quiz.py` `quiz_frequency` | `GET /frequency` | ✅ 已排除 + `include_junk` |
| `routers/quiz.py` `papers_index` | `GET /papers-index` | ✅ 已排除 + `include_junk` |
| `routers/quiz.py` `years_index` | `GET /years` | ✅ 已排除 + `include_junk` |
| `routers/quiz.py` `quiz_sections` | `GET /sections` | ✅ 已排除 + `include_junk` |
| `services/subject_registry.py` `_count_by_subject` | `GET /subjects` 等的 `question_count` | ✅ `exclude_junk=True`（默认） |

### 3.2 内部数据审计 / 非用户可见 —— **不需排除（保持全量）**
| 文件 | 用途 | 理由 |
|---|---|---|
| `services/db_optimizer.py` | VACUUM 前库体量审计 `total_questions` | 内部运维指标，应反映**物理总量** |
| `services/scheduler.py` | 定时任务"题库解析率" | 内部数据质量指标，需覆盖全部行 |
| `scripts/rebuild_knowledge_base.py`、`scripts/*` | 回填/升级脚本 | 内部工具，操作全量 |
| `tests/conftest.py`、`tests/test_kb_import.py` | 测试断言"库非空" | 测试夹具 |
| `POST /import`（导入结果 count） | 本次导入条数 | 与 junk 无关 |
| `POST /submit` | 单题提交 | 不涉及计数 |

## 4. 验证结果
- 8 处口径已在真库通过 FastAPI TestClient 实测（见 §2 对照表）；
  `include_junk=true` 均可复原全量，向后兼容。
- pytest `tests/test_quiz_put.py tests/test_api_contract.py tests/test_taxonomy_subjects.py`
  → **34 passed, 1 skipped** ✓
- 全项目原 `routers/quiz.py` 的 `or_` 局部导入已随改造清理（改用共享 helper）。
