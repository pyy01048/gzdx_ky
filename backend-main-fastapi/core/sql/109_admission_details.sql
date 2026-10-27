-- =============================================================================
-- 109 admission_details：拟录取/复试名单逐人明细（采集深度·详情页）
-- （pipeline/admission_batch_ocr.py 的落库目标；powered by DeepSeek-OCR）
--
-- 内容：
--   1) kaoyan_admission_details：逐人名单明细（考生编号/姓名/专业/初试/复试/总成绩），
--      与 kaoyan_admissions 聚合行通过 data_source 前缀关联（detail 行 =
--      '<聚合data_source>:d<序号>'），并有 admission_id 外键软关联；断点续跑幂等。
--   2) 索引：school+year、admission_id、data_source 唯一（去重兜底）、姓名检索。
--
-- 幂等，可重复执行。PG 方言（DATABASE_BACKEND=postgresql）。
-- 执行：python scripts/execute_core_sql.py core/sql/109_admission_details.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS kaoyan_admission_details (
    id            BIGSERIAL PRIMARY KEY,
    admission_id  BIGINT REFERENCES kaoyan_admissions(id) ON DELETE SET NULL,
    school_id     BIGINT NOT NULL REFERENCES kaoyan_schools(id),
    year          INTEGER NOT NULL,
    exam_no       VARCHAR(40),
    name          VARCHAR(60) NOT NULL,
    major_name    VARCHAR(120),
    score_initial NUMERIC(6,2),
    score_retest  NUMERIC(6,2),
    score_total   NUMERIC(6,2),
    remark        VARCHAR(200),
    data_source   VARCHAR(80) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_kaoyan_adm_detail_ds  ON kaoyan_admission_details (data_source);
CREATE INDEX        IF NOT EXISTS ix_kaoyan_adm_detail_sy ON kaoyan_admission_details (school_id, year);
CREATE INDEX        IF NOT EXISTS ix_kaoyan_adm_detail_aid ON kaoyan_admission_details (admission_id);
CREATE INDEX        IF NOT EXISTS ix_kaoyan_adm_detail_name ON kaoyan_admission_details (name);