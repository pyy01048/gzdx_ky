# 数据字典（自动生成）

> 生成时间：2026-11-20 22:35 · 生成器：`scripts/diagnostics/gen_data_dictionary.py`  
> **请勿手改**：结构变更后重新生成；视图标注 READONLY（写入一律指向真实表）。

## 一、真实表（114 张）

### `ai_providers`

- 类型：**TABLE**
- 行数：7
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`name`=供应商配置名，唯一；`provider_type`=接入协议类型，如 openai_compatible；`api_key`=服务商密钥；AES-256-GCM 密文（enc:v1: 前缀）；`base_url`=接口基地址；`model_name`=默认模型名；`temperature`=采样温度，取值 0-2；`is_default`=是否为默认供应商；`is_enabled`=是否启用；`fallback_priority`=降级优先级，数字越小越优先；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('ai_providers_id_seq'::regclass) |
| name | VARCHAR(100) | 否 |  |
| provider_type | VARCHAR(50) | 否 | 'openai_compatible'::character varying |
| api_key | TEXT | 是 |  |
| base_url | VARCHAR(500) | 是 |  |
| model_name | VARCHAR(200) | 是 |  |
| temperature | REAL | 否 | 0.7 |
| is_default | BOOLEAN | 否 | false |
| is_enabled | BOOLEAN | 否 | true |
| fallback_priority | INTEGER | 否 | 100 |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `annotation_samples`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`chunk_id`=被标注的分块 ID；`chunk_text`=标注时的分块正文快照；`label_l3`=L3 标注结果；`source`=样本来源：manual / auto_generated / imported

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('annotation_samples_id_seq'::regclass) |
| chunk_id | BIGINT | 是 |  |
| chunk_text | TEXT | 否 |  |
| label_l1 | VARCHAR(50) | 是 |  |
| label_l2 | VARCHAR(200) | 是 |  |
| label_l3 | VARCHAR(4) | 是 |  |
| annotate_user | VARCHAR(50) | 是 |  |
| source | VARCHAR(20) | 否 | 'manual'::character varying |
| created_at | TIMESTAMP | 否 | now() |

### `answer_candidates`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/answer_cross_check.py、services/confidence_service.py
- 列注释：`question_id`=题目 ID，题目删除时级联删除；`confidence`=该候选答案的置信度 0-1；`source`=答案来源：bank / source_extract / llm_generated / user_confirmed；`used_for_grading`=是否被采纳为判分依据；`verified_by`=校验人；`verified_at`=校验时间；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('answer_candidates_id_seq'::regclass) |
| question_id | BIGINT | 否 |  |
| answer | TEXT | 否 |  |
| explanation | TEXT | 是 |  |
| confidence | REAL | 否 | 0.5 |
| source | VARCHAR(14) | 否 | 'llm_generated'::answer_source |
| used_for_grading | BOOLEAN | 否 | false |
| verified_by | VARCHAR(50) | 是 |  |
| verified_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| provenance | TEXT | 是 |  |
| reviewed | BOOLEAN | 否 | false |

### `answer_records`

- 类型：**TABLE**
- 行数：40
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/study/quiz.py
- 列注释：`question_id`=题目 ID，题目删除时置空但保留答题历史；`my_answer`=用户作答；`correct_answer`=当时判定的正确答案快照；`is_correct`=是否答对；NULL 表示未判分（主观题待评）；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`mode`=练习模式：practice / exam / review；`cost_seconds`=作答耗时（秒）；`created_at`=作答时间（UTC，带时区），掌握度时间衰减以此为准

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('answer_records_id_seq'::regclass) |
| question_id | BIGINT | 是 |  |
| my_answer | TEXT | 是 |  |
| correct_answer | TEXT | 是 |  |
| is_correct | BOOLEAN | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| mode | VARCHAR(50) | 是 |  |
| cost_seconds | INTEGER | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `answer_review_queue`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/qa_foundation.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 |  |
| question_id | INTEGER | 是 |  |
| conflict_type | VARCHAR(50) | 是 |  |
| detail | TEXT | 是 |  |
| status | VARCHAR(20) | 是 | 'pending'::character varying |
| resolution | TEXT | 是 |  |
| created_at | TIMESTAMP | 是 |  |

### `audit_logs`

- 类型：**TABLE**
- 行数：53282
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`before_data`=变更前数据快照；`after_data`=变更后数据快照

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('audit_logs_id_seq'::regclass) |
| table_name | VARCHAR(100) | 否 |  |
| record_id | BIGINT | 否 |  |
| action | VARCHAR(50) | 否 |  |
| operator_id | BIGINT | 是 |  |
| operator_ip | INET | 是 |  |
| before_data | JSONB | 是 |  |
| after_data | JSONB | 是 |  |
| change_summary | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `auth_events`

- 类型：**TABLE**
- 行数：2
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('auth_events_id_seq'::regclass) |
| event_type | VARCHAR(64) | 否 |  |
| user_id | INTEGER | 是 |  |
| email | VARCHAR(255) | 是 |  |
| actor_id | INTEGER | 是 |  |
| success | BOOLEAN | 否 | true |
| ip | VARCHAR(64) | 是 |  |
| user_agent | VARCHAR(255) | 是 |  |
| detail | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `chunk_vectors`

- 类型：**TABLE**
- 行数：81348
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/vector_builder.py
- 列注释：`chunk_id`=关联知识分块 ID，一对一，分块删除时级联删除；`document_id`=冗余文档 ID，便于按文档批量删除向量；`subject_id`=冗余科目 ID，便于按科目做向量过滤；`engine`=生成向量的引擎：bge / openai / unknown；`dim`=向量维度，实测 512；`embedding`=退化方案存储：float32 小端字节数组，供 Python 侧余弦检索；`model_version`=模型版本，模型升级后可据此批量重算；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| chunk_id | BIGINT | 否 |  |
| document_id | BIGINT | 是 |  |
| subject_id | BIGINT | 是 |  |
| engine | VARCHAR(7) | 否 | 'unknown'::vector_engine |
| dim | INTEGER | 否 |  |
| embedding | BYTEA | 是 |  |
| model_version | VARCHAR(50) | 否 | 'bge-small-zh-v1.5'::character varying |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| embedding_f32 | NULL | 是 |  |

### `code_problem_tags`

- 类型：**TABLE**
- 行数：1972
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| problem_id | BIGINT | 否 |  |
| tag_id | INTEGER | 否 |  |

### `code_problem_testcases`

- 类型：**TABLE**
- 行数：578
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`input_data`=输入数据（大文件存对象存储，此处存路径；小文本直接存）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('code_problem_testcases_id_seq'::regclass) |
| problem_id | BIGINT | 否 |  |
| input_data | TEXT | 否 |  |
| expected_output | TEXT | 否 |  |
| is_sample | BOOLEAN | 否 | false |
| score_weight | REAL | 否 | 1.0 |
| sort_order | INTEGER | 否 | 0 |

### `code_problems`

- 类型：**TABLE**
- 行数：600
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/codebank_service.py
- 列注释：`time_limit_ms`=单组测试数据时限（毫秒）；`memory_limit_kb`=内存限制（KB）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('code_problems_id_seq'::regclass) |
| title | VARCHAR(200) | 否 |  |
| subject | VARCHAR(50) | 是 |  |
| difficulty | SMALLINT | 否 | 2 |
| description | TEXT | 否 |  |
| input_format | TEXT | 是 |  |
| output_format | TEXT | 是 |  |
| sample_input | TEXT | 是 |  |
| sample_output | TEXT | 是 |  |
| hints | TEXT | 是 |  |
| time_limit_ms | INTEGER | 否 | 1000 |
| memory_limit_kb | INTEGER | 否 | 256000 |
| tags | JSONB | 是 |  |
| is_public | BOOLEAN | 否 | true |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| frequency | INTEGER | 否 | 3 |
| appear_years | TEXT | 是 |  |
| languages | TEXT | 是 |  |
| source | TEXT | 是 |  |

### `code_questions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 |  |
| title | TEXT | 否 |  |
| subject | TEXT | 否 | '通用'::text |
| difficulty | TEXT | 否 | 'medium'::text |
| tags | TEXT | 是 |  |
| languages | TEXT | 是 |  |
| statement | TEXT | 是 |  |
| input_desc | TEXT | 是 |  |
| output_desc | TEXT | 是 |  |
| examples | TEXT | 是 |  |
| hint | TEXT | 是 |  |
| source | TEXT | 是 |  |
| frequency | INTEGER | 是 | 3 |
| appear_years | TEXT | 是 |  |
| is_available | INTEGER | 否 | 1 |
| created_at | TEXT | 是 |  |

### `code_subjects`

- 类型：**TABLE**
- 行数：22
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/codebank_service.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 |  |
| name | TEXT | 否 |  |
| direction | TEXT | 是 |  |
| is_builtin | INTEGER | 否 | 0 |
| created_at | TEXT | 是 |  |

