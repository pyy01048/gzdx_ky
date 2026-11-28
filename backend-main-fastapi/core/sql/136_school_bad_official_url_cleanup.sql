-- 136_school_bad_official_url_cleanup.sql
-- 院校库治理：清除无法核验的 official_url，避免前端渲染死链。
--
-- 依据（云端只读审计 2026-11-24，1150 所在库院校）：
--   1) 8 所科研院所的 official_url 是脱敏占位符（含 "***"），如
--      "http://www.***"、"https://yjs.***/JX_dsgz.aspx?ID=514"。
--      来源 data_source=yz.chsi.com.cn，说明研招网页面本身未给出可读域名，
--      占位符不是真实链接，会 100% 打不开。
--   2) kaoyan_schools.id=705（贵州民族大学）的 official_url 与 707（贵州师范学院）
--      同为 https://www.gznc.edu.cn/。云端实测该域首页 <title> 为「贵州师范学院官网」，
--      证明 705 的映射错误（data_source=yz.chsi.com.cn+domain_map，域名映射表串号）。
--      贵州民族大学的真实域名在云端网络不可达，无法核验，故先置空而不是猜写。
--
-- 处理口径：official_url 置 NULL（前端不渲染跳转），不删除院校行、不改其它字段；
--           幂等：仅处理当前仍为占位符 / 已确认错配的行。
-- 不编造数据：核验不到的正确网址一律留空，等待有来源的补录。

-- 1) 脱敏占位符（含 ***）
UPDATE kaoyan_schools
SET official_url = NULL,
    updated_at = now()
WHERE deleted_at IS NULL
  AND official_url IS NOT NULL
  AND official_url LIKE '%***%';

-- 2) 已确认错配：贵州民族大学（gznc.edu.cn 实测属于贵州师范学院）
UPDATE kaoyan_schools
SET official_url = NULL,
    updated_at = now()
WHERE deleted_at IS NULL
  AND id = 705
  AND official_url = 'https://www.gznc.edu.cn/';
