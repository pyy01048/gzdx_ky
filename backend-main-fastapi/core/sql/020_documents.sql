-- =============================================================================
-- 020 文档与知识分块域
-- 依赖：000 / 010
--
-- 关键设计：
--   1. 解决问题 3「文档 11 种格式混存」：source_format 列记录原始格式，
--      canonical_content 列统一存放解析后的 Markdown 中间态，下游只认这一列。
--   2. 解决问题 D2「4 张 FTS 影子表」：删除 knowledge_chunks_fts* 共 6 张表，
--      改为 knowledge_chunks 上的 search_tokens + 自动生成的 search_vector(GIN)。
--   3. 解决问题 D3「向量缺失」：chunk_vectors 与 knowledge_chunks 一对一，
--      同时提供 pgvector 列与 bytea 退化列，由 VECTOR_BACKEND 决定走哪条。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 文档主表
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS documents (
    id                    BIGSERIAL     PRIMARY KEY,
    -- 文件标识
    file_name             VARCHAR(500)  NOT NULL,
    file_path             VARCHAR(1000),
    size                  BIGINT,
    content_hash          VARCHAR(64),
    -- 格式归一（解决问题 3）
    source_format         doc_format    NOT NULL DEFAULT 'other',
    canonical_content     TEXT,
    canonical_engine      VARCHAR(50),
    canonical_version     INTEGER       NOT NULL DEFAULT 1,
    -- 兼容列：历史代码读写 content，由触发器与 canonical_content 双向同步
    content               TEXT,
    -- 归属（权威外键 + 兼容文本）
    subject_id            BIGINT        REFERENCES subjects(id) ON DELETE SET NULL,
    subject               VARCHAR(50),
    chapter_id            BIGINT        REFERENCES subject_chapters(id) ON DELETE SET NULL,
    chapter               VARCHAR(200),
    -- 三个正交维度，互不复用
    doc_type              doc_type,
    content_category      content_category,
    exam_stage            exam_stage,
    structure_level       structure_level,
    -- 解析状态
    index_status          index_status  NOT NULL DEFAULT 'pending',
    parse_progress        REAL          NOT NULL DEFAULT 0,
    parse_error           TEXT,
    knowledge_point_count INTEGER       NOT NULL DEFAULT 0,
    chunk_count           INTEGER       NOT NULL DEFAULT 0,
    ocr_used              BOOLEAN       NOT NULL DEFAULT FALSE,
    -- 溯源
    source_kind           source_kind   NOT NULL DEFAULT 'external_import',
    subject_source        VARCHAR(50),
    ima_media_id          VARCHAR(200),
    folder_path           VARCHAR(500),
    content_type          VARCHAR(20),
    created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT ck_documents_progress CHECK (parse_progress >= 0 AND parse_progress <= 1),
    CONSTRAINT ck_documents_canonical CHECK (char_length(btrim(canonical_content)) > 0)
);

