-- =============================================================================
-- pg_schema.sql —— PostgreSQL 16.15 完整 DDL 主入口
--
-- 目标数据库：PostgreSQL 16.15（免安装便携版，D:\pgsql，端口 5432，库名 kaoyan）
-- 迁移来源：SQLite D:\平台\database\kaoyan.db（670MB / 67 表 / 146 索引）
--
-- 执行方式（任选其一）：
--   1) psql 直接执行本文件（会自动按序 \ir 引入分片）：
--        psql -U postgres -d kaoyan -f core/pg_schema.sql
--   2) Python 侧（推荐，与 VECTOR_BACKEND 开关联动）：
--        from core.db_session import apply_schema; apply_schema()
--
-- 分片清单（顺序即依赖顺序，不得调换）：
--   \ir sql/000_extensions_and_enums.sql   扩展 / 26 个 ENUM / 通用函数
--   \ir sql/010_system_config.sql          科目权威源 / 章节 / 平台配置
--   \ir sql/020_documents.sql              文档 / 知识分块 / 分块向量
--   \ir sql/030_knowledge.sql              知识点 / 知识点关系
--   \ir sql/040_questions.sql              题库 / 试卷 / 模考
--   \ir sql/050_learning.sql               目标 / 任务 / 计划 / 复习 / 错题
--   \ir sql/060_schools.sql                院校 / 专业 / 通知 / 分数线
--   \ir sql/070_words_misc.sql             单词 / 网盘 / 训练评测
--   \ir sql/080_views_and_gates.sql        派生视图 / 校验门 / 兼容层
--
-- 全局约定：
--   主键      BIGSERIAL（统一 64 位，避免 SQLite 的 INTEGER 隐式行号问题）
--   时间      TIMESTAMPTZ（统一带时区，入库一律 UTC）
--   外键      全部显式声明 ON DELETE 行为，禁止缺省
--   枚举      PG 原生 ENUM，取值见 000，禁止再写裸 String(20/50)
--   注释      每表每列均有 COMMENT ON，缺失即视为未完成
--
-- =============================================================================

\set ON_ERROR_STOP on
\timing on

\echo '== [01/15] 扩展与枚举 =='
\ir sql/000_extensions_and_enums.sql

\echo '== [02/15] 科目权威源与章节 =='
\ir sql/010_system_config.sql

\echo '== [03/15] 平台对接与 AI 供应商 =='
\ir sql/011_system_platform.sql

\echo '== [04/15] 文档与知识分块 =='
\ir sql/020_documents.sql

\echo '== [05/15] 知识点 =='
\ir sql/030_knowledge.sql

\echo '== [06/15] 题目主表与校验函数 =='
\ir sql/040_questions.sql

\echo '== [07/15] 试卷与模考 =='
\ir sql/041_papers_exams.sql

\echo '== [08/15] 复习调度 / 目标 / 任务 =='
\ir sql/050_learning.sql

\echo '== [09/15] 计划体系 / 专注 / 艾宾浩斯 =='
\ir sql/051_planning.sql

\echo '== [10/15] 学习统计 / 事件流 / 节点 =='
\ir sql/052_study_stats.sql

\echo '== [11/15] 院校 / 专业 / 招生 / 分数线 =='
\ir sql/060_schools.sql

\echo '== [12/15] 通知 / 订阅 / 提醒 =='
\ir sql/061_notices.sql

\echo '== [13/19] 单词与辅助 =='
\ir sql/070_words_misc.sql

\echo '== [14/19] knowledge_points 兼容列（必须先于视图） =='
-- 顺序说明（2026-10-14 修正）：
--   094a 只做 ADD COLUMN / CREATE INDEX，不碰视图，因此可以安全地排在最前。
--   若兼容列在视图之后加，081 的 knowledge_points_legacy（SELECT kp.*）
--   列数会偏移，重跑报 "cannot change name of view column ... to next_review"。
\ir sql/094a_kp_mastery_columns.sql

\echo '== [15/19] 派生视图 =='
\ir sql/080_views_and_gates.sql

\echo '== [16/19] 校验门与兼容层 =='
\ir sql/081_gates.sql

\echo '== [17/19] 教材域 =='
\ir sql/090_textbooks.sql

\echo '== [18/19] 电子通信核心科目补齐 =='
\ir sql/091_subjects_ece_seed.sql

\echo '== [19/19] subject_config 兼容视图可写化 + knowledge_points 触发器/回填 =='
\ir sql/092_subject_config_writable.sql
\ir sql/093_kp_mastery_compat.sql

\echo '== [20/20] quiz_questions 导入分类闸门列（classify_* / needs_review） =='
-- 依赖 040_questions.sql 建出的 quiz_questions，故排在序列末尾。
\ir sql/095_quiz_classify_columns.sql

\echo '== [21/21] documents 违禁/废弃标记列（is_junk） =='
-- 依赖 documents 建表分片，紧随 095。
\ir sql/096_documents_junk_flag.sql

\echo '== [22/22] 水印自学习词库（watermark_lexicon） =='
-- 无外键依赖，紧随 096。此前 DDL 只写在 Python 里，测试库缺表。
\ir sql/097_watermark_lexicon.sql

\echo '== [23/23] 运行时懒建表收编（weak_knowledge / *_review_queue） =='
-- 此前只在服务里用 SQLite 风格 DDL 懒建且静默吞异常，PG 上整体缺表。
\ir sql/098_runtime_tables.sql

\echo '== [24/24] 全站收藏（favorites） =='
\ir sql/099_favorites.sql

-- 平台凭据列改宽：AES-256-GCM 密文比明文长，见 sql/100 头注释
\echo '== 追加：platform_configs 凭据列改宽 text =='
\ir sql/100_platform_credential_width.sql

