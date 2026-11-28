-- 211：题目证据链与精确原卷关联。
-- 只扩展 schema；不回填 paper_id，不按标题/年份猜测原卷，不伪造页码或来源。
-- 幂等：可重复执行。依赖 020/040/041/060/090。

ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS origin_document_id BIGINT;
ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS origin_chunk_id BIGINT;
ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS paper_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'quiz_questions_origin_document_id_fkey'
          AND conrelid = 'quiz_questions'::regclass
    ) THEN
        ALTER TABLE quiz_questions
            ADD CONSTRAINT quiz_questions_origin_document_id_fkey
            FOREIGN KEY (origin_document_id) REFERENCES documents(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'quiz_questions_origin_chunk_id_fkey'
          AND conrelid = 'quiz_questions'::regclass
    ) THEN
        ALTER TABLE quiz_questions
            ADD CONSTRAINT quiz_questions_origin_chunk_id_fkey
            FOREIGN KEY (origin_chunk_id) REFERENCES knowledge_chunks(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'quiz_questions_paper_id_fkey'
          AND conrelid = 'quiz_questions'::regclass
    ) THEN
        ALTER TABLE quiz_questions
            ADD CONSTRAINT quiz_questions_paper_id_fkey
            FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_qq_origin_document ON quiz_questions (origin_document_id);
CREATE INDEX IF NOT EXISTS idx_qq_origin_chunk ON quiz_questions (origin_chunk_id);
CREATE INDEX IF NOT EXISTS idx_qq_paper_id ON quiz_questions (paper_id);

COMMENT ON COLUMN quiz_questions.origin_document_id IS '来源文档 ID；未知为 NULL';
COMMENT ON COLUMN quiz_questions.origin_chunk_id IS '来源知识分块 ID；未知为 NULL';
COMMENT ON COLUMN quiz_questions.paper_id IS '精确关联的原卷 ID；NULL 时保留 paper 原字符串并标记未关联';

CREATE TABLE IF NOT EXISTS question_evidence_links (
    id                  BIGSERIAL PRIMARY KEY,
    question_id         BIGINT NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    knowledge_point_id  BIGINT REFERENCES knowledge_points(id) ON DELETE CASCADE,
    knowledge_chunk_id  BIGINT REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
    document_id         BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    textbook_id         BIGINT REFERENCES textbooks(id) ON DELETE CASCADE,
    paper_id            BIGINT REFERENCES papers(id) ON DELETE CASCADE,
    school_id           BIGINT REFERENCES kaoyan_schools(id) ON DELETE CASCADE,
    major_id            BIGINT REFERENCES kaoyan_majors(id) ON DELETE CASCADE,
    subject_id          BIGINT REFERENCES subjects(id) ON DELETE CASCADE,
    page_start          INTEGER,
    page_end            INTEGER,
    source              VARCHAR(100) NOT NULL DEFAULT 'manual',
    confidence          DOUBLE PRECISION,
    verification_status VARCHAR(20) NOT NULL DEFAULT 'unverified',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    verified_by         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    verified_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_qel_target CHECK (
        knowledge_point_id IS NOT NULL OR knowledge_chunk_id IS NOT NULL
        OR document_id IS NOT NULL OR textbook_id IS NOT NULL OR paper_id IS NOT NULL
    ),
    CONSTRAINT ck_qel_pages CHECK (
        (page_start IS NULL OR page_start >= 1)
        AND (page_end IS NULL OR page_end >= 1)
        AND (page_start IS NULL OR page_end IS NULL OR page_end >= page_start)
    ),
    CONSTRAINT ck_qel_confidence CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    CONSTRAINT ck_qel_verification CHECK (verification_status IN ('verified', 'unverified', 'rejected'))
);

COMMENT ON TABLE question_evidence_links IS
'题目证据显式关联；来源、置信度与核验状态独立于答案质量，拒绝的关联不参与证据摘要';
COMMENT ON COLUMN question_evidence_links.knowledge_point_id IS '题目关联考点；可由 question_knowledge_links 派生';
COMMENT ON COLUMN question_evidence_links.knowledge_chunk_id IS '真实知识分块；页码只从该分块读取';
COMMENT ON COLUMN question_evidence_links.textbook_id IS '教材 ID；经 textbook_documents 或本行 document_id 建立实体文件关系';
COMMENT ON COLUMN question_evidence_links.school_id IS '教材适用院校；未确定作用域时为 NULL';
COMMENT ON COLUMN question_evidence_links.major_id IS '教材适用招生专业；与 school_id/subject_id 共同表达专业—科目—教材';
COMMENT ON COLUMN question_evidence_links.subject_id IS '教材适用考试科目；不是招生学科';
COMMENT ON COLUMN question_evidence_links.page_start IS '证据真实起始页码；未知为 NULL，禁止按 chunk 序号推算';
COMMENT ON COLUMN question_evidence_links.page_end IS '证据真实结束页码；未知为 NULL';
COMMENT ON COLUMN question_evidence_links.source IS '证据来源标识，如 manual/official_catalog/import';
COMMENT ON COLUMN question_evidence_links.confidence IS '证据匹配置信度 0..1；不复用答案置信度';
COMMENT ON COLUMN question_evidence_links.verification_status IS 'verified/unverified/rejected；rejected 不参与 API 证据链';
COMMENT ON COLUMN question_evidence_links.metadata IS '原始依据、导入批次与核验说明 JSON';

CREATE INDEX IF NOT EXISTS idx_qel_question_verified
    ON question_evidence_links (question_id, verification_status);
CREATE INDEX IF NOT EXISTS idx_qel_chunk ON question_evidence_links (knowledge_chunk_id);
CREATE INDEX IF NOT EXISTS idx_qel_textbook_scope
    ON question_evidence_links (textbook_id, school_id, major_id, subject_id);
CREATE INDEX IF NOT EXISTS idx_qel_paper ON question_evidence_links (paper_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_qel_explicit_edge ON question_evidence_links (
    question_id,
    COALESCE(knowledge_point_id, 0),
    COALESCE(knowledge_chunk_id, 0),
    COALESCE(document_id, 0),
    COALESCE(textbook_id, 0),
    COALESCE(paper_id, 0),
    COALESCE(school_id, 0),
    COALESCE(major_id, 0),
    COALESCE(subject_id, 0),
    COALESCE(page_start, 0),
    COALESCE(page_end, 0),
    source
);

DROP TRIGGER IF EXISTS trg_qel_updated ON question_evidence_links;
CREATE TRIGGER trg_qel_updated BEFORE UPDATE ON question_evidence_links
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