### `code_submission_results`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('code_submission_results_id_seq'::regclass) |
| submission_id | BIGINT | 否 |  |
| testcase_id | BIGINT | 是 |  |
| status | VARCHAR(20) | 否 |  |
| time_ms | INTEGER | 是 |  |
| memory_kb | INTEGER | 是 |  |
| actual_output | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `code_submissions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`status`=判题状态：pending待判/judging判题中/ac通过/wa答案错/tle超时/mle超内存/ce编译错/re运行错/se系统错

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('code_submissions_id_seq'::regclass) |
| problem_id | BIGINT | 否 |  |
| user_id | BIGINT | 是 |  |
| language | VARCHAR(20) | 否 |  |
| code | TEXT | 否 |  |
| status | VARCHAR(20) | 否 | 'pending'::character varying |
| score | REAL | 否 | 0.0 |
| total_testcases | INTEGER | 是 |  |
| passed_testcases | INTEGER | 是 |  |
| compile_error | TEXT | 是 |  |
| error_message | TEXT | 是 |  |
| max_time_ms | INTEGER | 是 |  |
| max_memory_kb | INTEGER | 是 |  |
| submitted_at | TIMESTAMP | 否 | now() |
| judged_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `code_tags`

- 类型：**TABLE**
- 行数：113
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('code_tags_id_seq'::regclass) |
| name | VARCHAR(50) | 否 |  |
| category | VARCHAR(50) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `conflict_review_queue`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/confidence_service.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 |  |
| question_id | INTEGER | 否 |  |
| answer_a | TEXT | 否 | ''::text |
| answer_b | TEXT | 否 | ''::text |
| source_a | TEXT | 否 | ''::text |
| source_b | TEXT | 否 | ''::text |
| confidence_a | REAL | 否 | 0.0 |
| confidence_b | REAL | 否 | 0.0 |
| suggested_winner | TEXT | 是 |  |
| status | VARCHAR(20) | 否 | 'open'::character varying |
| resolution | TEXT | 是 |  |
| reviewer_note | TEXT | 是 |  |
| reviewed_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `crawl_dead_letters`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('crawl_dead_letters_id_seq'::regclass) |
| job_id | INTEGER | 是 |  |
| url | VARCHAR(1024) | 是 |  |
| source_key | VARCHAR(64) | 是 |  |
| error | TEXT | 是 |  |
| attempts | INTEGER | 否 | 0 |
| payload | JSONB | 是 |  |
| created_at | TIMESTAMP | 是 |  |

### `crawl_jobs`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`status`=pending/running/done/failed

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('crawl_jobs_id_seq'::regclass) |
| source_key | VARCHAR(64) | 否 |  |
| school_id | INTEGER | 是 |  |
| url | VARCHAR(1024) | 是 |  |
| job_type | VARCHAR(32) | 是 |  |
| status | VARCHAR(16) | 否 | 'pending'::character varying |
| attempts | INTEGER | 否 | 0 |
| next_run_at | TIMESTAMP | 是 |  |
| last_error | TEXT | 是 |  |
| created_at | TIMESTAMP | 是 |  |
| updated_at | TIMESTAMP | 是 |  |

### `crawl_pages`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('crawl_pages_id_seq'::regclass) |
| job_id | INTEGER | 是 |  |
| url | VARCHAR(1024) | 是 |  |
| canonical_url | VARCHAR(1024) | 是 |  |
| title | VARCHAR(512) | 是 |  |
| publish_date | DATE | 是 |  |
| html_path | VARCHAR(1000) | 是 |  |
| text | TEXT | 是 |  |
| content_hash | VARCHAR(64) | 是 |  |
| simhash | VARCHAR(32) | 是 |  |
| fetched_at | TIMESTAMP | 是 |  |

### `custom_links`

- 类型：**TABLE**
- 行数：4
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`name`=链接显示名；`url`=链接地址；`category`=分组分类；`sort_order`=组内排序权重，升序；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('custom_links_id_seq'::regclass) |
| name | VARCHAR(200) | 否 |  |
| url | VARCHAR(1000) | 否 |  |
| category | VARCHAR(100) | 否 | 'general'::character varying |
| sort_order | INTEGER | 否 | 0 |
| created_at | TIMESTAMP | 否 | now() |

### `daily_plans`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`date`=计划日期；`days_to_exam`=距考试天数；`timeline`=当日时间轴安排（JSON 数组）；`study_duration`=有效学习时长（分钟）；`wasted_duration`=浪费时长（分钟）；`score`=当日自评分

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('daily_plans_id_seq'::regclass) |
| date | DATE | 否 |  |
| days_to_exam | INTEGER | 是 |  |
| tasks | JSONB | 否 | '[]'::jsonb |
| timeline | JSONB | 否 | '[]'::jsonb |
| study_duration | INTEGER | 否 | 0 |
| wasted_duration | INTEGER | 否 | 0 |
| score | SMALLINT | 是 |  |
| summary | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `disciplines`

- 类型：**TABLE**
- 行数：97
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`code`=学科代码，研招口径，如 0803/0808/0812；`name`=学科名称；`category`=学科门类（实测值：工学）；`parent_code`=上级学科代码；`exam_overlap`=学科间考纲重叠说明；`description`=学科说明；`sort_order`=展示排序权重，升序；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('disciplines_id_seq'::regclass) |
| code | VARCHAR(20) | 否 |  |
| name | VARCHAR(100) | 否 |  |
| category | VARCHAR(50) | 是 |  |
| parent_code | VARCHAR(20) | 是 |  |
| exam_overlap | TEXT | 是 |  |
| description | TEXT | 是 |  |
| sort_order | INTEGER | 否 | 0 |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `document_blocks`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`block_type`=text/title/table/figure/formula/list/header/footer/page_no/unknown；`extra`=块级附加信息 JSON（math_corrupted / math_suspect / ocr_confidence_missing 等质检标记）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('document_blocks_id_seq'::regclass) |
| document_id | INTEGER | 否 |  |
| page_no | INTEGER | 否 |  |
| block_id | VARCHAR(64) | 是 |  |
| block_type | VARCHAR(32) | 是 |  |
| bbox | JSONB | 是 |  |
| text | TEXT | 是 |  |
| latex | TEXT | 是 |  |
| image_path | VARCHAR(1000) | 是 |  |
| reading_order | INTEGER | 是 |  |
| confidence | DOUBLE PRECISION | 是 |  |
| created_at | TIMESTAMP | 是 |  |
| extra | JSONB | 是 |  |

### `document_pages`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`page_no`=物理页码（1 基）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('document_pages_id_seq'::regclass) |
| document_id | INTEGER | 否 |  |
| page_no | INTEGER | 否 |  |
| width | DOUBLE PRECISION | 是 |  |
| height | DOUBLE PRECISION | 是 |  |
| text | TEXT | 是 |  |
| layout_json | JSONB | 是 |  |
| image_path | VARCHAR(1000) | 是 |  |
| ocr_engine | VARCHAR(50) | 是 |  |
| ocr_confidence | DOUBLE PRECISION | 是 |  |
| created_at | TIMESTAMP | 是 |  |

### `documents`

- 类型：**TABLE**
- 行数：2666
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`id`=主键，BIGSERIAL；`file_name`=原始文件名；`file_path`=服务器存储路径；`size`=文件字节数；`content_hash`=文件内容 SHA-256 前 64 位，用于跨来源去重；`source_format`=原始文件格式（pdf/txt/doc/docx/md/image...），11 种混存的记录口径；`canonical_content`=统一 Markdown 中间态：所有格式解析后归一写入，下游检索与切片只认这一列；`canonical_engine`=产出中间态的解析器名（如 pypdf / pdfplumber / rapidocr），便于重解析；`canonical_version`=中间态格式版本号，解析器升级后可据此批量重解析；`content`=兼容列（历史代码读写），由触发器与 canonical_content 双向同步，Phase 2 后移除；`subject_id`=权威科目外键，取代旧的 subject 文本；`subject`=兼容列：科目中文名，由 ETL 从 subjects.name 回填；`chapter_id`=权威章节外键；`chapter`=兼容列：章节名；`doc_type`=资料加工层级：raw 原始教材真题 / note 加工笔记错题 / index 索引考点清单；`content_category`=内容语义分类，与 doc_type 正交：textbook 教材 / example 例题 / exam 真题 / method 方法；`exam_stage`=考试阶段：初试 / 复试（原 stage 列，与 prep_stage 语义不同故改名）；`structure_level`=结构化程度：structured 已按章节解析 / flat 扁平文本 / ocr 扫描件；`index_status`=索引状态机：pending → indexing → indexed / failed / skipped；`parse_progress`=解析进度 0-1；`parse_error`=解析失败原因，index_status=failed 时必填；`knowledge_point_count`=已从该文档抽取的知识点数量；`chunk_count`=该文档已产生的知识分块数量；`ocr_used`=是否经 OCR 识别（扫描版资料）；`source_kind`=来源性质（正交列），取代旧的 source 字符串前缀归类；`subject_source`=资料导入来源：ima 表示 IMA 知识库导入，空表示本地上传；`ima_media_id`=IMA 侧条目 ID，正文按需拉取，不落库；`folder_path`=IMA 内文件夹路径，保留原始组织结构；`content_type`=内容性质：知识 / 试题 / 单词；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间，由 set_updated_at 触发器维护；`is_junk`=违禁/废弃文档标记（红线3：非 0854 学科内容）；列表与检索应过滤 is_junk IS NOT TRUE

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('documents_id_seq'::regclass) |
| file_name | VARCHAR(500) | 否 |  |
| file_path | VARCHAR(1000) | 是 |  |
| size | BIGINT | 是 |  |
| content_hash | VARCHAR(64) | 是 |  |
| source_format | VARCHAR(5) | 否 | 'other'::doc_format |
| canonical_content | TEXT | 是 |  |
| canonical_engine | VARCHAR(50) | 是 |  |
| canonical_version | INTEGER | 否 | 1 |
| content | TEXT | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter_id | BIGINT | 是 |  |
| chapter | VARCHAR(200) | 是 |  |
| doc_type | VARCHAR(5) | 是 |  |
| content_category | VARCHAR(8) | 是 |  |
| exam_stage | VARCHAR(2) | 是 |  |
| structure_level | VARCHAR(10) | 是 |  |
| index_status | VARCHAR(8) | 否 | 'pending'::index_status |
| parse_progress | REAL | 否 | 0 |
| parse_error | TEXT | 是 |  |
| knowledge_point_count | INTEGER | 否 | 0 |
| chunk_count | INTEGER | 否 | 0 |
| ocr_used | BOOLEAN | 否 | false |
| source_kind | VARCHAR(16) | 否 | 'external_import'::source_kind |
| subject_source | VARCHAR(50) | 是 |  |
| ima_media_id | VARCHAR(200) | 是 |  |
| folder_path | VARCHAR(500) | 是 |  |
| content_type | VARCHAR(20) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| stage | TEXT | 是 |  |
| is_junk | BOOLEAN | 否 | false |

### `early_bird_records`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`day_num`=连续打卡第几天；`date`=打卡日期；`wake_time`=起床时间；`sleep_time`=入睡时间；`note`=备注

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('early_bird_records_id_seq'::regclass) |
| day_num | INTEGER | 否 |  |
| date | DATE | 否 |  |
| wake_time | TIME | 是 |  |
| sleep_time | TIME | 是 |  |
| note | VARCHAR(500) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `ebbinghaus_items`

- 类型：**TABLE**
- 行数：1
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`learn_date`=首次学习时间（UTC，带时区）；`review_5min`=5 分钟后复习时点；`review_30min`=30 分钟后复习时点；`review_12h`=12 小时后复习时点；`review_1d`=1 天后复习时点；`review_2d`=2 天后复习时点；`review_4d`=4 天后复习时点；`review_7d`=7 天后复习时点；`review_15d`=15 天后复习时点；`review_1m`=1 个月后复习时点；`mastered`=是否已掌握

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('ebbinghaus_items_id_seq'::regclass) |
| seq | INTEGER | 是 |  |
| learn_date | TIMESTAMP | 否 |  |
| content | TEXT | 否 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| review_5min | TIMESTAMP | 是 |  |
| review_30min | TIMESTAMP | 是 |  |
| review_12h | TIMESTAMP | 是 |  |
| review_1d | TIMESTAMP | 是 |  |
| review_2d | TIMESTAMP | 是 |  |
| review_4d | TIMESTAMP | 是 |  |
| review_7d | TIMESTAMP | 是 |  |
| review_15d | TIMESTAMP | 是 |  |
| review_1m | TIMESTAMP | 是 |  |
| mastered | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |
| cycle_config | JSONB | 是 |  |
| review_times | JSONB | 是 |  |

### `email_tokens`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('email_tokens_id_seq'::regclass) |
| user_id | INTEGER | 否 |  |
| kind | VARCHAR(16) | 否 |  |
| token_hash | VARCHAR(64) | 否 |  |
| pwd_fingerprint | VARCHAR(64) | 是 |  |
| expires_at | TIMESTAMP | 否 |  |
| used_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| request_ip | VARCHAR(64) | 是 |  |

### `error_knowledge_links`

- 类型：**TABLE**
- 行数：14
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`error_id`=错题 ID，错题删除时级联删除；`relevance`=相关度 0-1；`source`=关联来源：auto 自动 / manual 人工；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('error_knowledge_links_id_seq'::regclass) |
| error_id | BIGINT | 否 |  |
| knowledge_point_id | BIGINT | 是 |  |
| chunk_id | BIGINT | 是 |  |
| document_id | BIGINT | 是 |  |
| relevance | REAL | 否 | 0 |
| source | VARCHAR(20) | 否 | 'auto'::character varying |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `error_records`

- 类型：**TABLE**
- 行数：7
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/error_analyzer.py、services/exam_builder.py
- 列注释：`question_id`=关联题目 ID，题目删除时置空保留错题；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`knowledge_point_id`=关联知识点 ID；`accuracy`=该错题的历史正确率 0-1；`status`=处理状态：unreviewed / reviewing / mastered；`mastery_level`=掌握等级：not_mastered / learning / reviewing / mastered；`tags`=错题标签数组；`pass_number`=当前轮次（第几遍刷）；`recent_weight`=近期权重，用于掌握度时间衰减加权；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('error_records_id_seq'::regclass) |
| question_id | BIGINT | 是 |  |
| content | TEXT | 是 |  |
| my_answer | TEXT | 是 |  |
| correct_answer | TEXT | 是 |  |
| error_reason | VARCHAR(200) | 是 |  |
| error_category | VARCHAR(50) | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| knowledge_point_id | BIGINT | 是 |  |
| accuracy | REAL | 是 |  |
| review_count | INTEGER | 否 | 0 |
| last_review | TIMESTAMP | 是 |  |
| next_review | TIMESTAMP | 是 |  |
| status | VARCHAR(50) | 否 | 'unreviewed'::character varying |
| mastery_level | VARCHAR(12) | 否 | 'not_mastered'::mastery_level |
| tags | JSONB | 否 | '[]'::jsonb |
| analysis | TEXT | 是 |  |
| ease_factor | REAL | 否 | 2.5 |
| interval_days | INTEGER | 否 | 0 |
| repetitions | INTEGER | 否 | 0 |
| lapses | INTEGER | 否 | 0 |
| pass_number | INTEGER | 否 | 1 |
| recent_weight | REAL | 否 | 1.0 |
| user_note | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| interval | INTEGER | 是 | 0 |
| last_status | TEXT | 是 | 'unreviewed'::text |
| prev_ease_factor | REAL | 是 |  |
| prev_interval | INTEGER | 是 |  |
| prev_repetitions | INTEGER | 是 |  |
| user_id | BIGINT | 是 |  |

### `eval_runs`

- 类型：**TABLE**
- 行数：2
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`kind`=评测类型：retrieval / generation / grading；`arm`=对比臂名称，如 baseline / hybrid_rerank；`dataset_fingerprint`=评测集指纹，保证可复现；`primary_metric`=主指标数值；`metrics`=全部指标（JSON 对象）；`report_path`=报告文件路径

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('eval_runs_id_seq'::regclass) |
| kind | VARCHAR(24) | 否 |  |
| arm | VARCHAR(120) | 是 |  |
| dataset_fingerprint | VARCHAR(64) | 是 |  |
| n_samples | INTEGER | 否 | 0 |
| primary_metric | REAL | 是 |  |
| metrics | JSONB | 否 | '{}'::jsonb |
| report_path | VARCHAR(300) | 是 |  |
| notes | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `exam_answers`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/exam_builder.py
- 列注释：`session_id`=所属场次 ID，场次删除时级联删除；`question_snapshot`=题干快照；`order_no`=卷内作答序号；`ai_score`=AI 评分；`self_score`=自评分；`final_score`=最终得分；`scored_by`=评分方：ai / self / teacher；`error_category`=错误分类

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('exam_answers_id_seq'::regclass) |
| session_id | BIGINT | 否 |  |
| question_id | BIGINT | 是 |  |
| question_snapshot | TEXT | 是 |  |
| section | TEXT | 是 |  |
| order_no | INTEGER | 是 |  |
| user_answer | TEXT | 是 |  |
| is_correct | BOOLEAN | 是 |  |
| time_spent | INTEGER | 是 |  |
| ai_score | REAL | 是 |  |
| self_score | REAL | 是 |  |
| final_score | REAL | 是 |  |
| scored_by | VARCHAR(30) | 是 |  |
| error_category | VARCHAR(50) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `exam_blueprints`

- 类型：**TABLE**
- 行数：130
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/module_a_schema.py
- 列注释：`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`paper`=试卷标识；`section`=卷内分区，如 选择题 / 解答题；`blueprint_question_type`=该分区的题型；`count`=该分区题量；`score_per_question`=单题分值；`time_limit_minutes`=建议时限（分钟）；`kp_filters`=知识点过滤条件；`is_active`=是否启用；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('exam_blueprints_id_seq'::regclass) |
| subject_id | BIGINT | 是 |  |
| subject | TEXT | 否 |  |
| paper | TEXT | 否 |  |
| year | INTEGER | 是 |  |
| section | TEXT | 否 |  |
| blueprint_question_type | VARCHAR(8) | 否 |  |
| count | INTEGER | 否 |  |
| score_per_question | REAL | 否 |  |
| time_limit_minutes | INTEGER | 是 |  |
| sort_order | INTEGER | 否 | 0 |
| kp_filters | TEXT | 是 |  |
| is_active | BOOLEAN | 否 | true |
| created_at | TIMESTAMP | 否 | now() |

