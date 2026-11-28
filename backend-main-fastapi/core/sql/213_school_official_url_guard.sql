-- 213：清除已审计的无效院校官网，并阻止占位符/研招网页面再次写入。
-- 本脚本含数据清理，必须显式手工执行，不进入空库自动迁移链。

UPDATE kaoyan_schools
SET official_url = NULL,
    updated_at = now()
WHERE deleted_at IS NULL
  AND (
    official_url LIKE '%***%'
    OR btrim(official_url) ~* '^https?://yz\.chsi\.com\.cn(?::[0-9]+)?(?:[/?#]|$)'
  );

-- 两条历史审计已确认的错校/风险域名仅按 ID + 原值精确清空，不猜替代地址。
UPDATE kaoyan_schools
SET official_url = NULL,
    updated_at = now()
WHERE deleted_at IS NULL
  AND (
    (id = 705 AND official_url = 'https://www.gznc.edu.cn/')
    OR (id = 897 AND official_url = 'https://www.hljut.edu.cn/')
  );

ALTER TABLE kaoyan_schools DROP CONSTRAINT IF EXISTS ck_kaoyan_schools_official_url;
ALTER TABLE kaoyan_schools ADD CONSTRAINT ck_kaoyan_schools_official_url
CHECK (
    official_url IS NULL
    OR btrim(official_url) = ''
    OR (
        official_url NOT LIKE '%***%'
        AND btrim(official_url) !~* '^https?://yz\.chsi\.com\.cn(?::[0-9]+)?(?:[/?#]|$)'
    )
);
