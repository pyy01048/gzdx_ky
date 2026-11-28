-- 128: 专业库垃圾数据治理（爬虫/OCR 解析错位产生的伪专业名）
-- 评估报告 P3：院校/专业数据质量；幂等：按 name/code 模式匹配，不依赖 id；删除前校验无外键依赖。
-- 覆盖：①纯数字垃圾名（OCR 页码/分数误当专业名）②ISBN 当专业代码 ③QQ 群/辅导班广告文本 ④带前导代码伪影的真实专业名清洗。

-- A. 删除纯数字 + 尾随标点的垃圾名（如 '3523'、'7780'、'1584：'、'1194276.'、school 436 的 OCR 页码簇）
DELETE FROM kaoyan_majors
WHERE name ~ '^[0-9]+[：:．.。，, ]*$'
  AND NOT EXISTS (SELECT 1 FROM kaoyan_scorelines s WHERE s.major_id = kaoyan_majors.id)
  AND NOT EXISTS (SELECT 1 FROM kaoyan_admissions a WHERE a.major_id = kaoyan_majors.id)
  AND NOT EXISTS (SELECT 1 FROM kaoyan_major_kb_link k WHERE k.major_id = kaoyan_majors.id);

-- B. 删除 ISBN 被误作专业代码的解析错位行（code 以 978 开头，如 '0245524，2000 年 1 月。'/978781、'1194276.'/978712）
DELETE FROM kaoyan_majors
WHERE code ~ '^978'
  AND NOT EXISTS (SELECT 1 FROM kaoyan_scorelines s WHERE s.major_id = kaoyan_majors.id)
  AND NOT EXISTS (SELECT 1 FROM kaoyan_admissions a WHERE a.major_id = kaoyan_majors.id)
  AND NOT EXISTS (SELECT 1 FROM kaoyan_major_kb_link k WHERE k.major_id = kaoyan_majors.id);

-- C. 删除广告/QQ 群 spam 伪专业名（含数字且命中 spam 关键词）
DELETE FROM kaoyan_majors
WHERE name ~ '(QQ|扫码|辅导班|交流群)'
  AND name ~ '[0-9]'
  AND NOT EXISTS (SELECT 1 FROM kaoyan_scorelines s WHERE s.major_id = kaoyan_majors.id)
  AND NOT EXISTS (SELECT 1 FROM kaoyan_admissions a WHERE a.major_id = kaoyan_majors.id)
  AND NOT EXISTS (SELECT 1 FROM kaoyan_major_kb_link k WHERE k.major_id = kaoyan_majors.id);

-- D. 清洗带前导代码/数字伪影的真实专业名：提取 '电子信息' 起的正文并折叠多余空白
--    例：'0 电子信息（包括1名士兵计划，5名非全）' / '085400 电子信息  （...联合学院）  （...）' / '085400)(专业学位)电子信息'
UPDATE kaoyan_majors
SET name = trim(regexp_replace(regexp_replace(name, '^.*?(电子信息)', '电子信息'), '\s+', ' ', 'g'))
WHERE name ~ '^[0-9]'
  AND name ~ '电子信息'
  AND name <> regexp_replace(name, '^.*?(电子信息)', '电子信息'); -- 仅在确实变化时更新，保证幂等

-- E. 兜底：清洗 '0' 直接接中文专业名的前导零伪影（如 '0电子信息' 之外的其它专业），不触碰 '3S集成...' 这类合法名
UPDATE kaoyan_majors
SET name = trim(regexp_replace(name, '^0+([一-龥])', '\1'))
WHERE name ~ '^0+[一-龥]';