### `exam_sessions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/exam_builder.py
- 列注释：`blueprint_key`=使用的蓝图标识；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`mode`=模式：normal 普通 / strict 严格计时；`question_source`=抽题范围性质，复用 source_kind 枚举；`config`=场次配置快照（JSON 对象）；`started_at`=开始时间（UTC，带时区）；`expires_at`=截止时间（UTC，带时区）；`status`=场次状态：ongoing / submitted / expired / abandoned

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('exam_sessions_id_seq'::regclass) |
| blueprint_key | VARCHAR(100) | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | TEXT | 否 |  |
| paper | TEXT | 是 |  |
| mode | VARCHAR(30) | 否 | 'normal'::character varying |
| question_source | VARCHAR(16) | 否 | 'external_import'::source_kind |
| config | JSONB | 否 | '{}'::jsonb |
| total_count | INTEGER | 是 |  |
| total_score | REAL | 是 |  |
| correct_count | INTEGER | 是 |  |
| score | REAL | 是 |  |
| time_limit_minutes | INTEGER | 是 |  |
| started_at | TIMESTAMP | 否 | now() |
| expires_at | TIMESTAMP | 是 |  |
| submitted_at | TIMESTAMP | 是 |  |
| status | VARCHAR(20) | 否 | 'ongoing'::character varying |
| created_at | TIMESTAMP | 否 | now() |

### `favorites`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/study/favorites.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('favorites_id_seq'::regclass) |
| item_type | VARCHAR(32) | 否 |  |
| item_id | INTEGER | 否 |  |
| title | VARCHAR(500) | 否 | ''::character varying |
| snippet | TEXT | 是 |  |
| meta | JSONB | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `flashcards`

- 类型：**TABLE**
- 行数：3706
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`front`=卡片正面；`back`=卡片背面；`knowledge_point_id`=关联知识点 ID；`next_review`=下次复习时间（UTC），兼容列，真值在 review_schedules；`interval_days`=当前复习间隔（天）；`ease_factor`=SM-2 难度因子；`mastery`=掌握状态：new / learning / review / mastered；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('flashcards_id_seq'::regclass) |
| front | TEXT | 否 |  |
| back | TEXT | 否 |  |
| knowledge_point_id | BIGINT | 是 |  |
| next_review | TIMESTAMP | 是 |  |
| review_count | INTEGER | 否 | 0 |
| interval_days | INTEGER | 否 | 1 |
| ease_factor | REAL | 否 | 2.5 |
| mastery | VARCHAR(12) | 否 | 'not_mastered'::mastery_level |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `focus_sessions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`start_at`=开始时间（UTC，带时区）；`end_at`=结束时间（UTC，带时区）；`duration_minutes`=专注时长（分钟）；`tag`=专注标签；`note`=备注；`created_at`=记录创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('focus_sessions_id_seq'::regclass) |
| start_at | TIMESTAMP | 否 |  |
| end_at | TIMESTAMP | 是 |  |
| duration_minutes | INTEGER | 是 |  |
| tag | VARCHAR(50) | 是 |  |
| note | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `goals`

- 类型：**TABLE**
- 行数：1
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`exam_date`=考试日期；`total_score_target`=总分目标；`politics_target`=政治目标分；`english_target`=英语目标分；`math_target`=数学目标分；`major_target`=专业课目标分；`university`=目标院校；`major`=目标专业；`remark`=备注；`subject_codes`=备考科目权威代码数组，元素须存在于 subjects.code；`support_subject_codes`=专业课支撑科目代码数组（可能涉及但未必考）；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间；`daily_focus_minutes`=每日专注时长目标（分钟）；NULL=未设目标，进度环显示"未设目标"；`daily_new_words`=每日新词目标；NULL=未设目标；`daily_review_words`=每日复习词量目标；NULL=未设目标；`daily_questions`=每日刷题目标；NULL=未设目标

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('goals_id_seq'::regclass) |
| exam_date | DATE | 是 |  |
| total_score_target | SMALLINT | 是 |  |
| politics_target | SMALLINT | 是 |  |
| english_target | SMALLINT | 是 |  |
| math_target | SMALLINT | 是 |  |
| major_target | SMALLINT | 是 |  |
| university | VARCHAR(200) | 是 |  |
| major | VARCHAR(200) | 是 |  |
| remark | TEXT | 是 |  |
| subject_codes | JSONB | 否 | '[]'::jsonb |
| support_subject_codes | JSONB | 否 | '[]'::jsonb |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| daily_focus_minutes | SMALLINT | 是 |  |
| daily_new_words | SMALLINT | 是 |  |
| daily_review_words | SMALLINT | 是 |  |
| daily_questions | SMALLINT | 是 |  |
| user_id | BIGINT | 是 |  |

### `kaoyan_admission_details`

- 类型：**TABLE**
- 行数：43064
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_admission_details_id_seq'::regclass) |
| admission_id | BIGINT | 是 |  |
| school_id | BIGINT | 否 |  |
| year | INTEGER | 否 |  |
| exam_no | VARCHAR(40) | 是 |  |
| name | VARCHAR(60) | 否 |  |
| major_name | VARCHAR(120) | 是 |  |
| score_initial | NUMERIC(6, 2) | 是 |  |
| score_retest | NUMERIC(6, 2) | 是 |  |
| score_total | NUMERIC(6, 2) | 是 |  |
| remark | VARCHAR(200) | 是 |  |
| data_source | VARCHAR(80) | 否 |  |
| created_at | TIMESTAMP | 否 | now() |

### `kaoyan_admissions`

- 类型：**TABLE**
- 行数：1613
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`school_id`=院校 ID，级联删除；`major_id`=专业 ID，级联删除；`year`=招生年份；`enroll_count`=计划招生人数；`retest_count`=进入复试人数；`admit_count`=实际录取人数；`admit_avg_score`=录取平均分；`major_avg_score`=专业课平均分；`retest_ratio`=复录比；`data_source`=采集来源；`source`=采集批次标识

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_admissions_id_seq'::regclass) |
| school_id | BIGINT | 否 |  |
| major_id | BIGINT | 是 |  |
| year | INTEGER | 否 |  |
| enroll_count | INTEGER | 是 |  |
| retest_count | INTEGER | 是 |  |
| admit_count | INTEGER | 是 |  |
| admit_avg_score | REAL | 是 |  |
| major_avg_score | REAL | 是 |  |
| retest_ratio | REAL | 是 |  |
| data_source | VARCHAR(50) | 是 |  |
| source | VARCHAR(50) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| enabled | BOOLEAN | 否 | true |
| deleted_at | TIMESTAMP | 是 |  |
| extra | JSONB | 是 |  |

### `kaoyan_alert_records`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/kaoyan/notice_alert.py、services/kaoyan/notice_alert.py
- 列注释：`notice_id`=关联通知 ID，通知删除时级联删除；`alert_kind`=提醒类型：deadline_soon / new_urgent / new_important / subscribed_new；`alert_date`=提醒发生日期（北京时间 YYYY-MM-DD）；`days_left`=距截止剩余天数；`acked`=用户是否已确认；`acked_at`=确认时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_alert_records_id_seq'::regclass) |
| notice_id | BIGINT | 否 |  |
| alert_kind | VARCHAR(14) | 否 |  |
| alert_date | TEXT | 否 |  |
| title | TEXT | 是 |  |
| school_name | TEXT | 是 |  |
| notice_type | TEXT | 是 |  |
| importance_level | TEXT | 是 |  |
| deadline_date | TEXT | 是 |  |
| days_left | INTEGER | 是 |  |
| message | TEXT | 否 |  |
| acked | BOOLEAN | 否 | false |
| acked_at | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `kaoyan_alert_runs`

- 类型：**TABLE**
- 行数：5
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/kaoyan/notice_alert.py
- 列注释：`trigger_source`=触发方式：schedule 定时 / manual 手动；`scanned`=扫描的通知条数；`created_alerts`=新生成的提醒条数；`skipped_dup`=因重复跳过的条数；`elapsed_ms`=本次扫描耗时（毫秒）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_alert_runs_id_seq'::regclass) |
| ran_at | TIMESTAMP | 否 | now() |
| trigger_source | VARCHAR(20) | 否 | 'schedule'::character varying |
| scanned | INTEGER | 否 | 0 |
| created_alerts | INTEGER | 否 | 0 |
| skipped_dup | INTEGER | 否 | 0 |
| elapsed_ms | INTEGER | 否 | 0 |
| detail | TEXT | 是 |  |

### `kaoyan_collection_runs`

- 类型：**TABLE**
- 行数：42
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`source`=采集来源；`item_type`=采集的数据类型：school / major / notice / scoreline；`row_count`=本次采集写入行数；`status`=执行结果：success / partial / failed；`created_at`=执行时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_collection_runs_id_seq'::regclass) |
| source | VARCHAR(50) | 否 |  |
| scope | VARCHAR(200) | 是 |  |
| item_type | VARCHAR(30) | 是 |  |
| row_count | INTEGER | 否 | 0 |
| detail | JSONB | 否 | '{}'::jsonb |
| status | VARCHAR(20) | 否 | 'success'::character varying |
| created_at | TIMESTAMP | 否 | now() |

### `kaoyan_colleges`

- 类型：**TABLE**
- 行数：673
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`school_id`=所属院校 ID，院校删除时级联删除；`name`=学院名称

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_colleges_id_seq'::regclass) |
| school_id | BIGINT | 否 |  |
| name | VARCHAR(200) | 否 |  |
| created_at | TIMESTAMP | 否 | now() |
| enabled | BOOLEAN | 否 | true |
| deleted_at | TIMESTAMP | 是 |  |

### `kaoyan_crawl_targets`

- 类型：**TABLE**
- 行数：46
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`enabled`=是否参与采集；`priority`=采集优先级，数字越大越优先；`note`=备注；`last_crawled_at`=最近一次采集时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('kaoyan_crawl_targets_id_seq'::regclass) |
| school_id | INTEGER | 否 |  |
| enabled | BOOLEAN | 否 |  |
| priority | INTEGER | 是 |  |
| note | VARCHAR(200) | 是 |  |
| last_crawled_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 是 |  |
| updated_at | TIMESTAMP | 是 |  |

### `kaoyan_major_kb_link`

- 类型：**TABLE**
- 行数：2733
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`match_level`=匹配等级：L1 精确 / L2 高度相似 / L3 弱匹配；`match_type`=匹配方式：exact 精确 / fuzzy 模糊 / alias 别名

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_major_kb_link_id_seq'::regclass) |
| major_id | BIGINT | 否 |  |
| school_id | BIGINT | 否 |  |
| school_name | TEXT | 否 | ''::text |
| major_name | TEXT | 否 | ''::text |
| major_code | VARCHAR(20) | 是 |  |
| subject_name | TEXT | 否 |  |
| match_level | VARCHAR(10) | 否 | 'L1'::character varying |
| match_type | VARCHAR(20) | 否 | 'exact'::character varying |
| kb_doc_count | INTEGER | 否 | 0 |
| confidence | REAL | 否 | 1.0 |
| created_at | TIMESTAMP | 否 | now() |

### `kaoyan_majors`

- 类型：**TABLE**
- 行数：12981
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`school_id`=所属院校 ID，院校删除时级联删除；`college_id`=所属学院 ID；`code`=专业代码；`research_direction`=研究方向；`subject_code`=所属学科代码；`exam_subjects`=初试科目数组（JSON）；`reference_books`=参考书目数组（JSON）；`degree_type`=学位类型：academic 学硕 / professional 专硕 / unknown

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_majors_id_seq'::regclass) |
| school_id | BIGINT | 否 |  |
| college_id | BIGINT | 是 |  |
| code | VARCHAR(20) | 是 |  |
| name | VARCHAR(200) | 否 |  |
| research_direction | VARCHAR(300) | 是 |  |
| subject_code | VARCHAR(20) | 是 |  |
| exam_subjects | JSONB | 否 | '[]'::jsonb |
| reference_books | JSONB | 否 | '[]'::jsonb |
| degree_type | VARCHAR(12) | 否 | 'unknown'::degree_type |
| created_at | TIMESTAMP | 否 | now() |
| enabled | BOOLEAN | 否 | true |
| deleted_at | TIMESTAMP | 是 |  |

### `kaoyan_national_lines`

- 类型：**TABLE**
- 行数：150
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_national_lines_id_seq'::regclass) |
| year | INTEGER | 否 |  |
| discipline | VARCHAR(100) | 否 |  |
| subjects | VARCHAR(500) | 是 |  |
| total_a | INTEGER | 是 |  |
| politics_a | INTEGER | 是 |  |
| math_a | INTEGER | 是 |  |
| total_b | INTEGER | 是 |  |
| politics_b | INTEGER | 是 |  |
| math_b | INTEGER | 是 |  |
| note | TEXT | 是 |  |
| source | VARCHAR(100) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `kaoyan_notices`

- 类型：**TABLE**
- 行数：1093
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/kaoyan/notice_alert.py、routers/kaoyan/notices.py、services/crawl/runner.py 等 6 处
- 列注释：`school_id`=解析出的院校 ID，未匹配上为空；`school_name`=通知上写的院校名原文；`notice_type`=通知类型：公告 / 简章 / 复试 / 调剂 / 录取；`publish_date`=发布日期（YYYY-MM-DD）；`importance_level`=重要级：urgent / important / normal / low；`importance_score`=重要度评分 0-1；`importance_reason`=重要度判定理由；`deadline_date`=截止日期（YYYY-MM-DD）；`events_json`=抽取出的关键事件（JSON 数组）；`is_noise`=是否为噪声通知（招生宣传/无关资讯）；`created_at`=入库时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_notices_id_seq'::regclass) |
| school_id | BIGINT | 是 |  |
| school_name | TEXT | 是 |  |
| title | TEXT | 否 |  |
| notice_type | VARCHAR(2) | 否 | '公告'::notice_type |
| publish_date | TEXT | 是 |  |
| url | TEXT | 是 |  |
| source | TEXT | 是 |  |
| fetched_at | TEXT | 是 |  |
| importance_level | VARCHAR(9) | 是 |  |
| importance_score | REAL | 是 |  |
| importance_reason | TEXT | 是 |  |
| deadline_date | TEXT | 是 |  |
| events_json | TEXT | 是 |  |
| classified_at | TEXT | 是 |  |
| is_read | BOOLEAN | 否 | false |
| is_starred | BOOLEAN | 否 | false |
| read_at | TEXT | 是 |  |
| starred_at | TEXT | 是 |  |
| content | TEXT | 是 |  |
| is_noise | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 否 | now() |

### `kaoyan_reforms`

- 类型：**TABLE**
- 行数：158
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 |  |
| school_id | INTEGER | 是 |  |
| school_name | TEXT | 否 |  |
| notice_id | INTEGER | 是 |  |
| notice_type | TEXT | 是 |  |
| title | TEXT | 是 |  |
| year | INTEGER | 是 |  |
| change_type | TEXT | 否 |  |
| change_detail | TEXT | 是 |  |
| keywords | TEXT | 是 |  |
| confidence | REAL | 是 | 0.5 |
| url | TEXT | 是 |  |
| source | TEXT | 是 |  |
| created_at | TEXT | 是 |  |
| detail_hash | TEXT | 是 |  |

### `kaoyan_schools`

- 类型：**TABLE**
- 行数：1150
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/kaoyan/school_type_enrich.py
- 列注释：`name`=院校名称，唯一；`level`=院校层次：985 / 211 / 双一流 / 普通；`province`=所在省份；`city`=所在城市；`logo_url`=校徽地址；`intro`=院校简介；`tags`=院校标签数组，如 ["985","自主划线"]；`official_url`=官网地址；`data_source`=数据采集来源；`type`=院校类型：综合 / 理工 / 师范 等；`region`=所属地区；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_schools_id_seq'::regclass) |
| name | VARCHAR(200) | 否 |  |
| level | VARCHAR(50) | 是 |  |
| province | VARCHAR(50) | 是 |  |
| city | VARCHAR(50) | 是 |  |
| logo_url | VARCHAR(500) | 是 |  |
| intro | TEXT | 是 |  |
| tags | JSONB | 否 | '[]'::jsonb |
| official_url | VARCHAR(500) | 是 |  |
| data_source | VARCHAR(50) | 是 |  |
| type | VARCHAR(30) | 是 |  |
| region | VARCHAR(30) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| enabled | BOOLEAN | 否 | true |
| deleted_at | TIMESTAMP | 是 |  |

### `kaoyan_scorelines`

- 类型：**TABLE**
- 行数：182748
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/kaoyan/engineering_codes.py
- 列注释：`total_line`=总分线；`politics_line`=政治单科线；`english_line`=英语单科线；`math_line`=数学单科线；`major_line`=专业课单科线；`national_line`=当年国家线；`retest_line`=复试线；`line_type`=线的类型：national 国家线 / school 校线 / college 院线 / retest 复试线；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_scorelines_id_seq'::regclass) |
| school_id | BIGINT | 否 |  |
| major_id | BIGINT | 是 |  |
| year | INTEGER | 否 |  |
| total_line | INTEGER | 是 |  |
| politics_line | INTEGER | 是 |  |
| english_line | INTEGER | 是 |  |
| math_line | INTEGER | 是 |  |
| major_line | INTEGER | 是 |  |
| national_line | INTEGER | 是 |  |
| retest_line | INTEGER | 是 |  |
| line_type | VARCHAR(20) | 是 |  |
| source | VARCHAR(50) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| enabled | BOOLEAN | 否 | true |
| deleted_at | TIMESTAMP | 是 |  |
| major_code | VARCHAR(20) | 是 |  |
| major_name | VARCHAR(120) | 是 |  |
| depart_name | VARCHAR(120) | 是 |  |
| degree_type | VARCHAR(20) | 是 |  |
| note | TEXT | 是 |  |
| special_remark | TEXT | 是 |  |
| diff_total | INTEGER | 是 |  |
| source_id | VARCHAR(64) | 是 |  |

### `kaoyan_subscriptions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/kaoyan/notice_alert.py
- 列注释：`scope`=订阅维度：school / major / notice_type / keyword；`level_min`=只推送不低于该重要级的通知；`enabled`=是否启用该订阅

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('kaoyan_subscriptions_id_seq'::regclass) |
| scope | VARCHAR(11) | 否 |  |
| school_id | BIGINT | 否 | 0 |
| school_name | TEXT | 否 | ''::text |
| major_name | TEXT | 否 | ''::text |
| notice_type | TEXT | 否 | ''::text |
| keyword | TEXT | 否 | ''::text |
| level_min | VARCHAR(9) | 否 | 'normal'::importance_level |
| enabled | BOOLEAN | 否 | true |
| remark | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `knowledge_chunks`