COMMENT ON TABLE  documents IS '文档主表：承载原始资料与其统一的 Markdown 中间态';
COMMENT ON COLUMN documents.id IS '主键，BIGSERIAL';
COMMENT ON COLUMN documents.file_name IS '原始文件名';
COMMENT ON COLUMN documents.file_path IS '服务器存储路径';
COMMENT ON COLUMN documents.size IS '文件字节数';
COMMENT ON COLUMN documents.content_hash IS '文件内容 SHA-256 前 64 位，用于跨来源去重';
COMMENT ON COLUMN documents.source_format IS '原始文件格式（pdf/txt/doc/docx/md/image...），11 种混存的记录口径';
COMMENT ON COLUMN documents.canonical_content IS '统一 Markdown 中间态：所有格式解析后归一写入，下游检索与切片只认这一列';
COMMENT ON COLUMN documents.canonical_engine IS '产出中间态的解析器名（如 pypdf / pdfplumber / rapidocr），便于重解析';
COMMENT ON COLUMN documents.canonical_version IS '中间态格式版本号，解析器升级后可据此批量重解析';
COMMENT ON COLUMN documents.content IS '兼容列（历史代码读写），由触发器与 canonical_content 双向同步，Phase 2 后移除';
COMMENT ON COLUMN documents.subject_id IS '权威科目外键，取代旧的 subject 文本';
COMMENT ON COLUMN documents.subject IS '兼容列：科目中文名，由 ETL 从 subjects.name 回填';
COMMENT ON COLUMN documents.chapter_id IS '权威章节外键';
COMMENT ON COLUMN documents.chapter IS '兼容列：章节名';
COMMENT ON COLUMN documents.doc_type IS '资料加工层级：raw 原始教材真题 / note 加工笔记错题 / index 索引考点清单';
COMMENT ON COLUMN documents.content_category IS '内容语义分类，与 doc_type 正交：textbook 教材 / example 例题 / exam 真题 / method 方法';
COMMENT ON COLUMN documents.exam_stage IS '考试阶段：初试 / 复试（原 stage 列，与 prep_stage 语义不同故改名）';
COMMENT ON COLUMN documents.structure_level IS '结构化程度：structured 已按章节解析 / flat 扁平文本 / ocr 扫描件';
COMMENT ON COLUMN documents.index_status IS '索引状态机：pending → indexing → indexed / failed / skipped';
COMMENT ON COLUMN documents.parse_progress IS '解析进度 0-1';
COMMENT ON COLUMN documents.parse_error IS '解析失败原因，index_status=failed 时必填';
COMMENT ON COLUMN documents.knowledge_point_count IS '已从该文档抽取的知识点数量';
COMMENT ON COLUMN documents.chunk_count IS '该文档已产生的知识分块数量';
COMMENT ON COLUMN documents.ocr_used IS '是否经 OCR 识别（扫描版资料）';
COMMENT ON COLUMN documents.source_kind IS '来源性质（正交列），取代旧的 source 字符串前缀归类';
COMMENT ON COLUMN documents.subject_source IS '资料导入来源：ima 表示 IMA 知识库导入，空表示本地上传';
COMMENT ON COLUMN documents.ima_media_id IS 'IMA 侧条目 ID，正文按需拉取，不落库';
COMMENT ON COLUMN documents.folder_path IS 'IMA 内文件夹路径，保留原始组织结构';
COMMENT ON COLUMN documents.content_type IS '内容性质：知识 / 试题 / 单词';
COMMENT ON COLUMN documents.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN documents.updated_at IS '最后更新时间，由 set_updated_at 触发器维护';

CREATE INDEX IF NOT EXISTS idx_documents_subject   ON documents (subject_id);
CREATE INDEX IF NOT EXISTS idx_documents_status    ON documents (index_status);
CREATE INDEX IF NOT EXISTS idx_documents_doctype   ON documents (doc_type, content_category);
CREATE INDEX IF NOT EXISTS idx_documents_hash      ON documents (content_hash) WHERE content_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_ima       ON documents (ima_media_id) WHERE ima_media_id IS NOT NULL;
-- 文档名模糊匹配（pg_trgm，PG 自带）
CREATE INDEX IF NOT EXISTS idx_documents_name_trgm ON documents USING GIN (file_name gin_trgm_ops);

-- canonical_content 与 content 双向同步（兼容期：任一列更新都同步到另一列）
CREATE OR REPLACE FUNCTION sync_document_content() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.canonical_content IS NULL AND NEW.content IS NOT NULL THEN
            NEW.canonical_content := NEW.content;
        ELSIF NEW.content IS NULL AND NEW.canonical_content IS NOT NULL THEN
            NEW.content := NEW.canonical_content;
        END IF;
    ELSIF NEW.canonical_content IS DISTINCT FROM OLD.canonical_content THEN
        NEW.content := NEW.canonical_content;
    ELSIF NEW.content IS DISTINCT FROM OLD.content THEN
        NEW.canonical_content := NEW.content;
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE TRIGGER trg_documents_sync_content BEFORE INSERT OR UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION sync_document_content();

