-- 198_school_url_clear_gscae.sql
-- 口径修正（2026-11-24）：#765/#686 简介取自中国航空研究院研究生院官网，但该站并非两所单位独立官网，
-- 为避免「官网」入口误导，清空 197 批写入的该地址；简介保留。
--
-- 安全边界：仅当 official_url 仍等于该地址时清空；不物理删除记录。

UPDATE kaoyan_schools
SET official_url = '',
    updated_at = now()
WHERE id IN (765, 686)
  AND official_url = 'https://www.gscae.cn';