- 类型：**TABLE**
- 行数：81348
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/embedding_service.py、services/kb_service.py、services/search_service.py
- 列注释：`id`=主键，BIGSERIAL；`document_id`=来源文档 ID，文档删除时分块级联删除；`doc_name`=来源文档名（冗余，避免检索时回表）；`chunk_index`=分块在本篇文档内的序号，从 0 开始；`text`=分块正文，禁止空串；`search_tokens`=jieba 预分词结果（空格分隔），由 Python 侧写入后自动生成 tsvector；`search_vector`=全文检索向量，GENERATED 列自动维护，不可手工写入；`summary`=分块摘要；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`chapter_id`=权威章节外键；`page_start`=起始页码；`page_end`=结束页码；`l2_chapter`=L2 章节/模块，如：连续时间系统的时域分析；`l3_content_type`=L3 内容语义类型：定义/定理/例题/习题/证明/公式等；`classify_confidence`=三路融合分类置信度 0-1；`classify_source`=分类判定来源留痕：vector/keyword/fusion/llm/fallback；`token_count`=分块正文的估算 token 数，用于控制召回拼装长度；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('knowledge_chunks_id_seq'::regclass) |
| document_id | BIGINT | 是 |  |
| doc_name | VARCHAR(500) | 是 |  |
| chunk_index | INTEGER | 否 | 0 |
| text | TEXT | 是 |  |
| search_tokens | TEXT | 是 |  |
| search_vector | TSVECTOR | 是 |  |
| summary | TEXT | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter_id | BIGINT | 是 |  |
| page_start | INTEGER | 是 |  |
| page_end | INTEGER | 是 |  |
| l2_chapter | VARCHAR(200) | 是 |  |
| l3_content_type | VARCHAR(4) | 是 |  |
| classify_confidence | REAL | 是 |  |
| classify_source | VARCHAR(8) | 是 |  |
| token_count | INTEGER | 否 | 0 |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `knowledge_point_relations`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`source_kp_id`=源知识点 ID；`target_kp_id`=目标知识点 ID（由本表关系指向）；`relation_type`=关系类型：prerequisite 前置 / parallel 并列 / contains 包含；`source`=关系来源留痕：model / manual / import；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('knowledge_point_relations_id_seq'::regclass) |
| source_kp_id | BIGINT | 否 |  |
| target_kp_id | BIGINT | 否 |  |
| relation_type | VARCHAR(12) | 否 |  |
| source | VARCHAR(100) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `knowledge_points`

- 类型：**TABLE**
- 行数：5262
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/study/quiz.py、services/kp_mastery.py、services/review_service.py
- 列注释：`id`=主键，BIGSERIAL；`name`=知识点名称；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名，由 ETL 回填；`chapter_id`=权威章节外键；`chapter`=兼容列：章节名；`parent_id`=父知识点 ID，顶级为 NULL；`document_id`=来源文档 ID，文档删除时置空保留知识点；`source_chunk_id`=来源分块 ID，可反查原文片段；`source_chunk_index`=来源分块在篇内序号；`extract_source`=抽取来源：smart_ingest / batch / manual；`subject_source`=学科判定来源：model / keyword / fallback；`exam_frequency`=考频 0-5，0 表示未统计；`difficulty`=难度 1-5；`question_types`=该知识点考过的题型数组，如 ["选择","计算"]；`description`=知识点描述；`review_count`=累计复习次数；`last_review`=上次复习时间（UTC，带时区）；`ease_factor`=SM-2 难度因子，取值 1.3-3.5；`interval_days`=当前复习间隔（天）；`lapses`=遗忘次数；`question_count`=关联题目数（冗余，由触发器维护）；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间；`mastery`=掌握度兼容列（0-100）：镜像 v_knowledge_mastery 派生值，权威源仍是该视图；类型须与视图输出列一致（integer），否则视图列绑定会冲突；`next_review`=下次复习时间兼容列：镜像 review_schedules.next_review_at，权威源是 review_schedules

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('knowledge_points_id_seq'::regclass) |
| name | VARCHAR(300) | 否 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter_id | BIGINT | 是 |  |
| chapter | VARCHAR(200) | 是 |  |
| parent_id | BIGINT | 是 |  |
| document_id | BIGINT | 是 |  |
| source_chunk_id | BIGINT | 是 |  |
| source_chunk_index | INTEGER | 是 |  |
| extract_source | VARCHAR(12) | 是 |  |
| subject_source | VARCHAR(20) | 是 |  |
| exam_frequency | SMALLINT | 否 | 0 |
| difficulty | SMALLINT | 否 | 3 |
| question_types | JSONB | 否 | '[]'::jsonb |
| description | TEXT | 是 |  |
| review_count | INTEGER | 否 | 0 |
| last_review | TIMESTAMP | 是 |  |
| ease_factor | REAL | 否 | 2.5 |
| interval_days | INTEGER | 否 | 0 |
| lapses | INTEGER | 否 | 0 |
| question_count | INTEGER | 否 | 0 |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| mastery | INTEGER | 否 | 0 |
| next_review | TIMESTAMP | 是 |  |

### `memory_facts`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`claim`=事实陈述（AI 认为你某知识点薄弱/擅长等）；`evidence`=证据引用数组：[{trace_id, kind, snippet}]；`user_corrected`=用户是否已纠正该事实；`corrected_claim`=用户纠正后的事实陈述（权威）；`original_claim`=纠正前的原始 claim（审计保留）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('memory_facts_id_seq'::regclass) |
| user_id | BIGINT | 是 |  |
| fact_type | VARCHAR(50) | 否 | 'weakness'::character varying |
| subject | VARCHAR(50) | 是 |  |
| knowledge_point_id | BIGINT | 是 |  |
| kp_name | VARCHAR(100) | 是 |  |
| claim | TEXT | 否 |  |
| confidence | REAL | 是 | 0.5 |
| evidence | JSONB | 否 | '[]'::jsonb |
| source_layer | VARCHAR(12) | 否 | 'l2_fact'::memory_source_layer |
| user_corrected | BOOLEAN | 否 | false |
| corrected_claim | TEXT | 是 |  |
| corrected_at | TIMESTAMP | 是 |  |
| original_claim | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `memory_synthesis`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`fact_ids`=引用的 L2 事实 id 数组（溯源链）；`user_corrected`=用户是否已纠正该综合结论；`corrected_summary`=用户纠正后的结论文本；`original_summary`=纠正前的原始结论（审计保留）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('memory_synthesis_id_seq'::regclass) |
| user_id | BIGINT | 是 |  |
| synth_type | VARCHAR(50) | 否 | 'profile'::character varying |
| title | VARCHAR(200) | 否 |  |
| summary | TEXT | 否 |  |
| detail | JSONB | 否 | '{}'::jsonb |
| fact_ids | JSONB | 否 | '[]'::jsonb |
| source_layer | VARCHAR(12) | 否 | 'l3_synthesis'::memory_source_layer |
| user_corrected | BOOLEAN | 否 | false |
| corrected_summary | TEXT | 是 |  |
| corrected_at | TIMESTAMP | 是 |  |
| original_summary | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `memory_traces`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`trace_type`=轨迹类型：qa 答疑 / tutoring 讲题 / grading 批改 / study 学习 / document 资料 / feedback 用户反馈；`session_id`=AI 对话会话或模考会话 ID（逻辑关联，不设 FK）；`title`=人类可读摘要，用于记忆图谱列表展示；`payload`=原始上下文快照 JSON：题目、用户问题、AI 回答、检索引用、评分等；`occurred_at`=事件发生时间（UTC）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('memory_traces_id_seq'::regclass) |
| user_id | BIGINT | 是 |  |
| trace_type | VARCHAR(8) | 否 | 'qa'::memory_trace_type |
| subject | VARCHAR(50) | 是 |  |
| question_id | BIGINT | 是 |  |
| document_id | BIGINT | 是 |  |
| session_id | BIGINT | 是 |  |
| title | VARCHAR(200) | 否 |  |
| payload | JSONB | 否 | '{}'::jsonb |
| occurred_at | TIMESTAMP | 否 | now() |
| created_at | TIMESTAMP | 否 | now() |

### `milestones`

