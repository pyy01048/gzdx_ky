-- 111_ocr_pipeline_tables.sql
-- OCR / 采集管线新表（docx/34-OCR与数据采集开源方案 §6）：
--   document_pages / document_blocks / question_images
--   crawl_jobs / crawl_pages / crawl_dead_letters
--
-- 幂等：全部 CREATE ... IF NOT EXISTS，重复执行不报错、不动已有数据。
-- 与 models.py 的 6 个 ORM 类一一对应（models.py 是 ORM 口径，这里是 DDL 真源）。
-- 独立执行入口：scripts/create_ocr_tables.py（--dry-run / --verify / --apply）。

-- ---------------------------------------------------------------------------
-- 文档页
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_pages (
    id             SERIAL PRIMARY KEY,
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no        INTEGER NOT NULL,
    width          DOUBLE PRECISION,
    height         DOUBLE PRECISION,
    text           TEXT,
    layout_json    JSONB,
    image_path     VARCHAR(1000),
    ocr_engine     VARCHAR(50),
    ocr_confidence DOUBLE PRECISION,
    created_at     TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_document_pages_doc_page
    ON document_pages (document_id, page_no);
CREATE INDEX IF NOT EXISTS ix_document_pages_doc_page
    ON document_pages (document_id, page_no);
CREATE INDEX IF NOT EXISTS ix_document_pages_document_id
    ON document_pages (document_id);
CREATE INDEX IF NOT EXISTS ix_document_pages_id ON document_pages (id);

COMMENT ON TABLE document_pages IS '文档页级数据（docx/34 §6）';
COMMENT ON COLUMN document_pages.page_no IS '物理页码（1 基）';

-- ---------------------------------------------------------------------------
-- 文档块
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_blocks (
    id            SERIAL PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no       INTEGER NOT NULL,
    block_id      VARCHAR(64),
    block_type    VARCHAR(32),
    bbox          JSONB,
    text          TEXT,
    latex         TEXT,
    image_path    VARCHAR(1000),
    reading_order INTEGER,
    confidence    DOUBLE PRECISION,
    created_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_document_blocks_doc_page
    ON document_blocks (document_id, page_no);
CREATE INDEX IF NOT EXISTS ix_document_blocks_document_id
    ON document_blocks (document_id);
CREATE INDEX IF NOT EXISTS ix_document_blocks_block_type
    ON document_blocks (block_type);
CREATE INDEX IF NOT EXISTS ix_document_blocks_id ON document_blocks (id);

-- 块级质检留痕（2026-10-20 数学扫描件实测追加）：
-- 数学 PDF 全是扫描件，RapidOCR 会把公式读坏（x→α、f(x)→fLg(））。
-- 这列把解析层的质检标记落库，好把坏块挑出来重解析：
--   SELECT * FROM document_blocks WHERE extra->>'math_corrupted' = 'true';
ALTER TABLE document_blocks ADD COLUMN IF NOT EXISTS extra JSONB;

COMMENT ON TABLE document_blocks IS '文档版面块级数据（docx/34 §6）';
COMMENT ON COLUMN document_blocks.block_type IS
    'text/title/table/figure/formula/list/header/footer/page_no/unknown';
COMMENT ON COLUMN document_blocks.extra IS '块级附加信息 JSON（math_corrupted / math_suspect / ocr_confidence_missing 等质检标记）';

-- ---------------------------------------------------------------------------
-- 题目配图
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS question_images (
    id           SERIAL PRIMARY KEY,
    question_id  INTEGER REFERENCES quiz_questions(id) ON DELETE CASCADE,
    document_id  INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    page_no      INTEGER,
    image_path   VARCHAR(1000),
    image_hash   VARCHAR(64),
    phash        VARCHAR(32),
    bbox         JSONB,
    image_kind   VARCHAR(32),
    caption      VARCHAR(1000),
    width        INTEGER,
    height       INTEGER,
    is_primary   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_question_images_question_id
    ON question_images (question_id);
CREATE INDEX IF NOT EXISTS ix_question_images_document_id
    ON question_images (document_id);
CREATE INDEX IF NOT EXISTS ix_question_images_image_hash
    ON question_images (image_hash);
CREATE INDEX IF NOT EXISTS ix_question_images_phash ON question_images (phash);
CREATE INDEX IF NOT EXISTS ix_question_images_id ON question_images (id);

COMMENT ON TABLE question_images IS '题目配图明细（docx/34 §6）';
COMMENT ON COLUMN question_images.is_primary IS '是否主图（同一题中面积最大者）';

-- ---------------------------------------------------------------------------
-- 采集任务
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_jobs (
    id          SERIAL PRIMARY KEY,
    source_key  VARCHAR(64) NOT NULL,
    school_id   INTEGER REFERENCES kaoyan_schools(id) ON DELETE SET NULL,
    url         VARCHAR(1024),
    job_type    VARCHAR(32),
    status      VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    next_run_at TIMESTAMP,
    last_error  TEXT,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_crawl_jobs_source_key ON crawl_jobs (source_key);
CREATE INDEX IF NOT EXISTS ix_crawl_jobs_status ON crawl_jobs (status);
CREATE INDEX IF NOT EXISTS ix_crawl_jobs_school_id ON crawl_jobs (school_id);
CREATE INDEX IF NOT EXISTS ix_crawl_jobs_next_run_at ON crawl_jobs (next_run_at);
CREATE INDEX IF NOT EXISTS ix_crawl_jobs_id ON crawl_jobs (id);

COMMENT ON TABLE crawl_jobs IS '采集任务（docx/34 §6）';
COMMENT ON COLUMN crawl_jobs.status IS 'pending/running/done/failed';

-- ---------------------------------------------------------------------------
-- 采集页面
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_pages (
    id            SERIAL PRIMARY KEY,
    job_id        INTEGER REFERENCES crawl_jobs(id) ON DELETE SET NULL,
    url           VARCHAR(1024),
    canonical_url VARCHAR(1024) UNIQUE,
    title         VARCHAR(512),
    publish_date  DATE,
    html_path     VARCHAR(1000),
    text          TEXT,
    content_hash  VARCHAR(64),
    simhash       VARCHAR(32),
    fetched_at    TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_crawl_pages_canonical_url
    ON crawl_pages (canonical_url);
CREATE INDEX IF NOT EXISTS ix_crawl_pages_job_id ON crawl_pages (job_id);
CREATE INDEX IF NOT EXISTS ix_crawl_pages_content_hash ON crawl_pages (content_hash);
CREATE INDEX IF NOT EXISTS ix_crawl_pages_simhash ON crawl_pages (simhash);
CREATE INDEX IF NOT EXISTS ix_crawl_pages_id ON crawl_pages (id);

COMMENT ON TABLE crawl_pages IS '采集到的页面（docx/34 §6）';

-- ---------------------------------------------------------------------------
-- 采集死信
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crawl_dead_letters (
    id         SERIAL PRIMARY KEY,
    job_id     INTEGER REFERENCES crawl_jobs(id) ON DELETE SET NULL,
    url        VARCHAR(1024),
    source_key VARCHAR(64),
    error      TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    payload    JSONB,
    created_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_crawl_dead_letters_job_id
    ON crawl_dead_letters (job_id);
CREATE INDEX IF NOT EXISTS ix_crawl_dead_letters_source_key
    ON crawl_dead_letters (source_key);
CREATE INDEX IF NOT EXISTS ix_crawl_dead_letters_id ON crawl_dead_letters (id);

COMMENT ON TABLE crawl_dead_letters IS '采集死信（docx/34 §6）';
