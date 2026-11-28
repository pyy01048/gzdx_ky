-- 194_school_url_clear_897.sql
-- 安全修正（2026-11-24）：#897 黑龙江工业学院登记官网 hljut.edu.cn 当前解析到与学校无关的博彩页面，疑似域名被劫持/停放。
-- 为避免向用户输出风险链接，清空该官网字段（简介已由 193 批补齐，不受影响）。
--
-- 安全边界：仅当 official_url 仍等于该异常地址时清空；不物理删除记录。

UPDATE kaoyan_schools
SET official_url = '',
    updated_at = now()
WHERE id = 897
  AND official_url = 'https://www.hljut.edu.cn/';
