-- =============================================================================
-- 090 教材域（textbooks）
-- 依赖：000 / 010（subjects）
--
-- 背景：平台此前**没有任何承载教材元数据的结构**（实测全库无 book/isbn/publisher
-- 相关列），教材只以 documents 表中一个文件的形式存在，无法回答"这门课指定
-- 哪本书、谁编的、哪个版本、用于初试还是复试、哪些学校在用"。
--
-- 设计原则（与 ADR-002 科目单一权威源对齐）：
--   1. 教材是**独立实体**，不是文档。一本教材可以有多个文档版本（讲义/答案/扫描件），
--      故 textbook 与 documents 是 1:N，通过 textbook_documents 关联。
--   2. 教材归属科目一律走 subject_id 外键，禁止在教材表里硬编码中文科目名。
--   3. 初试/复试是**教材属性**（同一本书可能两用），用数组表达，不拆表。
--   4. 适用院校走 school_id 外键关联表，与 kaoyan_schools 打通，
--      这样"考某校某专业要读哪些书"可以直接查出来。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 教材主表
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS textbooks (
    id              BIGSERIAL    PRIMARY KEY,
    -- 书目信息
    title           VARCHAR(300) NOT NULL,
    subtitle        VARCHAR(300),
    edition         VARCHAR(50),
    authors         TEXT         NOT NULL,
    publisher       VARCHAR(200),
    isbn            VARCHAR(20),
    pub_year        INTEGER,
    -- 归属科目（权威外键，可空以容纳跨科目教材）
    subject_id      BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    -- 适用阶段：初试 / 复试 / 初试+复试（数组，同书可两用）
    exam_stages     exam_stage[] NOT NULL DEFAULT '{}',
    -- 定位与说明
    role            VARCHAR(50)  NOT NULL DEFAULT 'main',
    summary         TEXT,
    note            TEXT,
    -- 使用广度（由 textbook_schools 视图实时算，此列冗余但便于排序）
    school_count    INTEGER      NOT NULL DEFAULT 0,
    -- 数据可信度与溯源：教材目录属人工整理，必须标注来源，禁止伪装成官方数据
    source          VARCHAR(100) NOT NULL DEFAULT 'manual_catalog',
    confidence      confidence_level NOT NULL DEFAULT 'medium',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    sort_order      INTEGER      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_textbooks_pub_year CHECK (pub_year IS NULL OR (pub_year BETWEEN 1900 AND 2100)),
    CONSTRAINT uq_textbooks_isbn CHECK (isbn IS NULL OR isbn <> ''),
    CONSTRAINT ck_textbooks_role CHECK (role IN ('main','reference','exercise','supplement'))
);

COMMENT ON TABLE  textbooks IS '教材权威表：电子通信考研核心专业课教材书目，取代此前无结构化承载的状态';
COMMENT ON COLUMN textbooks.title IS '教材书名（不含版次）';
COMMENT ON COLUMN textbooks.subtitle IS '副标题，如「理论、方法和应用」';
COMMENT ON COLUMN textbooks.edition IS '版次，如「第3版」「第5/6版」；多版通用时保留原始写法';
COMMENT ON COLUMN textbooks.authors IS '作者，多作者用「、」分隔；译者用括注';
COMMENT ON COLUMN textbooks.publisher IS '出版社';
COMMENT ON COLUMN textbooks.isbn IS 'ISBN（13位，去连字符）；未知时为 NULL，禁止编造';
COMMENT ON COLUMN textbooks.pub_year IS '出版年份，未知时为 NULL';
COMMENT ON COLUMN textbooks.subject_id IS '所属备考科目外键，禁止硬编码中文科目名';
COMMENT ON COLUMN textbooks.exam_stages IS '适用阶段数组：初试 / 复试；同一教材可两用';
COMMENT ON COLUMN textbooks.role IS '教材定位：main 主教材 / reference 参考书 / exercise 习题册 / supplement 补充';
COMMENT ON COLUMN textbooks.summary IS '教材内容概要';
COMMENT ON COLUMN textbooks.note IS '使用说明，如「贵大834核心教材」';
COMMENT ON COLUMN textbooks.school_count IS '使用该教材的院校数（冗余列，由视图刷新）';
COMMENT ON COLUMN textbooks.source IS '数据来源标识：manual_catalog 人工整理目录 / official 官方指定';
COMMENT ON COLUMN textbooks.confidence IS '数据可信度：官方指定为 high，常见考情归纳为 medium';
COMMENT ON COLUMN textbooks.is_active IS '是否启用';
COMMENT ON COLUMN textbooks.sort_order IS '展示排序权重，升序';

