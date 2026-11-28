-- 207：工科08学习空间——招生专业的初试考试科目关联。
-- 依赖：010（subjects 考试科目）、060（kaoyan_majors 招生专业）。
-- 只新增公共目录链路；quiz_questions 不直接关联院校，也不改动题目 owner_user_id。
-- 幂等：可重复执行；未匹配/歧义由回填脚本输出报告，不猜写 subject_id。

CREATE TABLE IF NOT EXISTS kaoyan_major_subject_links (
    id                  BIGSERIAL PRIMARY KEY,
    major_id            BIGINT NOT NULL REFERENCES kaoyan_majors(id) ON DELETE CASCADE,
    subject_id          BIGINT REFERENCES subjects(id) ON DELETE CASCADE,
    exam_subject_code   VARCHAR(32),
    exam_subject_name   VARCHAR(200),
    source              JSONB NOT NULL DEFAULT '{}'::jsonb,
    match_status        VARCHAR(20) NOT NULL DEFAULT 'matched',
    confidence          DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_kmmsl_match_status CHECK (match_status IN ('matched', 'ambiguous', 'unmatched')),
    CONSTRAINT ck_kmmsl_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT ck_kmmsl_exam_subject CHECK (
        exam_subject_code IS NOT NULL OR exam_subject_name IS NOT NULL OR subject_id IS NOT NULL
    )
);

COMMENT ON TABLE kaoyan_major_subject_links IS
'招生专业初试考试科目公共目录；科目是 subjects，不是 disciplines 招生学科';
COMMENT ON COLUMN kaoyan_major_subject_links.id IS '关联行 ID';
COMMENT ON COLUMN kaoyan_major_subject_links.major_id IS '招生专业 ID；链路 kaoyan_majors.school_id 指向院校';
COMMENT ON COLUMN kaoyan_major_subject_links.subject_id IS '考试科目 ID；仅确定匹配时回填，NULL 不参与题库查询';
COMMENT ON COLUMN kaoyan_major_subject_links.exam_subject_code IS '原招生目录考试代码（如 101/204/302 或院校自命题代码）';
COMMENT ON COLUMN kaoyan_major_subject_links.exam_subject_name IS '原招生目录考试科目名称';
COMMENT ON COLUMN kaoyan_major_subject_links.source IS '来源 JSON：保留原条目、解析方式与匹配依据';
COMMENT ON COLUMN kaoyan_major_subject_links.match_status IS '匹配状态 matched/ambiguous/unmatched；歧义与未命中不得自动模糊写入';
COMMENT ON COLUMN kaoyan_major_subject_links.confidence IS '匹配置信度 0..1；代码精确匹配为 1';
COMMENT ON COLUMN kaoyan_major_subject_links.created_at IS '创建时间 UTC';
COMMENT ON COLUMN kaoyan_major_subject_links.updated_at IS '更新时间 UTC';

CREATE INDEX IF NOT EXISTS idx_kmmsl_major_subject
    ON kaoyan_major_subject_links (major_id, subject_id);
CREATE INDEX IF NOT EXISTS idx_kmmsl_subject_status
    ON kaoyan_major_subject_links (subject_id, match_status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kmmsl_major_exam_subject
    ON kaoyan_major_subject_links (
        major_id,
        subject_id,
        COALESCE(exam_subject_code, ''),
        COALESCE(exam_subject_name, '')
    )
    WHERE subject_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_kmmsl_updated ON kaoyan_major_subject_links;
CREATE TRIGGER trg_kmmsl_updated BEFORE UPDATE ON kaoyan_major_subject_links
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