- 类型：**TABLE**
- 行数：36
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`year`=考试年份；`category`=节点分类：报名 / 考试 / 成绩 / 复试；`importance`=重要级 1-5；`action`=应做动作；`pitfalls`=常见坑提示

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('milestones_id_seq'::regclass) |
| year | INTEGER | 否 |  |
| name | VARCHAR(200) | 否 |  |
| category | VARCHAR(50) | 否 |  |
| start_date | DATE | 是 |  |
| end_date | DATE | 是 |  |
| importance | SMALLINT | 否 | 2 |
| action | TEXT | 是 |  |
| pitfalls | TEXT | 是 |  |
| is_active | BOOLEAN | 否 | true |
| created_at | TIMESTAMP | 否 | now() |

### `misconceptions`

- 类型：**TABLE**
- 行数：2
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/error_analyzer.py
- 列注释：`pattern`=错误模式描述；`category`=错误分类：概念不清 / 计算失误 / 审题偏差 / 方法不当；`suggestion`=改进建议；`evidence`=支撑证据（引用题目或对话片段）；`synced_at`=最近一次从外部知识库同步的时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('misconceptions_id_seq'::regclass) |
| question_id | BIGINT | 是 |  |
| error_record_id | BIGINT | 是 |  |
| knowledge_point_id | BIGINT | 是 |  |
| pattern | TEXT | 否 |  |
| category | VARCHAR(50) | 是 |  |
| suggestion | TEXT | 是 |  |
| evidence | TEXT | 是 |  |
| synced_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `month_plans`

- 类型：**TABLE**
- 行数：1
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`year`=年份；`month`=月份 1-12；`tasks`=月度任务列表（JSON 数组）；`completion`=完成情况说明；`summary`=月度总结

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('month_plans_id_seq'::regclass) |
| year | INTEGER | 否 |  |
| month | INTEGER | 否 |  |
| tasks | JSONB | 否 | '[]'::jsonb |
| completion | TEXT | 是 |  |
| summary | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `netdisk_file_cache`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`uk_account_fs`=uk + provider + fs_path的组合唯一键

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('netdisk_file_cache_id_seq'::regclass) |
| uk_account_fs | VARCHAR(200) | 否 |  |
| file_list | JSONB | 否 |  |
| expires_at | TIMESTAMP | 否 |  |
| created_at | TIMESTAMP | 否 | now() |

### `netdisk_files`

- 类型：**TABLE**
- 行数：1
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`file_type`=文件类型：video / pdf / doc / audio；`play_progress`=播放进度 0-1；`fs_id`=网盘侧文件 ID；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('netdisk_files_id_seq'::regclass) |
| file_name | VARCHAR(500) | 否 |  |
| path | VARCHAR(1000) | 是 |  |
| file_type | VARCHAR(50) | 是 |  |
| size | BIGINT | 是 |  |
| category | VARCHAR(100) | 是 |  |
| download_link | VARCHAR(1000) | 是 |  |
| play_progress | REAL | 否 | 0 |
| fs_id | VARCHAR(100) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `netdisk_operation_logs`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`action`=点分式操作名：netdisk.bind/netdisk.unbind/netdisk.preview等

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('netdisk_operation_logs_id_seq'::regclass) |
| user_id | BIGINT | 否 |  |
| action | VARCHAR(50) | 否 |  |
| provider | VARCHAR(50) | 是 |  |
| resource_id | VARCHAR(200) | 是 |  |
| status | VARCHAR(20) | 否 |  |
| error_code | VARCHAR(20) | 是 |  |
| error_message | TEXT | 是 |  |
| ip_address | INET | 是 |  |
| extra_metadata | JSONB | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `notice_user_states`

- 类型：**TABLE**
- 行数：1
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/kaoyan/notices.py、services/kaoyan/notice_read.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('notice_user_states_id_seq'::regclass) |
| user_id | BIGINT | 否 |  |
| notice_id | BIGINT | 否 |  |
| is_read | BOOLEAN | 否 | false |
| is_starred | BOOLEAN | 否 | false |
| updated_at | TIMESTAMP | 是 |  |

### `paper_answers`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`paper_question_seq`=卷内题号（快照，避免题目重排后序号变化）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('paper_answers_id_seq'::regclass) |
| attempt_id | BIGINT | 否 |  |
| question_id | BIGINT | 是 |  |
| paper_question_seq | INTEGER | 否 |  |
| user_answer | TEXT | 是 |  |
| is_correct | BOOLEAN | 是 |  |
| score | REAL | 是 |  |
| time_spent_seconds | INTEGER | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `paper_attempts`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`status`=作答状态：ongoing进行中/submitted已提交/expired超时

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('paper_attempts_id_seq'::regclass) |
| paper_id | BIGINT | 否 |  |
| user_id | BIGINT | 是 |  |
| started_at | TIMESTAMP | 否 | now() |
| submitted_at | TIMESTAMP | 是 |  |
| status | VARCHAR(20) | 否 | 'ongoing'::character varying |
| total_score | REAL | 是 |  |
| correct_count | INTEGER | 是 |  |
| duration_seconds | INTEGER | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `paper_questions`

- 类型：**TABLE**
- 行数：2379
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/qa_foundation.py
- 列注释：`paper_id`=所属试卷 ID，试卷删除时级联删除；`question_id`=源题目 ID，题目删除时置空但保留快照；`seq`=卷内序号；`content`=题干快照；`options`=选项快照，格式同 quiz_questions.options；`score`=该题分值；`avg_score`=该题历史平均得分（用于难度分析）；`attempt_count`=该题被作答次数（用于热度统计）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('paper_questions_id_seq'::regclass) |
| paper_id | BIGINT | 否 |  |
| question_id | BIGINT | 是 |  |
| seq | INTEGER | 否 | 0 |
| content | TEXT | 否 |  |
| options | JSONB | 是 |  |
| answer | TEXT | 是 |  |
| analysis | TEXT | 是 |  |
| question_type | VARCHAR(8) | 是 |  |
| difficulty | SMALLINT | 是 |  |
| score | INTEGER | 否 | 0 |
| avg_score | REAL | 是 |  |
| attempt_count | INTEGER | 否 | 0 |

### `papers`

- 类型：**TABLE**
- 行数：85
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/qa_foundation.py
- 列注释：`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`rules`=组卷规则（JSON 对象）：题型分布、难度分布、知识点范围；`total_score`=试卷总分；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间；`year`=真题年份（如 2024）；`paper_type`=卷种标签（如 数学一/英语二/专业课）；`is_mock`=是否为模拟试卷（true=用户自建，false=真题套卷）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('papers_id_seq'::regclass) |
| title | VARCHAR(200) | 否 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| description | TEXT | 是 |  |
| rules | JSONB | 否 | '{}'::jsonb |
| total_score | INTEGER | 否 | 100 |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| year | INTEGER | 是 |  |
| paper_type | VARCHAR(50) | 是 |  |
| is_mock | BOOLEAN | 否 | false |

### `pending_questions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/blind_spot_pool.py
- 列注释：`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`have_basis`=现有依据描述；`have_basis_ids`=依据的分块 ID 列表（逗号分隔）；`gap`=缺口描述；`gap_type`=缺口类型：missing_doc / outdated / conflict；`suggestion`=补齐建议；`suggested_action`=建议动作：import_doc / manual_answer / crawl；`status`=处理状态：open / resolved / ignored；`occurrence_count`=同一问题出现次数；`last_occurred_at`=最近一次出现时间；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('pending_questions_id_seq'::regclass) |
| question | TEXT | 否 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| asked_at | TIMESTAMP | 否 | now() |
| have_basis | TEXT | 是 |  |
| have_basis_ids | TEXT | 是 |  |
| gap | TEXT | 否 |  |
| gap_type | VARCHAR(50) | 是 |  |
| suggestion | TEXT | 是 |  |
| suggested_action | VARCHAR(100) | 是 |  |
| status | VARCHAR(20) | 否 | 'open'::character varying |
| resolved_by | VARCHAR(50) | 是 |  |
| resolved_at | TIMESTAMP | 是 |  |
| occurrence_count | INTEGER | 否 | 1 |
| last_occurred_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `phase_daily_reviews`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/study/planner.py
- 列注释：`morning_reviews`=早晨复习项（JSON 数组）；`evening_reviews`=晚间复习项（JSON 数组）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('phase_daily_reviews_id_seq'::regclass) |
| phase_plan_id | BIGINT | 否 |  |
| day_num | INTEGER | 否 |  |
| date | DATE | 是 |  |
| morning_reviews | JSONB | 否 | '[]'::jsonb |
| evening_reviews | JSONB | 否 | '[]'::jsonb |
| completed | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 否 | now() |

### `phase_plans`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`cycle_days`=阶段内循环周期天数

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('phase_plans_id_seq'::regclass) |
| name | VARCHAR(200) | 否 |  |
| start_date | DATE | 否 |  |
| end_date | DATE | 否 |  |
| cycle_days | INTEGER | 是 |  |
| tasks | JSONB | 否 | '[]'::jsonb |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `platform_configs`

- 类型：**TABLE**
- 行数：8
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`platform_name`=平台名称，唯一；`token`=访问令牌；AES-256-GCM 密文（enc:v1: 前缀），加解密见 utils/secret_codec.py；`app_key`=应用标识；AES-256-GCM 密文（enc:v1: 前缀）；`secret_key`=应用密钥；AES-256-GCM 密文（enc:v1: 前缀）；`sync_enabled`=是否启用自动同步；`sync_frequency`=同步频率：manual/hourly/daily/weekly；`last_sync`=上次同步时间；`extra`=平台专属扩展配置；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('platform_configs_id_seq'::regclass) |
| platform_name | VARCHAR(100) | 否 |  |
| token | TEXT | 是 |  |
| app_key | TEXT | 是 |  |
| secret_key | TEXT | 是 |  |
| sync_enabled | BOOLEAN | 否 | false |
| sync_frequency | VARCHAR(50) | 否 | 'manual'::character varying |
| last_sync | TIMESTAMP | 是 |  |
| extra | JSONB | 否 | '{}'::jsonb |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `preview_sessions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('preview_sessions_id_seq'::regclass) |
| user_id | BIGINT | 否 |  |
| file_id | VARCHAR(200) | 否 |  |
| play_position | INTEGER | 是 | 0 |
| progress_percent | DOUBLE PRECISION | 是 | 0 |
| page_number | INTEGER | 是 |  |
| session_expires_at | TIMESTAMP | 否 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `question_images`

- 类型：**TABLE**
- 行数：218
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`is_primary`=是否主图（同一题中面积最大者）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('question_images_id_seq'::regclass) |
| question_id | INTEGER | 是 |  |
| document_id | INTEGER | 是 |  |
| page_no | INTEGER | 是 |  |
| image_path | VARCHAR(1000) | 是 |  |
| image_hash | VARCHAR(64) | 是 |  |
| phash | VARCHAR(32) | 是 |  |
| bbox | JSONB | 是 |  |
| image_kind | VARCHAR(32) | 是 |  |
| caption | VARCHAR(1000) | 是 |  |
| width | INTEGER | 是 |  |
| height | INTEGER | 是 |  |
| is_primary | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 是 |  |

### `question_knowledge_links`

- 类型：**TABLE**
- 行数：4606
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`question_id`=题目 ID，题目删除时级联删除；`knowledge_point_id`=知识点 ID，知识点删除时级联删除；`role`=关联角色：primary 主考点 / secondary 次考点；`weight`=关联权重 0-1，聚合掌握度时作为加权系数；`is_verified`=是否人工校验过该关联；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('question_knowledge_links_id_seq'::regclass) |
| question_id | BIGINT | 否 |  |
| knowledge_point_id | BIGINT | 否 |  |
| role | VARCHAR(20) | 否 | 'primary'::character varying |
| weight | REAL | 否 | 1.0 |
| is_verified | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 否 | now() |

### `quiz_attempts`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`session_id`=所属刷题会话；`question_id`=所答题目；`user_answer`=用户作答内容；`is_correct`=是否答对：客观题 = (user_answer = answer)，主观题由自评或 AI 判定；`score`=得分：客观题满分或0分；主观题按 rubric 给分；`quality`=SM-2 回答质量：0=完全忘记, 1=错误, 2=困难想起, 3=正确但费力, 4=正确, 5=完美；`time_spent_seconds`=本题作答耗时（秒）；`feedback`=系统给出的反馈文本或标记；`ai_comment`=AI 对主观题作答的评语；`self_rating`=用户自评分级：correct 对 / partial 半对 / wrong 错；`mastery_before`=作答前知识点掌握度快照；`mastery_after`=经调度算法更新后的掌握度

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('quiz_attempts_id_seq'::regclass) |
| session_id | BIGINT | 否 |  |
| question_id | BIGINT | 否 |  |
| user_answer | TEXT | 是 |  |
| is_correct | BOOLEAN | 是 |  |
| score | REAL | 是 |  |
| quality | SMALLINT | 否 | 3 |
| answered_at | TIMESTAMP | 否 | now() |
| time_spent_seconds | INTEGER | 是 |  |
| feedback | TEXT | 是 |  |
| ai_comment | TEXT | 是 |  |
| self_rating | VARCHAR(10) | 是 |  |
| mastery_before | SMALLINT | 是 |  |
| mastery_after | SMALLINT | 是 |  |
| user_id | BIGINT | 是 |  |

### `quiz_questions`

