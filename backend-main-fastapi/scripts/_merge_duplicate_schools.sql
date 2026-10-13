-- 6 组重复院校合并 SQL（草案，需审核后手动执行）
-- 生成时间: 2026-10-12 13:18:51
-- 前置：必须先用 sqlite3 backup() API 备份，WAL 模式不能用 cp


-- ========== 合并 中国石油大学（北京）(id=519) → 中国石油大学(北京)(id=16) ==========
BEGIN;

-- 步骤 1  可选：把空壳侧更完整的信息回填到实体侧（字段级并集，只补空）
UPDATE kaoyan_schools
   SET intro         = CASE WHEN introIS NULL OR TRIM(intro) = ''         THEN (SELECT intro FROM kaoyan_schools WHERE id = 519)         ELSE intro END,
       logo_url      = CASE WHEN logo_url IS NULL OR TRIM(logo_url) = ''  THEN (SELECT logo_url FROM kaoyan_schools WHERE id = 519)      ELSE logo_url END,
       official_url  = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = 519)  ELSE official_url END,
       tags          = CASE WHEN tags IS NULL OR TRIM(tags) = ''          THEN (SELECT tags FROM kaoyan_schools WHERE id = 519)          ELSE tags END
 WHERE id = 16;

-- 步骤 2  重挂引用（实测本例 0 行，仍保留以防数据变化）
UPDATE kaoyan_colleges   SET school_id = 16 WHERE school_id = 519;
UPDATE kaoyan_majors     SET school_id = 16 WHERE school_id = 519;
UPDATE kaoyan_admissions SET school_id = 16 WHERE school_id = 519;

-- 步骤 3  别名保全：把指向空壳的别名改挂到实体；并确保空壳写法本身已登记为别名
UPDATE school_aliases SET school_id = 16 WHERE school_id = 519;
INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '中国石油大学（北京）', 16, '中国石油大学(北京)', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '中国石油大学（北京）');

-- 步骤 4  删除空壳行
DELETE FROM kaoyan_schools WHERE id = 519;
COMMIT;

-- ========== 合并 中国石油大学（华东）(id=587) → 中国石油大学(华东)(id=76) ==========
BEGIN;

-- 步骤 1  可选：把空壳侧更完整的信息回填到实体侧（字段级并集，只补空）
UPDATE kaoyan_schools
   SET intro         = CASE WHEN introIS NULL OR TRIM(intro) = ''         THEN (SELECT intro FROM kaoyan_schools WHERE id = 587)         ELSE intro END,
       logo_url      = CASE WHEN logo_url IS NULL OR TRIM(logo_url) = ''  THEN (SELECT logo_url FROM kaoyan_schools WHERE id = 587)      ELSE logo_url END,
       official_url  = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = 587)  ELSE official_url END,
       tags          = CASE WHEN tags IS NULL OR TRIM(tags) = ''          THEN (SELECT tags FROM kaoyan_schools WHERE id = 587)          ELSE tags END
 WHERE id = 76;

-- 步骤 2  重挂引用（实测本例 0 行，仍保留以防数据变化）
UPDATE kaoyan_colleges   SET school_id = 76 WHERE school_id = 587;
UPDATE kaoyan_majors     SET school_id = 76 WHERE school_id = 587;
UPDATE kaoyan_admissions SET school_id = 76 WHERE school_id = 587;

-- 步骤 3  别名保全：把指向空壳的别名改挂到实体；并确保空壳写法本身已登记为别名
UPDATE school_aliases SET school_id = 76 WHERE school_id = 587;
INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '中国石油大学（华东）', 76, '中国石油大学(华东)', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '中国石油大学（华东）');

-- 步骤 4  删除空壳行
DELETE FROM kaoyan_schools WHERE id = 587;
COMMIT;

-- ========== 合并 华北电力大学（保定）(id=532) → 华北电力大学(保定)(id=155) ==========
BEGIN;

-- 步骤 1  可选：把空壳侧更完整的信息回填到实体侧（字段级并集，只补空）
UPDATE kaoyan_schools
   SET intro         = CASE WHEN introIS NULL OR TRIM(intro) = ''         THEN (SELECT intro FROM kaoyan_schools WHERE id = 532)         ELSE intro END,
       logo_url      = CASE WHEN logo_url IS NULL OR TRIM(logo_url) = ''  THEN (SELECT logo_url FROM kaoyan_schools WHERE id = 532)      ELSE logo_url END,
       official_url  = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = 532)  ELSE official_url END,
       tags          = CASE WHEN tags IS NULL OR TRIM(tags) = ''          THEN (SELECT tags FROM kaoyan_schools WHERE id = 532)          ELSE tags END
 WHERE id = 155;

-- 步骤 2  重挂引用（实测本例 0 行，仍保留以防数据变化）
UPDATE kaoyan_colleges   SET school_id = 155 WHERE school_id = 532;
UPDATE kaoyan_majors     SET school_id = 155 WHERE school_id = 532;
UPDATE kaoyan_admissions SET school_id = 155 WHERE school_id = 532;

-- 步骤 3  别名保全：把指向空壳的别名改挂到实体；并确保空壳写法本身已登记为别名
UPDATE school_aliases SET school_id = 155 WHERE school_id = 532;
INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '华北电力大学（保定）', 155, '华北电力大学(保定)', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '华北电力大学（保定）');

