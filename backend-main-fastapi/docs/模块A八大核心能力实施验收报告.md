---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: b229e9f4d488c81cbf8c9cf190463897_e9314bf7c33311f1a05452540064ee0f
    ReservedCode1: w25d5moVgqKgptJDzDrsnj9bqGGk3UaKj8QXbTven8XHyZdtDJV7cpqG0RggD9j20QK7WOZxkygH5EtgGv2Qa/A/rz53SIs+DiY3MdZKgH546jMsE/5kLGt2CWX6cfadndkvw9VGO3p7xIQal3IU+t1yTiRVFKF5J9GnNzWeLMOPT/YzopK9D/LgWfo=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: b229e9f4d488c81cbf8c9cf190463897_e9314bf7c33311f1a05452540064ee0f
    ReservedCode2: w25d5moVgqKgptJDzDrsnj9bqGGk3UaKj8QXbTven8XHyZdtDJV7cpqG0RggD9j20QK7WOZxkygH5EtgGv2Qa/A/rz53SIs+DiY3MdZKgH546jMsE/5kLGt2CWX6cfadndkvw9VGO3p7xIQal3IU+t1yTiRVFKF5J9GnNzWeLMOPT/YzopK9D/LgWfo=
---

# 模块 A 八大核心能力实施验收报告

> 实施范围：`D:\平台\backend-main-fastapi`（FastAPI + SQLite + React + Ollama 考研备考系统）
> 红线遵守：现有 186 个 HTTP 接口不变；表结构仅 ALTER ADD 列 / 新建表；启动方式保持 `uvicorn main:app --port 8000`
> 验收日期：2026-10-08

---

## 一、交付文件清单

