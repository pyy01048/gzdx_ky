-- 155_school_intro_label_noise_cleanup.sql
-- 院校库简介清洗（2026-11-24）：只删除可证实的栏目标签/截断残符，不改写正文。
-- 审计结论（1150 所，简介缺失 219）：
--   A. 88 条简介夹带官网栏目名「周边环境」：62 条独占末行（正文后多一行标签），
--      24 条为「\n周边环境\n」小节标题（其后仍是有效的校区/地理位置正文），
--      1 条为行首标签（#97「周边环境北京建筑大学西城校区…」）。
--      统一删除行首的「周边环境」标签，保留其后的全部正文。
--   B. #630 广西师范大学简介以「（更新时间：2026年3月）」开头 → 去除该时间标签。
--   C. #716 云南师范大学简介正文后拼接了导航残块
--      （「学校网址：/招生处网址：/具体网页：云师大—招生—研究生招生/…」且链接为空）
--      → 从「学校网址：」起截断，保留前面的完整简介。
--   D. #424/#662 简介以悬空的「（」结尾（原文在括号处被截断）→ 去掉空括号。
--   E. #262 简介结尾为零宽连接符（不可见控制字符）→ 去除。
-- 守卫：仅处理仍含对应噪声的记录，重复执行不会二次生效；不回填、不删除院校行。

-- C. 先截断 #716 的导航残块（放在标签清洗之前，避免残留「校园地图：/校园风采：」）
UPDATE kaoyan_schools
SET intro = btrim(regexp_replace(intro, E'\\n学校网址：.*$', '', 's'), E' \t\n\r'),
    updated_at = now()
WHERE id = 716
  AND intro LIKE '%学校网址：%';

-- A. 删除行首（含独占行）的「周边环境」栏目标签，保留后续正文
UPDATE kaoyan_schools
SET intro = btrim(regexp_replace(intro, E'(^|\\n)[ \\t]*周边环境[:：]?[ \\t]*', E'\\1', 'g'), E' \t\n\r'),
    updated_at = now()
WHERE intro ~ E'(^|\n)[ \t]*周边环境[:：]?[ \t]*';

-- B. 去除 #630 的行首更新时间标签
UPDATE kaoyan_schools
SET intro = regexp_replace(btrim(intro), '^（更新时间[^）]*）[[:space:]]*', ''),
    updated_at = now()
WHERE id = 630
  AND intro ~ '^（更新时间';

-- D. 去掉 #424/#662 结尾的悬空左括号
UPDATE kaoyan_schools
SET intro = regexp_replace(btrim(intro), '（[[:space:]]*$', ''),
    updated_at = now()
WHERE id IN (424, 662)
  AND intro ~ '（[[:space:]]*$';

-- E. 去除 #262 结尾的零宽连接符
UPDATE kaoyan_schools
SET intro = btrim(intro, E' \t\n\r' || chr(8205)),
    updated_at = now()
WHERE id = 262
  AND right(btrim(intro), 1) = chr(8205);
