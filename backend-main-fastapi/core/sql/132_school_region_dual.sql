-- 132_school_region_dual.sql
-- 院校地区双口径补全：exam_region（考研 A/B 区）+ geo_region（七大地理区）。
-- 背景：kaoyan_schools.region 一列混装两种口径（818 行 A/B 区、332 行地理大区），
--       前端按「华东」筛选时只能命中 region 恰为「华东」的少数行，漏掉同区 A 区院校。
-- 本次按省份（公开行政区划与研招分区政策）分别写入两列，口径互不污染；region 保留不动。
-- 幂等：仅填空值。

UPDATE kaoyan_schools
SET exam_region = CASE
    WHEN province IN ('内蒙古','广西','海南','贵州','云南','西藏','甘肃','青海','宁夏','新疆') THEN 'B区'
    WHEN province IN ('北京','天津','河北','山西','辽宁','吉林','黑龙江','上海','江苏','浙江',
                      '安徽','福建','江西','山东','河南','湖北','湖南','广东','重庆','四川','陕西') THEN 'A区'
    ELSE exam_region
END
WHERE exam_region IS NULL OR trim(exam_region) = '';

UPDATE kaoyan_schools
SET geo_region = CASE
    WHEN province IN ('北京','天津','河北','山西','内蒙古') THEN '华北'
    WHEN province IN ('辽宁','吉林','黑龙江') THEN '东北'
    WHEN province IN ('上海','江苏','浙江','安徽','福建','江西','山东') THEN '华东'
    WHEN province IN ('河南','湖北','湖南') THEN '华中'
    WHEN province IN ('广东','广西','海南') THEN '华南'
    WHEN province IN ('重庆','四川','贵州','云南','西藏') THEN '西南'
    WHEN province IN ('陕西','甘肃','青海','宁夏','新疆') THEN '西北'
    ELSE geo_region
END
WHERE geo_region IS NULL OR trim(geo_region) = '';