| 模块 | 文件路径 | 说明 |
|:---|:---|:---|
| A1 | `services/analysis_engine.py`（增强，原 285 行保留做加法） | 新增 `_SUBJECT_TEMPLATES` / `_DEEP_PROMPT` / `_map_knowledge_points` / `deep_analyze_problem`（步骤分解+知识点归因+四段式讲解）/ `build_sft_entry`（SFT 友好输出，对齐 `D:\kaoyan_ai\pipeline\build_sft.py` 的 is_copy/noisy 质检口径）；原 5 个函数 `analyze_problem / recognize_problem_image / build_lecture_html / save_lecture / list_lectures` 保留继续可用 |
| A2 | `services/formula_service.py`（新建） | 强约束 prompt（行内 `\(...\)`、填空 `\underline{\quad\quad}`、形近字符/运算符/希腊字母/电路符号防控清单、`[待核对:...]` 标记、禁止猜测）；`validate_latex`（tectonic/xelatex 自动探测编译校验）；`detect_formula_regions`（孤立符号密度/高度错落启发式公式区检测）；`recognize_formula(image_path) -> {latex, validated, compile_ok, pending_flags, error}` |
| A2 路由 | `routers/formula.py`（新建） | 前缀 `/api/formula`，已注册 main.py |
| A3 | `services/retrieval_gate.py`（新建） | 双阈值门控 `evaluate_gate`（0.50/0.60，复杂问题 0.35/0.45，`RETRIEVAL_GATE_MODE="observe"` 灰度）；只信 rerank_score；四条硬规则；reason_codes 驱动 HyDE 重写 / step_back 回溯；`gate_and_retrieve` 接入 `hybrid_search_with_rerank`（只读调用不改签名）；每轮打点 `retrieval_gate_logs` |
| A4 | `services/blind_spot_pool.py`（新建） | `record_abstain` 沉淀拒答；`get_gaps` 看板；`top_gaps` 高频缺口聚合；`resolve_gap`；`get_weakest_subjects/get_weakest_kps` 薄弱点聚合供组卷 weakest 模式；`build_abstain_reply` 先给可答部分+引用再说明缺口的话术模板 |
| A5 | `services/exam_builder.py`（新建） | `load_blueprints`（4 科预置蓝图写入 exam_blueprints）；`uniform_sample_by_chapter`（按 chapter 分组轮转均匀采样）；`build_paper`（normal/weakest/random，试卷冻结：抽中题号存 config + 题目快照存 exam_answers.question_snapshot）；`submit_session`（客观题 auto 判分、主观题 ai 建议分+self 自评，统计只认 auto+self，错题回流 error_records 去重并联动盲区池）；`list_sessions/session_detail`。`services/paper_builder.py` 未删未改 |
| A5 路由 | `routers/exam.py`（新建） | 前缀 `/api/exam`：`POST /api/exam/build`、`POST /api/exam/{session_id}/submit`、`GET /api/exam/sessions`、`GET /api/exam/sessions/{id}`，已注册 main.py |
| A6 | `services/answer_cross_check.py`（新建） | `cross_check_question`（题库 answer / 2-gram 真题检索结果 / LLM 生成多来源比对）；一致性→写 `answer_candidates` 并标 confidence 0-1；来源冲突→`quiz_questions.confidence='verify'`；`check_batch` / `stats` 校验与统计入口 |
| A6 路由 | `routers/answers.py`（新建） | 前缀 `/api/answers`，已注册 main.py |
| A7 | `services/exam_engine.py`（新建） | 直接加载 `D:\真题（公共课）\专有答疑模型\index.pkl`（2712 题，docs/postings/total/doc_grams），`get_exam_index()` lru 单例挂进进程；四阶段检索（NFKC 归一→2-gram idf→BM25+长度归一+覆盖率→OCR 噪声惩罚+二次校验重排 top-60）；`find_variants`（Jaccard min_sim=0.08 top-3）；`search_with_exam` 第 4 路融合：base 三路保持 K=60、exam 用 K=20（2.9 倍权重），负 ID `-300000-doc_id`，返回 `source_type='exam_question'` 及 year/answer/analysis/variants |
| A7 融合 | `services/search_service.py`（增强，末尾追加） | 新增 `hybrid_search_with_exam(db, query, query_vec, limit, subject)` 入口，现有 `hybrid_search / hybrid_search_with_rerank` 行为不变 |
| A8 | `services/error_analyzer.py`（新建） | 四段式协议（1 考点定位→引用 knowledge_points 真实 ID；2 大纲依据；3 思路拆解；4 干扰项解析强制逐个错误选项）；错因分类（概念混淆/审题失误/计算错误/记忆缺失/方法没想到/时间不足）；`_practice_questions` 复练建议（同知识点未做错题抽取）；输出写 `error_records.analysis`、evidence 落 `misconceptions` |
| A8 接线 | `routers/errors.py` 的 `ai-analyze` 端点（增强） | 保持原返回结构 `{analysis, message}` 不变，新增四段式字段，调用 `error_analyzer.analyze_error` |
| 公共 | `services/module_a_schema.py`（新建） | 全部 DDL 幂等（CREATE TABLE IF NOT EXISTS / 列存在性检查），8 张新表 + quiz_questions 12 列 + error_records 16 列 ALTER；`ensure_blueprints()` 预置 4 科蓝图；写库带 busy_timeout + 重试 |
| 公共 | `services/db_retry.py`（新建） | `exec_retry(conn, sql, params)` 遇 `database is locked` 最多 6 次重试 |
| 公共 | `main.py`（修改，仅新增注册） | routers import 追加 formula/exam/answers；papers.router 后追加 3 个 `include_router`，现有注册与路由零改动 |

## 二、新增表清单（8 张，均 CREATE TABLE IF NOT EXISTS）

| 表名 | 用途 | 当前 COUNT |
|:---|:---|:---|
| `retrieval_gate_logs` | 检索门控每轮打点（decision/reason_codes/top1_score/topk_mean/top1_margin/distinct_doc_count/gate_mode/would_abstain/latency_ms） | 4 |
| `pending_questions` | 知识盲区池（question/have_basis/have_basis_ids JSON/gap/gap_type/suggestion/suggested_action/status/resolved_by/occurrence_count 等） | 4 |
| `exam_blueprints` | 组卷蓝图（subject/paper/section/question_type/count/score_per_question/time_limit_minutes/sort_order/kp_filters/is_active） | 8 |
| `exam_sessions` | 模考会话（config JSON 快照/total_count/total_score/correct_count/score/status 等） | 4 |
| `exam_answers` | 模考作答（question_snapshot 快照/user_answer/is_correct/ai_score/self_score/final_score/scored_by auto|ai|self/error_category） | 12 |
| `answer_candidates` | 多来源答案候选（answer/explanation/confidence 0-1/source bank|extracted|llm|user_confirmed/used_for_grading/verified_by/verified_at） | 0 |
| `misconceptions` | 结构化错因（question_id/error_record_id/knowledge_point_id/pattern/category/suggestion/evidence/synced_at） | 2 |
| `question_knowledge_links` | 题目↔知识点多对多（role/weight/is_verified） | 0 |