-- 步骤 4  删除空壳行
DELETE FROM kaoyan_schools WHERE id = 532;
COMMIT;

-- ========== 合并 中国地质大学（武汉）(id=598) → 中国地质大学(武汉)(id=190) ==========
BEGIN;

-- 步骤 1  可选：把空壳侧更完整的信息回填到实体侧（字段级并集，只补空）
UPDATE kaoyan_schools
   SET intro         = CASE WHEN introIS NULL OR TRIM(intro) = ''         THEN (SELECT intro FROM kaoyan_schools WHERE id = 598)         ELSE intro END,
       logo_url      = CASE WHEN logo_url IS NULL OR TRIM(logo_url) = ''  THEN (SELECT logo_url FROM kaoyan_schools WHERE id = 598)      ELSE logo_url END,
       official_url  = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = 598)  ELSE official_url END,
       tags          = CASE WHEN tags IS NULL OR TRIM(tags) = ''          THEN (SELECT tags FROM kaoyan_schools WHERE id = 598)          ELSE tags END
 WHERE id = 190;

-- 步骤 2  重挂引用（实测本例 0 行，仍保留以防数据变化）
UPDATE kaoyan_colleges   SET school_id = 190 WHERE school_id = 598;
UPDATE kaoyan_majors     SET school_id = 190 WHERE school_id = 598;
UPDATE kaoyan_admissions SET school_id = 190 WHERE school_id = 598;

-- 步骤 3  别名保全：把指向空壳的别名改挂到实体；并确保空壳写法本身已登记为别名
UPDATE school_aliases SET school_id = 190 WHERE school_id = 598;
INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '中国地质大学（武汉）', 190, '中国地质大学(武汉)', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '中国地质大学（武汉）');

-- 步骤 4  删除空壳行
DELETE FROM kaoyan_schools WHERE id = 598;
COMMIT;

-- ========== 合并 中国地质大学（北京）(id=520) → 中国地质大学(北京)(id=217) ==========
BEGIN;

-- 步骤 1  可选：把空壳侧更完整的信息回填到实体侧（字段级并集，只补空）
UPDATE kaoyan_schools
   SET intro         = CASE WHEN introIS NULL OR TRIM(intro) = ''         THEN (SELECT intro FROM kaoyan_schools WHERE id = 520)         ELSE intro END,
       logo_url      = CASE WHEN logo_url IS NULL OR TRIM(logo_url) = ''  THEN (SELECT logo_url FROM kaoyan_schools WHERE id = 520)      ELSE logo_url END,
       official_url  = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = 520)  ELSE official_url END,
       tags          = CASE WHEN tags IS NULL OR TRIM(tags) = ''          THEN (SELECT tags FROM kaoyan_schools WHERE id = 520)          ELSE tags END
 WHERE id = 217;

-- 步骤 2  重挂引用（实测本例 0 行，仍保留以防数据变化）
UPDATE kaoyan_colleges   SET school_id = 217 WHERE school_id = 520;
UPDATE kaoyan_majors     SET school_id = 217 WHERE school_id = 520;
UPDATE kaoyan_admissions SET school_id = 217 WHERE school_id = 520;

-- 步骤 3  别名保全：把指向空壳的别名改挂到实体；并确保空壳写法本身已登记为别名
UPDATE school_aliases SET school_id = 217 WHERE school_id = 520;
INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '中国地质大学（北京）', 217, '中国地质大学(北京)', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '中国地质大学（北京）');

-- 步骤 4  删除空壳行
DELETE FROM kaoyan_schools WHERE id = 520;
COMMIT;

-- ========== 合并 中国矿业大学（北京）(id=518) → 中国矿业大学(北京)(id=668) ==========
BEGIN;

-- 步骤 1  可选：把空壳侧更完整的信息回填到实体侧（字段级并集，只补空）
UPDATE kaoyan_schools
   SET intro         = CASE WHEN introIS NULL OR TRIM(intro) = ''         THEN (SELECT intro FROM kaoyan_schools WHERE id = 518)         ELSE intro END,
       logo_url      = CASE WHEN logo_url IS NULL OR TRIM(logo_url) = ''  THEN (SELECT logo_url FROM kaoyan_schools WHERE id = 518)      ELSE logo_url END,
       official_url  = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = 518)  ELSE official_url END,
       tags          = CASE WHEN tags IS NULL OR TRIM(tags) = ''          THEN (SELECT tags FROM kaoyan_schools WHERE id = 518)          ELSE tags END
 WHERE id = 668;

-- 步骤 2  重挂引用（实测本例 0 行，仍保留以防数据变化）
UPDATE kaoyan_colleges   SET school_id = 668 WHERE school_id = 518;
UPDATE kaoyan_majors     SET school_id = 668 WHERE school_id = 518;
UPDATE kaoyan_admissions SET school_id = 668 WHERE school_id = 518;

-- 步骤 3  别名保全：把指向空壳的别名改挂到实体；并确保空壳写法本身已登记为别名
UPDATE school_aliases SET school_id = 668 WHERE school_id = 518;
INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '中国矿业大学（北京）', 668, '中国矿业大学(北京)', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '中国矿业大学（北京）');

-- 步骤 4  删除空壳行
DELETE FROM kaoyan_schools WHERE id = 518;
COMMIT;
