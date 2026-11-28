-- 147_school_city_from_intro_verified.sql
-- 城市补全（2026-11-24）：对缺 city 的院校，从库内既有简介原文中核对「省份一致 +
-- 原文明确的办学所在地」，并仅采用库内已存在的城市值（白名单）。
-- 逐条注释保留原文定位句，可人工复核。守卫：仅当 city 仍为空时更新，幂等。
-- 另有候选 #669 中国民用航空飞行学院（本部广汉、天府校区成都，跨市多校区），
-- 城市归属不唯一，本批不写。

-- [#258] 黑龙江东方学院 ← 学院坐落在北国“冰城”哈尔滨市
UPDATE kaoyan_schools SET city = $q$哈尔滨$q$, updated_at = now() WHERE id = 258 AND (city IS NULL OR trim(city) = '');

-- [#328] 淮阴师范学院 ← 坐落于……江苏省淮安市
UPDATE kaoyan_schools SET city = $q$淮安$q$, updated_at = now() WHERE id = 328 AND (city IS NULL OR trim(city) = '');

-- [#467] 山东航空学院 ← 坐落在……黄河三角洲中心城市——滨州市
UPDATE kaoyan_schools SET city = $q$滨州$q$, updated_at = now() WHERE id = 467 AND (city IS NULL OR trim(city) = '');

-- [#585] 湖南理工大学 ← 坐落于……岳阳市
UPDATE kaoyan_schools SET city = $q$岳阳$q$, updated_at = now() WHERE id = 585 AND (city IS NULL OR trim(city) = '');

-- [#707] 贵州师范学院 ← 位于贵州省贵阳市乌当区
UPDATE kaoyan_schools SET city = $q$贵阳$q$, updated_at = now() WHERE id = 707 AND (city IS NULL OR trim(city) = '');

-- [#719] 云南财经大学 ← 学校在云南省昆明市办学
UPDATE kaoyan_schools SET city = $q$昆明$q$, updated_at = now() WHERE id = 719 AND (city IS NULL OR trim(city) = '');

-- [#727] 西藏农牧大学 ← 坐落在……西藏林芝市
UPDATE kaoyan_schools SET city = $q$林芝$q$, updated_at = now() WHERE id = 727 AND (city IS NULL OR trim(city) = '');
