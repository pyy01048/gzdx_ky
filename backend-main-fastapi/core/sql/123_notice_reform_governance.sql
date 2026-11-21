-- C 批次2：公告/改考治理列（评估报告 #12/#14/P3：缺日期打标/去重/标题清洗/白名单队列/置信度分级）
-- 幂等：IF NOT EXISTS；kaoyan_reforms 可能尚未建表（ensure_reforms_schema 懒建）→ DO 块守卫。
ALTER TABLE kaoyan_notices ADD COLUMN IF NOT EXISTS date_source TEXT;
ALTER TABLE kaoyan_notices ADD COLUMN IF NOT EXISTS title_raw TEXT;
ALTER TABLE kaoyan_notices ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'ok';
ALTER TABLE kaoyan_notices ADD COLUMN IF NOT EXISTS review_source TEXT NOT NULL DEFAULT 'auto';
CREATE INDEX IF NOT EXISTS idx_notices_review ON kaoyan_notices (review_status);

DO $$
BEGIN
    IF to_regclass('kaoyan_reforms') IS NOT NULL THEN
        ALTER TABLE kaoyan_reforms ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'ok';
        ALTER TABLE kaoyan_reforms ADD COLUMN IF NOT EXISTS review_source TEXT NOT NULL DEFAULT 'auto';
        ALTER TABLE kaoyan_reforms ADD COLUMN IF NOT EXISTS confidence_basis TEXT;
        CREATE INDEX IF NOT EXISTS idx_reforms_review ON kaoyan_reforms (review_status);
    END IF;
END $$;