-- 仪表盘 D-06/D-07 的"目标值"出处：goals 每日目标四列（全部可空，NULL=未设目标）
\echo '== 追加：goals 每日学习目标四列 =='
\ir sql/101_goal_daily_targets.sql

-- 院校采集开关：此前只有 ORM 建表（naive timestamp），收编为 TIMESTAMPTZ，见 sql/105 头注释
\echo '== 追加：kaoyan_crawl_targets 收编 =='
\ir sql/105_kaoyan_crawl_targets.sql

-- 科目删除墓碑：DELETE 返回 200 但科目被 ensure_subject_config_seeds 复活的问题，
-- 见 sql/106 头注释。须在 092（可写视图触发器）之后。
\echo '== 追加：subject_removals 删除墓碑 =='
\ir sql/106_subject_removals.sql

-- --------------------------------------------------------------------------- #
-- 补接漏引用的分片（2026-10-18 生产故障修复）
--                                                                             #
-- 背景：以下分片写在 core/sql/ 里，但 pg_schema.sql 的 \ir 区从未引用它们，     #
-- 生产库因此从未建出对应表/列。症状是一批接口集体 500：                        #
--   * audit_logs 缺失          -> 新建/修改/重置用户全部 500（审计写库）        #
--   * kaoyan_schools.enabled   -> 院校管理/目标策略/分数详情 500                #
--   * papers.year / paper_type -> 试卷索引与模考报告 500                       #
--   * quiz_sessions            -> 刷题会话追踪缺表                              #
--   * 网盘四表                 -> 网盘缓存统计 500                              #
-- 根因是"加了分片却忘了接 \ir"，且没有门禁校验这一点。                          #
-- 修复：按依赖顺序补接 + project_healthcheck 新增"分片必须被引用"检查。         #
-- --------------------------------------------------------------------------- #

\echo '== 补接 1/8：users 账号表（104） =='
\ir sql/104_users.sql

\echo '== 补接 2/8：刷题会话 quiz_sessions / quiz_attempts（095） =='
-- 依赖 subjects/textbooks/subject_chapters（010/090），无新增依赖。
\ir sql/095_quiz_sessions.sql

\echo '== 补接 3/8：papers 年份/卷种轴 + paper_attempts（096） =='
-- 依赖 papers（041）。
\ir sql/096_papers_year_type.sql

\echo '== 补接 4/8：代码 OJ 四表（097） =='
-- 判题 Worker 因 2C2G 暂缓挂载，表先按权威口径就位。
\ir sql/097_code_oj.sql

\echo '== 补接 5/8：review_schedules FSRS 三要素（102） =='
-- 依赖 review_schedules（050）。
\ir sql/102_review_schedules_fsrs.sql

\echo '== 补接 6/8：院校后台审计 audit_logs + 软删除列 + 触发器（102 schools） =='
-- 依赖 kaoyan_schools/colleges/majors/admissions/scorelines（060）。
\ir sql/102_schools_admin_schema.sql

\echo '== 补接 7/8：网盘四表 third_party_accounts 等（103 netdisk） =='
-- 无外键依赖（user_id 仅逻辑关联）。
\ir sql/103_netdisk_four_tables.sql

\echo '== 补接 8/8：历史调度数据回填（103 backfill，幂等 DO NOTHING） =='
-- 依赖 review_schedules（050）+ FSRS 列（102），故排在两者之后。
\ir sql/103_backfill_review_schedules.sql

-- 用户软删除：DELETE /api/admin/users/{id} 原本 405（无端点），改为 deleted_at
-- 软删 + 可恢复；见 sql/107 头注释。
-- 位置纪律：107 做 ALTER TABLE users，**必须排在 104 建 users 之后**，
-- 否则 users 尚未建出就 ALTER，整份 DDL 中止（踩过一次：apply 报
-- relation "users" does not exist，后续 audit_logs/subject_removals 全部没建）。
\echo '== 追加：users 软删除列（107，依赖 104 已建 users） =='
\ir sql/107_users_soft_delete.sql

-- 国家线表收编（2026-10-23 规整归一）：此前只由一次性导入脚本建表，
-- 不在权威 schema 中，全新库 GET /api/kaoyan/national-lines 直接 500。
\echo '== 追加：kaoyan_national_lines 国家线表（114） =='
\ir sql/114_kaoyan_national_lines.sql

-- 三层可审计记忆（55 号方案 P0-1，DeepTutor DPM/Trace Forest 借鉴）：
-- L1 原始轨迹 -> L2 摘要事实 -> L3 综合画像，全部支持用户纠错溯源。
-- 依赖 users / quiz_questions / documents / knowledge_points，故排在序列末尾。
\echo '== 追加：三层可审计记忆表（115） =='
\ir sql/115_memory_traces.sql

-- --------------------------------------------------------------------------- #
-- 建库自检：下列查询应全部有结果，任一项为空说明对应分片未生效
-- --------------------------------------------------------------------------- #
\echo '== 自检 1/4：表数量（应 >= 60） =='
SELECT COUNT(*) AS table_count
  FROM information_schema.tables
 WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

\echo '== 自检 2/4：枚举类型数量（应为 28） =='
SELECT COUNT(*) AS enum_count
  FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
 WHERE n.nspname = 'public' AND t.typtype = 'e';

\echo '== 自检 3/4：无注释的列（应为空） =='
SELECT c.relname AS table_name, a.attname AS column_name
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid
 WHERE n.nspname = 'public' AND c.relkind = 'r'
   AND a.attnum > 0 AND NOT a.attisdropped
   AND col_description(c.oid, a.attnum) IS NULL
 LIMIT 20;

\echo '== 自检 4/4：pgvector 可用性 =='
SELECT pgvector_available() AS pgvector_enabled;
