-- 156_school_intro_title_prefix_cleanup.sql
-- 院校库简介清洗续（2026-11-24）：清理两类可证实的标题噪声。
-- 1) 14 条简介以「校名+简介」作为标题开头，且其后正文重复校名
--    （如「黑龙江东方学院简介黑龙江东方学院1992年建校…」）→ 去掉重复标题前缀。
-- 2) #403 滁州学院简介结尾粘着孤立栏目名「周边环境」（正文以「。」紧邻标签）
--    → 去掉尾部标签；#545「周边环境十分安逸」为正常行文，不动。
-- 守卫：仅命中仍有对应前缀/尾部标签的记录，重复执行不会二次生效。

-- 1) 去掉行首「校名+简介」标题前缀（名字长度 + 2 个汉字“简介”）
UPDATE kaoyan_schools
SET intro = btrim(substring(btrim(intro) from char_length(btrim(name)) + 3), E' \t\n\r'),
    updated_at = now()
WHERE btrim(coalesce(intro, '')) <> ''
  AND intro LIKE btrim(name) || '简介%';

-- 2) #403 去掉尾部孤立栏目名
UPDATE kaoyan_schools
SET intro = btrim(regexp_replace(intro, E'[ \\t\\n\\r]*周边环境[ \\t\\n\\r]*$', '', 'g'), E' \t\n\r'),
    updated_at = now()
WHERE id = 403
  AND intro ~ '周边环境[[:space:]]*$';
