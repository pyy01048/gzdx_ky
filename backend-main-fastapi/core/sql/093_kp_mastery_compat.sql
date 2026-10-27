-- =============================================================================
-- 093 knowledge_points 兼容列的**触发器与存量回填**
-- 依赖：030（knowledge_points）、094a（兼容列已建）、080（v_knowledge_mastery 视图）
--
-- 问题（实测）
-- -----------
-- 030 按"解决问题 5"的设计，**刻意删掉了 knowledge_points.mastery 硬编码列**，
-- 掌握度改为由 v_knowledge_mastery 实时聚合（30 天指数衰减加权正确率）。
-- 但存量业务代码有大量 `kp.mastery` 读访问（routers/taxonomy.py 至少 6 处），
-- 切到 PG 后直接抛：column knowledge_points.mastery does not exist。
--
-- 为什么不改业务代码
-- ----------------
-- mastery 的**权威来源**确实是派生视图（复习/作答记录驱动），这是正确设计。
-- 但在业务路由完成"改读派生值"迁移之前，直接砍属性会让整页 500。
-- 折中：**保留一列只读兼容值**，由触发器从派生视图同步，业务读到的仍是
-- 真实派生结果（而非假数据）；写入被触发器忽略（掌握度只能由复习行为驱动）。
--
-- 与 080 的关系
-- -------------
-- 本文件不权威源，仅作缓存镜像；权威源始终是 v_knowledge_mastery。
-- 前端若需最新值应优先查视图（services.kp_mastery 已提供该口径）。
--
-- 顺序约束（2026-10-14 修正）
-- --------------------------
-- 本文件**必须排在 080 / 081 之后**：触发器函数体与回填语句都要读
-- v_knowledge_mastery。而"加列"部分已拆到 094a，**必须排在 080 / 081 之前**
-- （081 的 knowledge_points_legacy 用 SELECT kp.*，加列会让视图列数偏移）。
-- 详见 094a 顶部说明。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 1. 触发器：任何写入 mastery 的操作都被改写成派生值
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION sync_kp_mastery()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_real INTEGER;
BEGIN
    SELECT COALESCE(mastery, 0) INTO v_real
      FROM v_knowledge_mastery WHERE knowledge_point_id = NEW.id;
    -- 一律以派生值为准：业务代码写的 0 不会覆盖真实掌握度
    NEW.mastery := COALESCE(v_real, 0);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_kp_mastery_sync ON knowledge_points;
CREATE OR REPLACE TRIGGER trg_kp_mastery_sync
    BEFORE INSERT OR UPDATE ON knowledge_points
    FOR EACH ROW EXECUTE FUNCTION sync_kp_mastery();

-- --------------------------------------------------------------------------- #
-- 2. 存量回填：把派生值写进兼容列，使首次读取即准确
-- --------------------------------------------------------------------------- #
UPDATE knowledge_points kp
   SET mastery = COALESCE(
        (SELECT m.mastery FROM v_knowledge_mastery m
          WHERE m.knowledge_point_id = kp.id), 0);

UPDATE knowledge_points kp
   SET next_review = (SELECT rs.next_review_at FROM review_schedules rs
                       WHERE rs.item_type = 'knowledge_point'
                         AND rs.item_id = kp.id
                       LIMIT 1);