CREATE OR REPLACE TRIGGER trg_documents_updated BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 知识分块：RAG 检索的基本单元（取代 knowledge_chunks_fts* 6 张影子表）
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id                  BIGSERIAL    PRIMARY KEY,
    document_id         BIGINT       REFERENCES documents(id) ON DELETE CASCADE,
    doc_name            VARCHAR(500),
    chunk_index         INTEGER      NOT NULL DEFAULT 0,
    -- 正文与检索
    text                TEXT,
    -- Python 侧 jieba 分词结果（空格分隔），写入即自动生成 search_vector
    search_tokens       TEXT,
    search_vector       tsvector     GENERATED ALWAYS AS (fts_build(search_tokens)) STORED,
    summary             TEXT,
    -- 归属
    subject_id          BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    subject             VARCHAR(50),
    chapter_id          BIGINT       REFERENCES subject_chapters(id) ON DELETE SET NULL,
    -- 页码溯源
    page_start          INTEGER,
    page_end            INTEGER,
    -- 三层语义标签
    l2_chapter          VARCHAR(200),
    l3_content_type     l3_content_type,
    classify_confidence REAL,
    classify_source     classify_source,
    token_count         INTEGER      NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_chunks_text CHECK (char_length(btrim(text)) > 0),
    CONSTRAINT ck_chunks_confidence CHECK (
        classify_confidence IS NULL OR (classify_confidence >= 0 AND classify_confidence <= 1)),
    CONSTRAINT ck_chunks_page CHECK (
        page_start IS NULL OR page_end IS NULL OR page_start <= page_end)
);

COMMENT ON TABLE  knowledge_chunks IS '知识分块表：RAG 检索基本单元，全文检索由 search_vector(GIN) 承载，不再需要 FTS 影子表';
COMMENT ON COLUMN knowledge_chunks.id IS '主键，BIGSERIAL';
COMMENT ON COLUMN knowledge_chunks.document_id IS '来源文档 ID，文档删除时分块级联删除';
COMMENT ON COLUMN knowledge_chunks.doc_name IS '来源文档名（冗余，避免检索时回表）';
COMMENT ON COLUMN knowledge_chunks.chunk_index IS '分块在本篇文档内的序号，从 0 开始';
COMMENT ON COLUMN knowledge_chunks.text IS '分块正文，禁止空串';
COMMENT ON COLUMN knowledge_chunks.search_tokens IS 'jieba 预分词结果（空格分隔），由 Python 侧写入后自动生成 tsvector';
COMMENT ON COLUMN knowledge_chunks.search_vector IS '全文检索向量，GENERATED 列自动维护，不可手工写入';
COMMENT ON COLUMN knowledge_chunks.summary IS '分块摘要';
COMMENT ON COLUMN knowledge_chunks.subject_id IS '权威科目外键';
COMMENT ON COLUMN knowledge_chunks.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN knowledge_chunks.chapter_id IS '权威章节外键';
COMMENT ON COLUMN knowledge_chunks.page_start IS '起始页码';
COMMENT ON COLUMN knowledge_chunks.page_end IS '结束页码';
COMMENT ON COLUMN knowledge_chunks.l2_chapter IS 'L2 章节/模块，如：连续时间系统的时域分析';
COMMENT ON COLUMN knowledge_chunks.l3_content_type IS 'L3 内容语义类型：定义/定理/例题/习题/证明/公式等';
COMMENT ON COLUMN knowledge_chunks.classify_confidence IS '三路融合分类置信度 0-1';
COMMENT ON COLUMN knowledge_chunks.classify_source IS '分类判定来源留痕：vector/keyword/fusion/llm/fallback';
COMMENT ON COLUMN knowledge_chunks.token_count IS '分块正文的估算 token 数，用于控制召回拼装长度';
COMMENT ON COLUMN knowledge_chunks.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN knowledge_chunks.updated_at IS '最后更新时间';