- 类型：**TABLE**
- 行数：10953
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/answer_cross_check.py、services/confidence_service.py、services/qa_foundation.py
- 列注释：`id`=主键，BIGSERIAL；`content`=题干正文，不含选项；洁净度由 check_stem_clean 软检查；`options`=选项数组，规范格式 [{"key":"A","text":"..."}]，长度 2-10；`option_count`=选项数量派生列，自动维护，可直接用于筛选与统计；`answer`=正确答案；客观题存选项 key（多选如 "AB"），主观题存参考答案；`analysis`=解析；`rubric`=主观题评分细则；`max_score`=该题满分；`question_type`=题型枚举（实测取值 single/judge/fill/calc/essay/draw）；`answer_type`=作答类型：objective 可自动判分 / subjective 需人工或 LLM 评分；`difficulty`=难度 1-5；`source_kind`=来源性质（权威归类列）：past_exam 真题 / textbook 教材 / chapter_exercise 章节习题 等；`is_past_exam`=是否真题派生列，等价于 source_kind=past_exam，用于索引加速；`source_label`=原始来源标签，仅用于展示，不再承载归类语义；`origin_document_id`=来源文档 ID，可回溯到具体资料；`origin_chunk_id`=来源分块 ID，可回溯到具体片段；`year`=真题年份；source_kind=past_exam 时必填；`paper`=试卷标识，如 2026全国卷；`source_paper`=来源试卷名；`source_page`=来源页码；`question_no`=题号（试卷内序号）；`external_id`=外部题目唯一 ID，用于跨来源去重；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`chapter_id`=权威章节外键；`chapter`=兼容列：章节名；`knowledge_point`=兼容列：知识点名称（正式关联走 question_knowledge_links）；`confidence`=入库置信度：high/medium/low；`quality`=质量评级：A/B/C/incomplete；`ai_generated`=答案解析是否由 AI 生成；`verified`=AI 生成答案是否经过人工或多角色校验；`variant_group`=变式题组 ID，同组内为近似题；`answer_source`=答案来源：bank 题库自带 / source_extract 原文抽取 / llm_generated / user_confirmed；`answer_confidence`=答案置信度 0-1，低于 0.8 不参与自动判分；`is_available`=是否可用（下线标记）；`is_junk`=是否 OCR 碎片或答案串，列表默认排除；`is_retest`=是否复试题（0 初试 / 1 复试）；`figure_missing`=识别图缺失标记：题干引用图表但库内无图；`validation_status`=校验门结果：pending/pass/warn/fail；`validation_errors`=校验门输出的错误明细数组；`validated_at`=最近一次过校验门的时间；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间；`classify_confidence`=导入自动分类整体置信度 0-1（科目×题型置信下限）；`classify_source`=分类来源留痕：keyword/vector/fusion/llm/disagree/none（非 classify_source ENUM 取值域）；`needs_review`=分类低置信待人工复核（进复核队列）；models 侧声明了 index=True，故下方建索引；`images`=???????[{url,page,bbox,kind}] ??????????=??；`question_category`=题目主分类（筛选主键）：真题/练习题/习题/考研题；与 source_kind 正交；`exam_type`=考试类型：考研/期末/期中/竞赛/资格认证/教材课后/模拟/平时；`source_platform`=来源平台：国家高等教育智慧教育平台/中科UMajor/维普/MIT OCW/考试资料网/GitHub 等；`source_url`=来源链接，供溯源与复核

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('quiz_questions_id_seq'::regclass) |
| content | TEXT | 否 |  |
| options | JSONB | 是 |  |
| option_count | SMALLINT | 是 |  |
| answer | TEXT | 是 |  |
| analysis | TEXT | 是 |  |
| rubric | TEXT | 是 |  |
| max_score | REAL | 是 |  |
| question_type | VARCHAR(8) | 否 | 'single'::question_type |
| answer_type | VARCHAR(10) | 否 | 'objective'::answer_type |
| difficulty | SMALLINT | 否 | 3 |
| source_kind | VARCHAR(16) | 否 | 'external_import'::source_kind |
| is_past_exam | BOOLEAN | 是 |  |
| source_label | TEXT | 是 |  |
| origin_document_id | BIGINT | 是 |  |
| origin_chunk_id | BIGINT | 是 |  |
| year | INTEGER | 是 |  |
| paper | VARCHAR(100) | 是 |  |
| source_paper | VARCHAR(200) | 是 |  |
| source_page | INTEGER | 是 |  |
| question_no | INTEGER | 是 |  |
| external_id | VARCHAR(100) | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter_id | BIGINT | 是 |  |
| chapter | VARCHAR(200) | 是 |  |
| knowledge_point | VARCHAR(200) | 是 |  |
| confidence | VARCHAR(6) | 否 | 'medium'::confidence_level |
| quality | VARCHAR(10) | 是 |  |
| ai_generated | BOOLEAN | 否 | false |
| verified | BOOLEAN | 否 | false |
| variant_group | VARCHAR(50) | 是 |  |
| answer_source | VARCHAR(14) | 是 |  |
| answer_confidence | REAL | 是 |  |
| is_available | BOOLEAN | 否 | true |
| is_junk | BOOLEAN | 否 | false |
| is_retest | BOOLEAN | 否 | false |
| figure_missing | SMALLINT | 否 | 0 |
| validation_status | VARCHAR(7) | 否 | 'pending'::question_validation_status |
| validation_errors | JSONB | 否 | '[]'::jsonb |
| validated_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| classify_confidence | DOUBLE PRECISION | 是 |  |
| classify_source | VARCHAR(30) | 是 |  |
| needs_review | BOOLEAN | 是 | false |
| images | JSONB | 是 | '[]'::jsonb |
| question_category | VARCHAR(3) | 否 | '习题'::question_category |
| exam_type | VARCHAR(50) | 是 |  |
| source_platform | VARCHAR(100) | 是 |  |
| source_url | TEXT | 是 |  |

### `quiz_sessions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`mode`=会话模式：chapter_practice 章节练习 / smart_paper 智能组卷 / free_practice 自由练习；`subject_id`=所属科目；`textbook_id`=所属教材（五层结构第2层）；`chapter_id`=所属章（五层结构第3层）；`section_id`=所属节（五层结构第4层）；`knowledge_point_ids`=选中的知识点 ID 数组，空表示该层级下全量出题；`filters`=JSONB 筛选条件：{"question_types":["single","fill"],"difficulty":[2,3,4],"time_limit":1800}；`total_questions`=会话总题数（快照，避免后续题库变动影响统计）；`answered_count`=已作答数；`correct_count`=答对数：客观题自动判分 + 主观题用户自评（对/半对=0.5/错=0）；`duration_seconds`=会话耗时（秒），从 started_at 到 completed_at 或当前时刻；`status`=会话状态：in_progress 进行中 / completed 已完成 / abandoned 已放弃

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('quiz_sessions_id_seq'::regclass) |
| mode | VARCHAR(30) | 否 | 'free_practice'::character varying |
| subject_id | BIGINT | 是 |  |
| textbook_id | BIGINT | 是 |  |
| chapter_id | BIGINT | 是 |  |
| section_id | BIGINT | 是 |  |
| knowledge_point_ids | JSONB | 否 | '[]'::jsonb |
| filters | JSONB | 否 | '{}'::jsonb |
| total_questions | INTEGER | 否 | 0 |
| answered_count | INTEGER | 否 | 0 |
| correct_count | INTEGER | 否 | 0 |
| duration_seconds | INTEGER | 否 | 0 |
| status | VARCHAR(20) | 否 | 'in_progress'::character varying |
| started_at | TIMESTAMP | 否 | now() |
| completed_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `quiz_subject_centroids`

- 类型：**TABLE**
- 行数：3
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| subject | VARCHAR(50) | 否 |  |
| engine | VARCHAR(20) | 否 | 'bge'::character varying |
| dim | INTEGER | 否 |  |
| vector | BYTEA | 否 |  |
| n_samples | INTEGER | 否 | 0 |
| built_at | TIMESTAMP | 否 | now() |

### `retrieval_gate_logs`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/retrieval_gate.py
- 列注释：`query`=用户查询原文；`is_complex`=是否被判为复杂查询；`decision`=门决策：answer / abstain / clarify；`reason_codes`=决策理由码（逗号分隔）；`top1_score`=最高相似度；`topk_mean`=TopK 平均相似度；`top1_margin`=Top1 与第二名的分差；`distinct_doc_count`=命中结果覆盖的文档数；`gate_mode`=门模式：off / soft / strict；`would_abstain`=在对照模式下是否会拒答（用于灰度评估）；`latency_ms`=检索耗时（毫秒）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('retrieval_gate_logs_id_seq'::regclass) |
| query | TEXT | 否 |  |
| is_complex | BOOLEAN | 否 | false |
| decision | VARCHAR(30) | 否 |  |
| reason_codes | TEXT | 是 |  |
| top1_score | REAL | 是 |  |
| topk_mean | REAL | 是 |  |
| top1_margin | REAL | 是 |  |
| distinct_doc_count | INTEGER | 是 |  |
| gate_mode | VARCHAR(30) | 是 |  |
| would_abstain | BOOLEAN | 否 | false |
| latency_ms | INTEGER | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `review_records`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`item_type`=复习对象类型：task / error_record / flashcard / knowledge_point；`item_id`=复习对象 ID；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`result`=SM-2 评分档位：again / hard / good / easy；`grade`=评分 0-5；`mastery_before`=复习前掌握度 0-100；`mastery_after`=复习后掌握度 0-100；`next_review`=本次复习后计算出的下次复习时间（UTC）；`created_at`=复习时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('review_records_id_seq'::regclass) |
| item_type | VARCHAR(20) | 否 |  |
| item_id | BIGINT | 否 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter | VARCHAR(200) | 是 |  |
| result | VARCHAR(5) | 是 |  |
| grade | SMALLINT | 否 | 0 |
| mastery_before | SMALLINT | 否 | 0 |
| mastery_after | SMALLINT | 否 | 0 |
| duration | INTEGER | 否 | 0 |
| interval_after | INTEGER | 否 | 0 |
| next_review | TIMESTAMP | 是 |  |
| note | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `review_schedules`

- 类型：**TABLE**
- 行数：8
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`item_type`=复习对象类型：task / error_record / flashcard / knowledge_point；`item_id`=复习对象 ID；`algorithm`=调度算法：sm2 / fsrs / ebbinghaus；`ease_factor`=SM-2 难度因子 1.3-3.5；`interval_days`=当前复习间隔（天）；`repetitions`=连续答对次数；`lapses`=遗忘次数；`last_reviewed_at`=上次复习时间（UTC）；`next_review_at`=下次复习时间（UTC），到期判定以此列为准；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间；`stability`=FSRS 稳定度（天），R(t) 曲线参数；`difficulty`=FSRS 难度 1-10；`retrievability`=本次复习时的可提取概率 0-1；`state`=0新 1学习 2复习 3重学

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('review_schedules_id_seq'::regclass) |
| item_type | VARCHAR(30) | 否 |  |
| item_id | BIGINT | 否 |  |
| algorithm | VARCHAR(30) | 否 | 'sm2'::character varying |
| ease_factor | REAL | 否 | 2.5 |
| interval_days | INTEGER | 否 | 0 |
| repetitions | INTEGER | 否 | 0 |
| lapses | INTEGER | 否 | 0 |
| last_reviewed_at | TIMESTAMP | 是 |  |
| next_review_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| stability | REAL | 是 |  |
| difficulty | REAL | 是 |  |
| retrievability | REAL | 是 |  |
| state | SMALLINT | 是 | 0 |
| user_id | BIGINT | 是 |  |

### `role_permission`

- 类型：**TABLE**
- 行数：24
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| role | VARCHAR(16) | 否 |  |
| permission | VARCHAR(64) | 否 |  |

### `roles`

- 类型：**TABLE**
- 行数：3
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| role | VARCHAR(16) | 否 |  |
| label | VARCHAR(64) | 否 |  |
| description | TEXT | 是 |  |

### `schema_migrations`

- 类型：**TABLE**
- 行数：49
- ORM 类：—（无 ORM 映射）
- 主要写入方：core/migrations.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| version | TEXT | 否 |  |
| checksum | TEXT | 否 |  |
| applied_at | TIMESTAMP | 否 | now() |
| duration_ms | INTEGER | 是 |  |
| applied_by | TEXT | 是 |  |

### `school_aliases`

- 类型：**TABLE**
- 行数：704
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`alias`=院校别名，唯一，如 华科 / HUST；`school_id`=指向的院校 ID；`alias_type`=别名类型：common 俗称 / abbrev 缩写 / former 曾用名；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('school_aliases_id_seq'::regclass) |
| alias | VARCHAR(100) | 否 |  |
| school_id | BIGINT | 否 |  |
| school_name | VARCHAR(200) | 是 |  |
| alias_type | VARCHAR(20) | 否 | 'common'::character varying |
| created_at | TIMESTAMP | 否 | now() |

### `sft_examples`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`split`=数据划分：train / valid / test；`system`=系统提示词；`user_input`=用户输入；`assistant`=期望回复；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('sft_examples_id_seq'::regclass) |
| split | VARCHAR(20) | 否 | 'train'::character varying |
| system | TEXT | 是 |  |
| user_input | TEXT | 是 |  |
| assistant | TEXT | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `study_events`

- 类型：**TABLE**
- 行数：40
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`event_type`=事件类型：answer / review / focus / plan 等；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`payload`=事件附加数据（JSON 对象）；`occurred_at`=事件发生时间（UTC，带时区），统计以此列为准；`created_at`=入库时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('study_events_id_seq'::regclass) |
| event_type | VARCHAR(50) | 否 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter_id | BIGINT | 是 |  |
| knowledge_point_id | BIGINT | 是 |  |
| question_id | BIGINT | 是 |  |
| session_id | BIGINT | 是 |  |
| is_correct | BOOLEAN | 是 |  |
| duration_seconds | INTEGER | 是 |  |
| payload | JSONB | 否 | '{}'::jsonb |
| occurred_at | TIMESTAMP | 否 | now() |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `study_sessions`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`duration`=学习时长（分钟）；`subject_id`=权威科目外键；`subject`=兼容列：科目中文名

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('study_sessions_id_seq'::regclass) |
| date | DATE | 否 |  |
| duration | INTEGER | 否 | 0 |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| task_type | VARCHAR(50) | 是 |  |
| remark | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `study_stats`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`subject_durations`=各科时长（JSON 对象，key 为科目 code）；`new_knowledge_count`=当日新增知识点数

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('study_stats_id_seq'::regclass) |
| date | DATE | 否 |  |
| total_duration | INTEGER | 否 | 0 |
| subject_durations | JSONB | 否 | '{}'::jsonb |
| task_completed | INTEGER | 否 | 0 |
| error_count | INTEGER | 否 | 0 |
| new_knowledge_count | INTEGER | 否 | 0 |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `subject_aliases`

