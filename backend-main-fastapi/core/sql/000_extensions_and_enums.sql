-- =============================================================================
-- 000 扩展 / 枚举类型 / 通用函数
-- 依赖顺序：本文件必须第一个执行，后续分片全部依赖这里的类型与函数。
-- 目标：把散落在 18 处代码、44 张表里的裸 String(20/50) 枚举收敛为 PG 原生 ENUM。
-- =============================================================================

-- pg_trgm：三元组模糊匹配，PG 自带 contrib，无需额外 DLL。
-- 用途：中文分词漏召回时兜底（错别字/部分匹配），与 tsvector 互补。
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- pgvector：Windows 便携版可能没有 vector 扩展文件，因此容错创建。
-- 创建失败不代表迁移失败，向量检索自动切换到 Python 侧退化方案。
DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS vector;
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'pgvector 不可用（%）。VECTOR_BACKEND 请设为 python。', SQLERRM;
    END;
END $$;

-- 供 SQL 分片与运行时共同判断：当前库到底能不能用 pgvector。
CREATE OR REPLACE FUNCTION pgvector_available() RETURNS boolean
LANGUAGE sql STABLE PARALLEL SAFE AS $$
    SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector');
$$;

-- updated_at 自动维护触发器函数（各分片按需挂载）。
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;

-- --------------------------------------------------------------------------- #
-- 中文全文检索：PG 无内置中文分词器，Windows 便携版装 zhparser/pg_jieba 困难。
-- 方案：Python 侧用 jieba 预分词，把空格分隔的 token 串写入 search_tokens 列；
--       本函数把 token 串转成 tsvector，由 GENERATED 列自动维护，配 GIN 索引。
-- 注意：必须两参数版 to_tsvector(regconfig, text)，它是 IMMUTABLE，
--       才能用在 GENERATED ALWAYS AS (...) STORED 里（单参数版是 STABLE，不合法）。
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION fts_build(tokens text) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT to_tsvector('simple'::regconfig, coalesce(tokens, ''));
$$;

-- 查询侧：token 串（空格分隔）转 tsquery，AND 语义。
-- Python 侧先 jieba 分词再传入，保证写入与查询用同一套分词。
CREATE OR REPLACE FUNCTION fts_query(tokens text) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN coalesce(btrim(tokens), '') = ''
                THEN ''::tsquery
                ELSE plainto_tsquery('simple'::regconfig, tokens) END;
$$;

-- 查询侧：OR 语义（召回优先，用于 RAG 粗排）。
CREATE OR REPLACE FUNCTION fts_query_any(tokens text) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN coalesce(btrim(tokens), '') = ''
                THEN ''::tsquery
                ELSE to_tsquery('simple'::regconfig,
                                btrim(regexp_replace(tokens, '\s+', ' | ', 'g'), ' |'))
           END;
$$;

-- --------------------------------------------------------------------------- #
-- 枚举类型（ADD 新枚举时必须同步 python 侧 core/pg_types.py 的 ENUM_CATALOG）
-- --------------------------------------------------------------------------- #

-- 备考科目分类：公共课 / 专业课 / 复试科目
DO $$ BEGIN CREATE TYPE subject_category AS ENUM ('public','professional','retest');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 题型（实测取值：essay/single/calc/fill/judge/draw，旧文档里的 multiple 已无数据但保留兼容）
DO $$ BEGIN CREATE TYPE question_type AS ENUM (
    'single','multiple','judge','fill','calc','essay','draw','proof','other');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 作答类型：objective 可自动判分 / subjective 需人工或 LLM 评分
DO $$ BEGIN CREATE TYPE answer_type AS ENUM ('objective','subjective');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 来源性质：正交独立列，取代旧的 "知识库:" / "真题:" 字符串前缀归类
DO $$ BEGIN CREATE TYPE source_kind AS ENUM (
    'past_exam','textbook','chapter_exercise','mock_exam','ai_generated',
    'user_created','external_import');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 备考阶段（tasks.stage / phase_plans）