CREATE INDEX IF NOT EXISTS idx_chunks_document  ON knowledge_chunks (document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunks_subject   ON knowledge_chunks (subject_id);
CREATE INDEX IF NOT EXISTS idx_chunks_l3        ON knowledge_chunks (l3_content_type);
-- 全文检索主索引：取代原 6 张 FTS 影子表
CREATE INDEX IF NOT EXISTS idx_chunks_search    ON knowledge_chunks USING GIN (search_vector);
-- 模糊兜底：错别字 / 部分匹配
CREATE INDEX IF NOT EXISTS idx_chunks_text_trgm ON knowledge_chunks USING GIN (text gin_trgm_ops);

CREATE OR REPLACE TRIGGER trg_chunks_updated BEFORE UPDATE ON knowledge_chunks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 分块向量：pgvector 与 Python 退化方案共用一张表
--   VECTOR_BACKEND=pgvector → 写 embedding_f32，SQL 侧 <=> 检索
--   VECTOR_BACKEND=python   → 写 embedding(bytea)，Python 侧 numpy 余弦检索
-- 两列可同时存在，切换开关不需要改表结构。
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id      BIGINT       PRIMARY KEY REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
    document_id   BIGINT       REFERENCES documents(id) ON DELETE CASCADE,
    subject_id    BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    engine        vector_engine NOT NULL DEFAULT 'unknown',
    dim           INTEGER      NOT NULL,
    -- 退化方案：float32 小端字节数组
    embedding     BYTEA,
    model_version VARCHAR(50)  NOT NULL DEFAULT 'bge-small-zh-v1.5',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_chunk_vectors_dim CHECK (dim > 0 AND dim <= 4096)
    -- 注意：这里刻意不写 "必须有向量" 的 CHECK。
    -- 因为 pgvector 不可用时 embedding_f32 列根本不存在，写在 CREATE TABLE 里会直接报
    -- "column embedding_f32 does not exist"；且存量 61041 分块中有 42619 条无向量，
    -- 强制非空会让迁移直接失败。向量空洞改由视图 v_chunk_vector_coverage 监控。
);

COMMENT ON TABLE  chunk_vectors IS '分块向量表：pgvector 列与 bytea 退化列并存，由 VECTOR_BACKEND 决定检索走哪条';
COMMENT ON COLUMN chunk_vectors.chunk_id IS '关联知识分块 ID，一对一，分块删除时级联删除';
COMMENT ON COLUMN chunk_vectors.document_id IS '冗余文档 ID，便于按文档批量删除向量';
COMMENT ON COLUMN chunk_vectors.subject_id IS '冗余科目 ID，便于按科目做向量过滤';
COMMENT ON COLUMN chunk_vectors.engine IS '生成向量的引擎：bge / openai / unknown';
COMMENT ON COLUMN chunk_vectors.dim IS '向量维度，实测 512';
COMMENT ON COLUMN chunk_vectors.embedding IS '退化方案存储：float32 小端字节数组，供 Python 侧余弦检索';
COMMENT ON COLUMN chunk_vectors.model_version IS '模型版本，模型升级后可据此批量重算';
COMMENT ON COLUMN chunk_vectors.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN chunk_vectors.updated_at IS '最后更新时间';

-- pgvector 可用时补向量列与 HNSW 索引；否则上面的 ck_chunk_vectors_payload 约束
-- 只要求 embedding 非空，退化方案依然完整可用。
DO $$
BEGIN
    IF pgvector_available() THEN
        ALTER TABLE chunk_vectors ADD COLUMN IF NOT EXISTS embedding_f32 vector(512);
        CREATE INDEX IF NOT EXISTS idx_chunk_vectors_hnsw
            ON chunk_vectors USING hnsw (embedding_f32 vector_cosine_ops);
    ELSE
        RAISE NOTICE 'pgvector 不可用：chunk_vectors 仅使用 embedding(bytea) 退化列';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_chunk_vectors_doc     ON chunk_vectors (document_id);
CREATE INDEX IF NOT EXISTS idx_chunk_vectors_subject ON chunk_vectors (subject_id);

CREATE OR REPLACE TRIGGER trg_chunk_vectors_updated BEFORE UPDATE ON chunk_vectors
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