- 类型：**TABLE**
- 行数：25
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`alias`=别名原字符串，如 公共课-数学 / 408 / 数模电；`subject_id`=指向的权威备考科目 ID；`alias_source`=别名来源：legacy_code 旧代码 / import 导入 / user 用户输入；`is_primary`=一个别名命中多行时，本行是否为首选解析结果；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('subject_aliases_id_seq'::regclass) |
| alias | VARCHAR(100) | 否 |  |
| subject_id | BIGINT | 否 |  |
| alias_source | VARCHAR(50) | 否 | 'legacy_code'::character varying |
| is_primary | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 否 | now() |

### `subject_chapters`

- 类型：**TABLE**
- 行数：266
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`subject_id`=所属备考科目 ID；`code`=章节代码，同一科目内唯一；`title`=章节标题；`parent_id`=父章节 ID，支持"章→节"两级；`sort_order`=章节内排序权重，升序；`is_active`=是否启用；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('subject_chapters_id_seq'::regclass) |
| subject_id | BIGINT | 否 |  |
| code | VARCHAR(64) | 否 |  |
| title | VARCHAR(300) | 否 |  |
| parent_id | BIGINT | 是 |  |
| sort_order | INTEGER | 否 | 0 |
| is_active | BOOLEAN | 否 | true |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `subject_configs`

- 类型：**TABLE**
- 行数：47
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`subject_id`=所属备考科目 ID，一对一；`question_types`=该科目支持的题型数组，元素为 question_type 枚举值字符串；`is_custom`=是否用户自定义配置；`extra`=扩展配置项（JSON 对象）；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('subject_configs_id_seq'::regclass) |
| subject_id | BIGINT | 否 |  |
| question_types | JSONB | 否 | '[]'::jsonb |
| is_custom | BOOLEAN | 否 | false |
| extra | JSONB | 否 | '{}'::jsonb |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `subject_discipline_links`

- 类型：**TABLE**
- 行数：28
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`subject_id`=备考科目 ID；`discipline_id`=招生学科 ID；`is_primary`=是否为主映射（一科对多科时用于默认归类）；`created_at`=创建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('subject_discipline_links_id_seq'::regclass) |
| subject_id | BIGINT | 否 |  |
| discipline_id | BIGINT | 否 |  |
| is_primary | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 否 | now() |

### `subject_prototypes`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`subject_id`=所属备考科目 ID；`engine`=生成该向量的引擎：bge / openai / unknown；`dim`=向量维度，实测 512；`prototype`=原型向量的 float32 小端字节数组；`n_samples`=构建该原型使用的样本数；`built_at`=构建时间（UTC，带时区）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('subject_prototypes_id_seq'::regclass) |
| subject_id | BIGINT | 否 |  |
| engine | VARCHAR(7) | 否 | 'unknown'::vector_engine |
| dim | INTEGER | 否 |  |
| prototype | BYTEA | 否 |  |
| n_samples | INTEGER | 否 | 0 |
| built_at | TIMESTAMP | 否 | now() |
| prototype_vec | NULL | 是 |  |

### `subject_removals`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/taxonomy.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| subject | TEXT | 否 |  |
| removed_at | TIMESTAMP | 否 | now() |

### `subjects`

- 类型：**TABLE**
- 行数：84
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/study/goals.py、services/codebank_service.py、services/taxonomy.py
- 列注释：`code`=权威科目代码（如 politics/english/math/circuit），代码与外键引用的唯一键；`name`=科目中文名，仅用于展示；`short_name`=科目简称，用于窄屏与标签展示；`category`=科目分类：public 公共课 / professional 专业课 / retest 复试科目；`parent_id`=父科目 ID，用于"专业课→子模块"两级结构，顶级为 NULL；`exam_overlap`=科目间的考纲重叠说明，供跨科目去重与出题范围提示；`description`=科目说明；`sort_order`=展示排序权重，升序；`is_active`=是否启用，停用的科目不参与出题与统计；`is_custom`=是否用户自定义科目；`legacy_names`=历史中文名数组，保留"光学/光学工程/光学与工程光学"等旧写法用于 ETL 归档；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间，由 set_updated_at 触发器维护

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('subjects_id_seq'::regclass) |
| code | VARCHAR(32) | 否 |  |
| name | VARCHAR(100) | 否 |  |
| short_name | VARCHAR(50) | 是 |  |
| category | VARCHAR(12) | 否 | 'professional'::subject_category |
| parent_id | BIGINT | 是 |  |
| exam_overlap | TEXT | 是 |  |
| description | TEXT | 是 |  |
| sort_order | INTEGER | 否 | 0 |
| is_active | BOOLEAN | 否 | true |
| is_custom | BOOLEAN | 否 | false |
| legacy_names | JSONB | 否 | '[]'::jsonb |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `tasks`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`subject_id`=权威科目外键；`subject`=兼容列：科目中文名；`chapter_id`=权威章节外键；`stage`=备考阶段：basic 基础 / intensive 强化 / sprint 冲刺 / retest 复试；`status`=任务状态：pending / doing / done / cancelled；`next_review`=下次复习时间（UTC），兼容列，真值在 review_schedules；`review_count`=已复习次数；`completed_at`=完成时间；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('tasks_id_seq'::regclass) |
| title | VARCHAR(300) | 否 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter_id | BIGINT | 是 |  |
| task_type | VARCHAR(50) | 是 |  |
| stage | VARCHAR(9) | 是 |  |
| status | VARCHAR(9) | 否 | 'pending'::task_status |
| due_date | DATE | 是 |  |
| priority | SMALLINT | 否 | 0 |
| next_review | TIMESTAMP | 是 |  |
| review_count | INTEGER | 否 | 0 |
| completed_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `textbook_documents`

- 类型：**TABLE**
- 行数：23
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`textbook_id`=教材 ID；`document_id`=文档 ID；`doc_role`=文档角色：body 正文 / exercise 习题 / answer 答案 / slides 讲义 / scan 扫描件

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('textbook_documents_id_seq'::regclass) |
| textbook_id | BIGINT | 否 |  |
| document_id | BIGINT | 否 |  |
| doc_role | VARCHAR(30) | 否 | 'body'::character varying |
| created_at | TIMESTAMP | 否 | now() |

### `textbook_schools`

- 类型：**TABLE**
- 行数：20
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`textbook_id`=教材 ID；`school_id`=院校 ID，与 kaoyan_schools 打通；`usage_note`=该校具体用法，保留原始目录中的表述；`exam_stage`=该校使用阶段；`is_official`=是否官方指定（相对「常见考情归纳」）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('textbook_schools_id_seq'::regclass) |
| textbook_id | BIGINT | 否 |  |
| school_id | BIGINT | 否 |  |
| usage_note | VARCHAR(200) | 是 |  |
| exam_stage | VARCHAR(2) | 是 |  |
| is_official | BOOLEAN | 否 | false |
| created_at | TIMESTAMP | 否 | now() |

### `textbooks`

- 类型：**TABLE**
- 行数：26
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`title`=教材书名（不含版次）；`subtitle`=副标题，如「理论、方法和应用」；`edition`=版次，如「第3版」「第5/6版」；多版通用时保留原始写法；`authors`=作者，多作者用「、」分隔；译者用括注；`publisher`=出版社；`isbn`=ISBN（13位，去连字符）；未知时为 NULL，禁止编造；`pub_year`=出版年份，未知时为 NULL；`subject_id`=所属备考科目外键，禁止硬编码中文科目名；`exam_stages`=适用阶段数组：初试 / 复试；同一教材可两用；`role`=教材定位：main 主教材 / reference 参考书 / exercise 习题册 / supplement 补充；`summary`=教材内容概要；`note`=使用说明，如「贵大834核心教材」；`school_count`=使用该教材的院校数（冗余列，由视图刷新）；`source`=数据来源标识：manual_catalog 人工整理目录 / official 官方指定；`confidence`=数据可信度：官方指定为 high，常见考情归纳为 medium；`is_active`=是否启用；`sort_order`=展示排序权重，升序

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('textbooks_id_seq'::regclass) |
| title | VARCHAR(300) | 否 |  |
| subtitle | VARCHAR(300) | 是 |  |
| edition | VARCHAR(50) | 是 |  |
| authors | TEXT | 否 |  |
| publisher | VARCHAR(200) | 是 |  |
| isbn | VARCHAR(20) | 是 |  |
| pub_year | INTEGER | 是 |  |
| subject_id | BIGINT | 是 |  |
| exam_stages | ARRAY | 否 | '{}'::exam_stage[] |
| role | VARCHAR(50) | 否 | 'main'::character varying |
| summary | TEXT | 是 |  |
| note | TEXT | 是 |  |
| school_count | INTEGER | 否 | 0 |
| source | VARCHAR(100) | 否 | 'manual_catalog'::character varying |
| confidence | VARCHAR(6) | 否 | 'medium'::confidence_level |
| is_active | BOOLEAN | 否 | true |
| sort_order | INTEGER | 否 | 0 |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `third_party_accounts`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`access_token_encrypted`=AES-256-GCM加密的access_token；`refresh_token_encrypted`=AES-256-GCM加密的refresh_token

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('third_party_accounts_id_seq'::regclass) |
| user_id | BIGINT | 否 |  |
| provider | VARCHAR(50) | 否 |  |
| uk_provider_uid | VARCHAR(200) | 否 |  |
| access_token_encrypted | BYTEA | 是 |  |
| refresh_token_encrypted | BYTEA | 是 |  |
| token_expires_at | TIMESTAMP | 是 |  |
| account_name | VARCHAR(200) | 是 |  |
| is_active | BOOLEAN | 否 | true |
| last_synced_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `universities_legacy`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`score_lines`=历史分数线（JSON 对象）；`admission_ratio`=历史报录比文本；`difficulty`=难度评级

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('universities_legacy_id_seq'::regclass) |
| name | VARCHAR(200) | 否 |  |
| type | VARCHAR(50) | 是 |  |
| city | VARCHAR(50) | 是 |  |
| major_name | VARCHAR(200) | 是 |  |
| score_lines | JSONB | 是 |  |
| admission_ratio | VARCHAR(50) | 是 |  |
| difficulty | SMALLINT | 是 |  |
| remark | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `users`

- 类型：**TABLE**
- 行数：4
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`username`=登录名；`password_hash`=PBKDF2 哈希，库内无明文；`display_name`=显示名；`role`=admin | user；`is_active`=禁用即会话失效；`must_change_password`=首登/重置后强制改密；`token_version`=会话版本号；`last_login_at`=最近登录（UTC）；`deleted_at`=软删除时间戳：非空表示该用户已被删除（列表隐藏 / 登录拒绝 / 用户名被占用）；清空即恢复

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 | nextval('users_id_seq'::regclass) |
| username | VARCHAR(64) | 否 |  |
| password_hash | VARCHAR(255) | 否 |  |
| display_name | VARCHAR(64) | 是 |  |
| role | VARCHAR(16) | 否 |  |
| is_active | BOOLEAN | 否 |  |
| must_change_password | BOOLEAN | 否 |  |
| token_version | INTEGER | 否 |  |
| last_login_at | TIMESTAMP | 是 |  |
| created_at | TIMESTAMP | 是 |  |
| updated_at | TIMESTAMP | 是 |  |
| deleted_at | TIMESTAMP | 是 |  |
| email | VARCHAR(255) | 是 |  |
| email_verified_at | TIMESTAMP | 是 |  |
| status | VARCHAR(20) | 否 | 'active'::character varying |
| disabled_reason | TEXT | 是 |  |
| disabled_at | TIMESTAMP | 是 |  |
| deletion_requested_at | TIMESTAMP | 是 |  |
| last_login_ip | VARCHAR(64) | 是 |  |
| login_count | INTEGER | 否 | 0 |

### `watermark_lexicon`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/platform/watermark_admin.py、services/content_sanitizer.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| phrase | TEXT | 否 |  |
| doc_count | INTEGER | 否 | 0 |
| hit_count | INTEGER | 否 | 0 |
| confidence | REAL | 否 | 0.5 |
| enabled | BOOLEAN | 否 | true |
| auto_learned | BOOLEAN | 否 | true |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `weak_knowledge`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：services/qa_foundation.py

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | INTEGER | 否 |  |
| knowledge_point | TEXT | 否 |  |
| subject | VARCHAR(50) | 是 |  |
| wrong_count | INTEGER | 是 | 0 |
| total_count | INTEGER | 是 | 0 |
| accuracy | REAL | 是 |  |
| mastery | REAL | 是 |  |
| last_wrong_at | TIMESTAMP | 是 |  |
| updated_at | TIMESTAMP | 是 |  |

### `week_plans`

