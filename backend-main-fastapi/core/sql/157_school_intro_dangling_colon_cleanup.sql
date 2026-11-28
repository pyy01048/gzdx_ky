-- 157_school_intro_dangling_colon_cleanup.sql
-- 院校库简介清洗续（2026-11-24）：清理 4 条以悬空栏目标签（带冒号、无链接）结尾的简介。
-- 这些标签后的 URL 在抓取时丢失，仅保留标签会形成「……详见：」这类残句。
-- 处理方式：按精确后缀删除该标签句，保留其前正文；每条均有后缀守卫，重复执行不会二次生效。
--   #97  北京建筑大学        尾句「地理位置图详见：」
--   #104 中国铁道科学研究院  尾句「中国铁道科学研究院研究生部官方网站：」（前面邮箱正文完整保留）
--   #283 上海海关学院        尾句「关于学院更多的信息：请访问我院官方网站：」（两个连续标签一并删除）
--   #331 南京体育学院        尾句「报考详情请查阅：」

UPDATE kaoyan_schools
SET intro = btrim(regexp_replace(intro, E'[[:space:]]*地理位置图详见：[[:space:]]*$', ''), E' \t\n\r'),
    updated_at = now()
WHERE id = 97
  AND intro ~ E'地理位置图详见：[[:space:]]*$';

UPDATE kaoyan_schools
SET intro = btrim(regexp_replace(intro, E'[[:space:]]*中国铁道科学研究院研究生部官方网站：[[:space:]]*$', ''), E' \t\n\r'),
    updated_at = now()
WHERE id = 104
  AND intro ~ E'中国铁道科学研究院研究生部官方网站：[[:space:]]*$';

UPDATE kaoyan_schools
SET intro = btrim(regexp_replace(intro, E'[[:space:]]*关于学院更多的信息：请访问我院官方网站：[[:space:]]*$', ''), E' \t\n\r'),
    updated_at = now()
WHERE id = 283
  AND intro ~ E'关于学院更多的信息：请访问我院官方网站：[[:space:]]*$';

UPDATE kaoyan_schools
SET intro = btrim(regexp_replace(intro, E'[[:space:]]*报考详情请查阅：[[:space:]]*$', ''), E' \t\n\r'),
    updated_at = now()
WHERE id = 331
  AND intro ~ E'报考详情请查阅：[[:space:]]*$';
