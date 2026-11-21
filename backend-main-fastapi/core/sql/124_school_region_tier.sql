-- C 批次3：院校地区口径拆分 + 层级嵌套标签（评估报告 #20/#21）
-- exam_region=考研分区（A区/B区，教育部国家线口径）；geo_region=地理七大区；
-- is_double_first_class=双一流嵌套标签（与 985/211 层级正交，不再互斥并列）。
ALTER TABLE kaoyan_schools ADD COLUMN IF NOT EXISTS exam_region TEXT;
ALTER TABLE kaoyan_schools ADD COLUMN IF NOT EXISTS geo_region TEXT;
ALTER TABLE kaoyan_schools ADD COLUMN IF NOT EXISTS is_double_first_class BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_schools_exam_region ON kaoyan_schools (exam_region);
CREATE INDEX IF NOT EXISTS idx_schools_geo_region ON kaoyan_schools (geo_region);
CREATE INDEX IF NOT EXISTS idx_schools_dfc ON kaoyan_schools (is_double_first_class);