CREATE INDEX IF NOT EXISTS idx_textbooks_subject ON textbooks (subject_id, role);
CREATE INDEX IF NOT EXISTS idx_textbooks_title_trgm ON textbooks USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_textbooks_stages ON textbooks USING GIN (exam_stages);

CREATE OR REPLACE TRIGGER trg_textbooks_updated BEFORE UPDATE ON textbooks
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 教材 ↔ 院校：哪些学校的哪些专业在用这本书
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS textbook_schools (
    id           BIGSERIAL    PRIMARY KEY,
    textbook_id  BIGINT       NOT NULL REFERENCES textbooks(id)      ON DELETE CASCADE,
    school_id    BIGINT       NOT NULL REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    -- 该校用法说明（如「东南大学专用」「复试指定」）
    usage_note   VARCHAR(200),
    exam_stage   exam_stage,
    is_official  BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_textbook_school UNIQUE (textbook_id, school_id, exam_stage)
);

COMMENT ON TABLE  textbook_schools IS '教材与院校的关联表：回答「哪些学校在用这本教材」';
COMMENT ON COLUMN textbook_schools.textbook_id IS '教材 ID';
COMMENT ON COLUMN textbook_schools.school_id IS '院校 ID，与 kaoyan_schools 打通';
COMMENT ON COLUMN textbook_schools.usage_note IS '该校具体用法，保留原始目录中的表述';
COMMENT ON COLUMN textbook_schools.exam_stage IS '该校使用阶段';
COMMENT ON COLUMN textbook_schools.is_official IS '是否官方指定（相对「常见考情归纳」）';

CREATE INDEX IF NOT EXISTS idx_textbook_schools_school ON textbook_schools (school_id);
CREATE INDEX IF NOT EXISTS idx_textbook_schools_book ON textbook_schools (textbook_id);

-- --------------------------------------------------------------------------- #
-- 教材 ↔ 文档：教材的实体文件（讲义/答案/扫描件）
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS textbook_documents (
    id           BIGSERIAL    PRIMARY KEY,
    textbook_id  BIGINT       NOT NULL REFERENCES textbooks(id)  ON DELETE CASCADE,
    document_id  BIGINT       NOT NULL REFERENCES documents(id)  ON DELETE CASCADE,
    -- 该文档相对教材的角色
    doc_role     VARCHAR(30)  NOT NULL DEFAULT 'body',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_textbook_document UNIQUE (textbook_id, document_id),
    CONSTRAINT ck_textbook_document_role CHECK (doc_role IN ('body','exercise','answer','slides','scan'))
);

COMMENT ON TABLE  textbook_documents IS '教材与知识库文档的关联：定位某本教材的实体文件';
COMMENT ON COLUMN textbook_documents.textbook_id IS '教材 ID';
COMMENT ON COLUMN textbook_documents.document_id IS '文档 ID';
COMMENT ON COLUMN textbook_documents.doc_role IS '文档角色：body 正文 / exercise 习题 / answer 答案 / slides 讲义 / scan 扫描件';

CREATE INDEX IF NOT EXISTS idx_textbook_docs_book ON textbook_documents (textbook_id);
CREATE INDEX IF NOT EXISTS idx_textbook_docs_doc ON textbook_documents (document_id);
