-- 142_school_intro_wrong_school_cleanup.sql
-- 清理串校数据：#147 北华航天工业学院 的简介实为安徽工程大学（含「简称安工程（AHPU），
-- 位于安徽省芜湖市」与库内 #397 安徽工程大学完全一致），继续展示会误导考生。
-- 处理：清空该条错误简介（保留其他字段），前端回落到「暂无简介」。
-- 守卫：仅当简介仍为那条错误文本特征时才清空（幂等，不覆盖后续人工/抓取补全）。
UPDATE kaoyan_schools
SET intro = NULL, updated_at = now()
WHERE id = 147
  AND intro LIKE '%简称安工程%'
  AND intro LIKE '%芜湖市%';