DO $$ BEGIN CREATE TYPE prep_stage AS ENUM ('basic','intensive','sprint','retest');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 考试阶段（documents.stage，实测取值 初试/复试，与 prep_stage 语义不同，故拆成两个枚举）
DO $$ BEGIN CREATE TYPE exam_stage AS ENUM ('初试','复试');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 内容语义分类（与 doc_type 的加工层级正交）
DO $$ BEGIN CREATE TYPE content_category AS ENUM (
    'textbook','example','exam','method','glossary','other');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 资料加工层级：原始教材真题 / 加工笔记错题 / 索引考点清单
DO $$ BEGIN CREATE TYPE doc_type AS ENUM ('raw','note','index');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 原始文件格式（实测 11 种混存；归一后统一写入 canonical_content 的 Markdown 中间态）
DO $$ BEGIN CREATE TYPE doc_format AS ENUM (
    'pdf','txt','doc','docx','md','image','pptx','ppt','xlsx','html','json',
    'jpg','png','other');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 结构化程度：已按章节解析 / 扁平文本 / 扫描件 OCR
DO $$ BEGIN CREATE TYPE structure_level AS ENUM ('structured','flat','ocr');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 索引状态
DO $$ BEGIN CREATE TYPE index_status AS ENUM (
    'pending','indexing','indexed','failed','skipped');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 质量评级（实测含 incomplete，表示题干/选项不完整）
DO $$ BEGIN CREATE TYPE quality_grade AS ENUM ('A','B','C','incomplete');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 置信度
DO $$ BEGIN CREATE TYPE confidence_level AS ENUM ('high','medium','low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 答案来源：题库自带 / 原文抽取 / LLM 生成 / 人工确认
DO $$ BEGIN CREATE TYPE answer_source AS ENUM (
    'bank','source_extract','llm_generated','user_confirmed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 分块分类判定来源
DO $$ BEGIN CREATE TYPE classify_source AS ENUM (
    'vector','keyword','fusion','llm','no_bge','fallback');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- 'manual'：人工修正标签写入通道（documents.py POST /chunks/{id}/label），
-- 缺失会让人工修正 500（InvalidTextRepresentation）。幂等补值。
ALTER TYPE classify_source ADD VALUE IF NOT EXISTS 'manual' AFTER 'fallback';
-- 'document'：文档级分类结果**传播到分块**时的来源标记
-- （classify_document → 逐 chunk 写入 subject/l3_content_type）。
-- 缺失会让文档级分类落库 500：invalid input value for enum classify_source: "document"
ALTER TYPE classify_source ADD VALUE IF NOT EXISTS 'document' AFTER 'manual';

-- 知识点抽取来源
DO $$ BEGIN CREATE TYPE extract_source AS ENUM ('smart_ingest','batch','manual');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 知识点关系类型：前置 / 并列 / 包含
DO $$ BEGIN CREATE TYPE relation_type AS ENUM ('prerequisite','parallel','contains');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 任务状态
DO $$ BEGIN CREATE TYPE task_status AS ENUM ('pending','doing','done','cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 复习反馈结果（SM-2 评分档位）
DO $$ BEGIN CREATE TYPE review_result AS ENUM ('again','hard','good','easy');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 掌握度等级
DO $$ BEGIN CREATE TYPE mastery_level AS ENUM (
    'not_mastered','learning','reviewing','mastered');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 研招通知类型
DO $$ BEGIN CREATE TYPE notice_type AS ENUM ('公告','简章','复试','调剂','录取');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 通知重要级
DO $$ BEGIN CREATE TYPE importance_level AS ENUM ('urgent','important','normal','low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 提醒类型
DO $$ BEGIN CREATE TYPE alert_kind AS ENUM (
    'deadline_soon','new_urgent','new_important','subscribed_new');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 订阅维度
DO $$ BEGIN CREATE TYPE subscription_scope AS ENUM (
    'school','major','notice_type','keyword');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 学位类型
DO $$ BEGIN CREATE TYPE degree_type AS ENUM ('academic','professional','unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 向量引擎（实测项目用 bge，维度 512）
DO $$ BEGIN CREATE TYPE vector_engine AS ENUM ('bge','openai','unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 分块 L3 语义类型
DO $$ BEGIN CREATE TYPE l3_content_type AS ENUM (
    '定义','定理','理论陈述','例题','习题','证明','公式','实验步骤','其他');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 题目校验门结果：未校验 / 通过 / 有告警 / 不通过
DO $$ BEGIN CREATE TYPE question_validation_status AS ENUM ('pending','pass','warn','fail');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
