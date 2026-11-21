-- =============================================================================
-- 120 院校品牌化：封面图列
-- 依赖：060
--
-- 校徽 logo_url 早已存在；本迁移只补 cover_url（校门/校园实景封面，
-- 自托管 /media/images/school_covers/{id}.jpg）。幂等：IF NOT EXISTS。
-- =============================================================================

ALTER TABLE kaoyan_schools ADD COLUMN IF NOT EXISTS cover_url VARCHAR(500);

COMMENT ON COLUMN kaoyan_schools.cover_url IS '院校封面图地址（校门/校园实景，自托管 /media/images 路径）';