- 类型：**TABLE**
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`month_plan_id`=所属月计划 ID；`week_start`=周起始日期（周一）；`daily_records`=每日完成记录（JSON 对象，key 为日期）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('week_plans_id_seq'::regclass) |
| month_plan_id | BIGINT | 是 |  |
| week_start | DATE | 否 |  |
| tasks | JSONB | 否 | '[]'::jsonb |
| daily_records | JSONB | 否 | '{}'::jsonb |
| completion | TEXT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `word_decks`

- 类型：**TABLE**
- 行数：5
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）
- 列注释：`name`=单词本名称，唯一；`description`=单词本描述；`source`=来源：考研大纲 / 真题词频 / 自定义；`word_count`=单词总数（冗余，由触发器维护）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('word_decks_id_seq'::regclass) |
| name | VARCHAR(200) | 否 |  |
| description | VARCHAR(500) | 是 |  |
| source | VARCHAR(100) | 是 |  |
| word_count | INTEGER | 否 | 0 |
| created_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |

### `word_examples`

- 类型：**TABLE**
- 行数：26842
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('word_examples_id_seq'::regclass) |
| word_id | BIGINT | 否 |  |
| word | VARCHAR(100) | 否 |  |
| sentence_en | TEXT | 否 |  |
| sentence_cn | TEXT | 是 |  |
| source | VARCHAR(20) | 否 | 'tatoeba'::character varying |
| sentence_id | BIGINT | 是 |  |
| created_at | TIMESTAMP | 否 | now() |

### `word_roots`

- 类型：**TABLE**
- 行数：611
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（未在 routers/services 命中写入语句）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('word_roots_id_seq'::regclass) |
| morpheme | VARCHAR(200) | 否 |  |
| variants | JSONB | 是 |  |
| type | VARCHAR(20) | 否 |  |
| subtype | VARCHAR(20) | 否 | ''::character varying |
| origin | VARCHAR(100) | 是 |  |
| meaning | TEXT | 是 |  |
| meaning_cn | TEXT | 是 |  |
| explanation | TEXT | 是 |  |
| example_words | JSONB | 是 |  |
| word_count | INTEGER | 是 | 0 |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |

### `words`

- 类型：**TABLE**
- 行数：11664
- ORM 类：—（无 ORM 映射）
- 主要写入方：routers/study/quiz.py、routers/study/words.py
- 列注释：`deck_id`=所属单词本 ID，单词本删除时级联删除；`word`=单词，同一单词本内唯一；`phonetic`=音标；`pos`=词性；`meaning`=释义；`root`=词根词缀；`example`=英文例句；`example_cn`=例句翻译；`tag`=标签：高频 / 熟词僻义 / 词组；`status`=掌握状态（复用 mastery_level 枚举）；`due_date`=下次到期日期；`review_history`=复习历史数组（JSON）；`created_at`=创建时间（UTC，带时区）；`updated_at`=最后更新时间

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 否 | nextval('words_id_seq'::regclass) |
| deck_id | BIGINT | 是 |  |
| word | VARCHAR(100) | 否 |  |
| phonetic | VARCHAR(100) | 是 |  |
| pos | VARCHAR(50) | 是 |  |
| meaning | TEXT | 否 |  |
| root | VARCHAR(300) | 是 |  |
| example | TEXT | 是 |  |
| example_cn | TEXT | 是 |  |
| tag | VARCHAR(50) | 是 |  |
| status | VARCHAR(12) | 否 | 'not_mastered'::mastery_level |
| ease_factor | REAL | 否 | 2.5 |
| interval_days | INTEGER | 否 | 0 |
| reps | INTEGER | 否 | 0 |
| lapses | INTEGER | 否 | 0 |
| due_date | DATE | 是 |  |
| last_review | DATE | 是 |  |
| review_history | JSONB | 否 | '[]'::jsonb |
| created_at | TIMESTAMP | 否 | now() |
| updated_at | TIMESTAMP | 否 | now() |
| user_id | BIGINT | 是 |  |
| extra | JSONB | 是 |  |

## 二、视图（9 个）

### `kaoyan_subjects`

- 类型：**VIEW**（READONLY）
- 行数：97
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 是 |  |
| code | VARCHAR(20) | 是 |  |
| name | VARCHAR(100) | 是 |  |
| category | VARCHAR(50) | 是 |  |
| parent_code | VARCHAR(20) | 是 |  |
| exam_overlap | TEXT | 是 |  |
| description | TEXT | 是 |  |
| sort_order | INTEGER | 是 |  |
| created_at | TIMESTAMP | 是 |  |

### `knowledge_points_legacy`

- 类型：**VIEW**（READONLY）
- 行数：5262
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| id | BIGINT | 是 |  |
| name | VARCHAR(300) | 是 |  |
| subject_id | BIGINT | 是 |  |
| subject | VARCHAR(50) | 是 |  |
| chapter_id | BIGINT | 是 |  |
| chapter | VARCHAR(200) | 是 |  |
| parent_id | BIGINT | 是 |  |
| document_id | BIGINT | 是 |  |
| source_chunk_id | BIGINT | 是 |  |
| source_chunk_index | INTEGER | 是 |  |
| extract_source | VARCHAR(12) | 是 |  |
| subject_source | VARCHAR(20) | 是 |  |
| exam_frequency | SMALLINT | 是 |  |
| difficulty | SMALLINT | 是 |  |
| question_types | JSONB | 是 |  |
| description | TEXT | 是 |  |
| review_count | INTEGER | 是 |  |
| last_review | TIMESTAMP | 是 |  |
| ease_factor | REAL | 是 |  |
| interval_days | INTEGER | 是 |  |
| lapses | INTEGER | 是 |  |
| question_count | INTEGER | 是 |  |
| created_at | TIMESTAMP | 是 |  |
| updated_at | TIMESTAMP | 是 |  |
| mastery | INTEGER | 是 |  |
| next_review | TIMESTAMP | 是 |  |
| mastery_attempts | BIGINT | 是 |  |
| mastery_correct | BIGINT | 是 |  |

### `pg_stat_statements`

- 类型：**VIEW**（READONLY）
- 行数：4941
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| userid | OID | 是 |  |
| dbid | OID | 是 |  |
| toplevel | BOOLEAN | 是 |  |
| queryid | BIGINT | 是 |  |
| query | TEXT | 是 |  |
| plans | BIGINT | 是 |  |
| total_plan_time | DOUBLE PRECISION | 是 |  |
| min_plan_time | DOUBLE PRECISION | 是 |  |
| max_plan_time | DOUBLE PRECISION | 是 |  |
| mean_plan_time | DOUBLE PRECISION | 是 |  |
| stddev_plan_time | DOUBLE PRECISION | 是 |  |
| calls | BIGINT | 是 |  |
| total_exec_time | DOUBLE PRECISION | 是 |  |
| min_exec_time | DOUBLE PRECISION | 是 |  |
| max_exec_time | DOUBLE PRECISION | 是 |  |
| mean_exec_time | DOUBLE PRECISION | 是 |  |
| stddev_exec_time | DOUBLE PRECISION | 是 |  |
| rows | BIGINT | 是 |  |
| shared_blks_hit | BIGINT | 是 |  |
| shared_blks_read | BIGINT | 是 |  |
| shared_blks_dirtied | BIGINT | 是 |  |
| shared_blks_written | BIGINT | 是 |  |
| local_blks_hit | BIGINT | 是 |  |
| local_blks_read | BIGINT | 是 |  |
| local_blks_dirtied | BIGINT | 是 |  |
| local_blks_written | BIGINT | 是 |  |
| temp_blks_read | BIGINT | 是 |  |
| temp_blks_written | BIGINT | 是 |  |
| blk_read_time | DOUBLE PRECISION | 是 |  |
| blk_write_time | DOUBLE PRECISION | 是 |  |
| temp_blk_read_time | DOUBLE PRECISION | 是 |  |
| temp_blk_write_time | DOUBLE PRECISION | 是 |  |
| wal_records | BIGINT | 是 |  |
| wal_fpi | BIGINT | 是 |  |
| wal_bytes | NUMERIC | 是 |  |
| jit_functions | BIGINT | 是 |  |
| jit_generation_time | DOUBLE PRECISION | 是 |  |
| jit_inlining_count | BIGINT | 是 |  |
| jit_inlining_time | DOUBLE PRECISION | 是 |  |
| jit_optimization_count | BIGINT | 是 |  |
| jit_optimization_time | DOUBLE PRECISION | 是 |  |
| jit_emission_count | BIGINT | 是 |  |
| jit_emission_time | DOUBLE PRECISION | 是 |  |

### `pg_stat_statements_info`

- 类型：**VIEW**（READONLY）
- 行数：1
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| dealloc | BIGINT | 是 |  |
| stats_reset | TIMESTAMP | 是 |  |

### `subject_config`

- 类型：**VIEW**（READONLY）
- 行数：84
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| subject | VARCHAR(100) | 是 |  |
| chapters | JSONB | 是 |  |
| question_types | JSONB | 是 |  |
| is_custom | BOOLEAN | 是 |  |
| created_at | TIMESTAMP | 是 |  |
| updated_at | TIMESTAMP | 是 |  |

### `subject_prototypes_by_name`

- 类型：**VIEW**（READONLY）
- 行数：0
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| subject | VARCHAR(100) | 是 |  |
| engine | VARCHAR(7) | 是 |  |
| dim | INTEGER | 是 |  |
| prototype | BYTEA | 是 |  |
| n_samples | INTEGER | 是 |  |
| built_at | TIMESTAMP | 是 |  |

### `v_chunk_vector_coverage`

- 类型：**VIEW**（READONLY）
- 行数：18
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| subject_id | BIGINT | 是 |  |
| total_chunks | BIGINT | 是 |  |
| vectorized_chunks | BIGINT | 是 |  |
| missing_chunks | BIGINT | 是 |  |
| coverage_pct | NUMERIC | 是 |  |

### `v_knowledge_mastery`

- 类型：**VIEW**（READONLY）
- 行数：5262
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| knowledge_point_id | BIGINT | 是 |  |
| subject_id | BIGINT | 是 |  |
| attempts | BIGINT | 是 |  |
| correct | BIGINT | 是 |  |
| mastery | INTEGER | 是 |  |
| mastery_level | VARCHAR(12) | 是 |  |
| last_activity_at | TIMESTAMP | 是 |  |

### `v_question_health`

- 类型：**VIEW**（READONLY）
- 行数：35
- ORM 类：—（无 ORM 映射）
- 主要写入方：—（视图只读）

| 列 | 类型 | 可空 | 默认 |
|---|---|---|---|
| subject_id | BIGINT | 是 |  |
| total | BIGINT | 是 |  |
| no_options | BIGINT | 是 |  |
| no_answer | BIGINT | 是 |  |
| no_analysis | BIGINT | 是 |  |
| junk | BIGINT | 是 |  |
| figure_missing | BIGINT | 是 |  |
| failed | BIGINT | 是 |  |
| warned | BIGINT | 是 |  |

## 三、ORM 未覆盖表清单

共 114 张（作为 models 拆分的输入，见 04 文档）：

- `ai_providers`
- `annotation_samples`
- `answer_candidates`
- `answer_records`
- `answer_review_queue`
- `audit_logs`
- `auth_events`
- `chunk_vectors`
- `code_problem_tags`
- `code_problem_testcases`
- `code_problems`
- `code_questions`
- `code_subjects`
- `code_submission_results`
- `code_submissions`
- `code_tags`
- `conflict_review_queue`
- `crawl_dead_letters`
- `crawl_jobs`
- `crawl_pages`
- `custom_links`
- `daily_plans`
- `disciplines`
- `document_blocks`
- `document_pages`
- `documents`
- `early_bird_records`
- `ebbinghaus_items`
- `email_tokens`
- `error_knowledge_links`
- `error_records`
- `eval_runs`
- `exam_answers`
- `exam_blueprints`
- `exam_sessions`
- `favorites`
- `flashcards`
- `focus_sessions`
- `goals`
- `kaoyan_admission_details`
- `kaoyan_admissions`
- `kaoyan_alert_records`
- `kaoyan_alert_runs`
- `kaoyan_collection_runs`
- `kaoyan_colleges`
- `kaoyan_crawl_targets`
- `kaoyan_major_kb_link`
- `kaoyan_majors`
- `kaoyan_national_lines`
- `kaoyan_notices`
- `kaoyan_reforms`
- `kaoyan_schools`
- `kaoyan_scorelines`
- `kaoyan_subscriptions`
- `knowledge_chunks`
- `knowledge_point_relations`
- `knowledge_points`
- `memory_facts`
- `memory_synthesis`
- `memory_traces`
- `milestones`
- `misconceptions`
- `month_plans`
- `netdisk_file_cache`
- `netdisk_files`
- `netdisk_operation_logs`
- `notice_user_states`
- `paper_answers`
- `paper_attempts`
- `paper_questions`
- `papers`
- `pending_questions`
- `phase_daily_reviews`
- `phase_plans`
- `platform_configs`
- `preview_sessions`
- `question_images`
- `question_knowledge_links`
- `quiz_attempts`
- `quiz_questions`
- `quiz_sessions`
- `quiz_subject_centroids`
- `retrieval_gate_logs`
- `review_records`
- `review_schedules`
- `role_permission`
- `roles`
- `schema_migrations`
- `school_aliases`
- `sft_examples`
- `study_events`
- `study_sessions`
- `study_stats`
- `subject_aliases`
- `subject_chapters`
- `subject_configs`
- `subject_discipline_links`
- `subject_prototypes`
- `subject_removals`
- `subjects`
- `tasks`
- `textbook_documents`
- `textbook_schools`
- `textbooks`
- `third_party_accounts`
- `universities_legacy`
- `users`
- `watermark_lexicon`
- `weak_knowledge`
- `week_plans`
- `word_decks`
- `word_examples`
- `word_roots`
- `words`
