-- 202_school_missing_city_backfill.sql
-- 院校城市补全（2026-11-26）：仅为线上仍为空且有可靠依据的 4 条记录补值。
-- 守卫同时限定 id、name 和空城市；重跑不会覆盖已修正或后续人工维护的数据。
-- 依据：中国美术学院/浙江传媒学院位于杭州，安徽科技工程大学位于凤阳，西藏民族大学位于咸阳。

UPDATE kaoyan_schools AS s
SET city = v.city,
    updated_at = now()
FROM (VALUES
    (375, '中国美术学院', '杭州'),
    (380, '浙江传媒学院', '杭州'),
    (411, '安徽科技工程大学', '凤阳'),
    (729, '西藏民族大学', '咸阳')
) AS v(id, name, city)
WHERE s.id = v.id
  AND s.name = v.name
  AND coalesce(btrim(s.city), '') = '';