### ALTER 幂等新增列（列存在性检查，不重建表）

- `quiz_questions` +12 列：`year / paper / external_id / source_paper / source_page / question_no / confidence(default medium) / answer_type(default objective) / is_available(default 1) / quality / rubric / max_score`，并建 `idx_q_external` 唯一索引（IF NOT EXISTS）
- `error_records` +16 列：`knowledge_point_id / error_category / pass_number / ease_factor(2.5) / interval / repetitions / lapses / next_review / last_review / mastery_level(not_mastered) / last_status(unreviewed) / recent_weight(1.0) / prev_ease_factor / prev_interval / prev_repetitions / user_note`

### 预置蓝图（exam_blueprints，共 8 条）

| 科目 | paper | 段数 | 构成 |
|:---|:---|:---|:---|
| 数学二 | math2 | 3 | 10 选择×5 + 6 填空×5 + 6 解答×~10（满分 150） |
| 408 | cs408 | 2 | 40 选择×2 + 7 综合应用（满分 150） |
| 政治 | politics | 2 | 16 单选×1 + 17 多选×2（满分 50） |
| 英语二 | english2 | 1 | 50 词汇四选一×2（满分 100） |

## 三、新增 HTTP 接口清单（红线内新增，不影响既有 186 接口）

| 前缀 | 接口 | 说明 |
|:---|:---|:---|
| `/api/formula` | `POST /api/formula/recognize` | 公式区识别：`{image_path} -> {latex, validated, compile_ok, pending_flags, error}` |
| `/api/formula` | `GET /api/formula/compilers` | 探测可用 LaTeX 编译器 |
| `/api/exam` | `POST /api/exam/build` | 组卷：`{subject, paper, year, mode, kp_ids, question_source, exclude_recent_days}` |
| `/api/exam` | `POST /api/exam/{session_id}/submit` | 交卷判分 + 错题回流 |
| `/api/exam` | `GET /api/exam/sessions` | 会话列表 |
| `/api/exam` | `GET /api/exam/sessions/{id}` | 会话详情（含作答快照） |
| `/api/answers` | `POST /api/answers/check` | 单题多来源答案交叉校验 |
| `/api/answers` | `POST /api/answers/check-batch` | 批量校验 |
| `/api/answers` | `GET /api/answers/stats` | 答案可信度统计 |

## 四、自测结果

1. **py_compile 全量编译**：`D:\平台\backend-main-fastapi` 下 140 个 `.py` 文件，**failed=0**
2. **模块导入**：12 个新服务/路由模块（formula_service / retrieval_gate / blind_spot_pool / exam_builder / answer_cross_check / exam_engine / error_analyzer / module_a_schema / db_retry / routers.formula / routers.exam / routers.answers）全部导入 OK
3. **A1 增强**：`analysis_engine` 原 5 函数 + `deep_analyze_problem` / `build_sft_entry` 均可导入调用
4. **建表幂等**：`ensure_module_a_schema()` 可重跑；8 张新表 COUNT 如上；`quiz_questions.year/rubric/confidence`、`error_records.knowledge_point_id/error_category/ease_factor` 列存在性验证通过
5. **A7 第 4 路融合**：`hybrid_search_with_exam("2019年考研数学二求极限")` 返回 6 条含 `source_type='exam_question'`，2019 年题目经年份 +8 加权正确置顶，变式题 variants=3 正常返回；修复了两处融合 bug（exam lane ID 正负号、K 权重 20/60 分离）
6. **功能级冒烟**：A1-A8 核心调用（A3 各门控分支、A4 gaps/reply、A6 cross、A8 analyze、A5 blueprints/build/submit、A7 index/retrieve/variants）全部通过

## 五、红线确认

- ✅ 现有路由文件零改动（除 errors.py ai-analyze 端点内部增强、search_service.py 末尾追加新入口）
- ✅ 现有 186 接口路径与响应结构不变
- ✅ 无 DROP / 重建表；所有 DDL 幂等可重跑
- ✅ 启动方式不变：`uvicorn main:app --port 8000`
- ✅ 涉及外部模型一律走 `services.model_gateway.ModelGateway.chat(...)` 统一入口，无新增直连
*（内容由AI生成，仅供参考）*
