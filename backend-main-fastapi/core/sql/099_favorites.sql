-- --------------------------------------------------------------------------- #
-- 099 收藏表（favorites）—— S7「收藏 / 学习轨迹」数据地基
-- --------------------------------------------------------------------------- #
-- 背景（2026-10-15）
-- ----------------------
-- 全站通用收藏：可收藏文档、题目、错题、知识点、单词、卡片、链接等任意实体。
-- 采用「弱引用」设计：不设外键（item_type + item_id 指向不同表），
-- 被收藏对象删除后收藏行保留（title 快照仍在，前端可标注"已失效"）。
--
-- 幂等：CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，可反复重跑。
-- 顺序：无外键依赖，排在序列末尾（紧随 098）。
-- --------------------------------------------------------------------------- #

CREATE TABLE IF NOT EXISTS favorites (
    id         BIGSERIAL PRIMARY KEY,
    item_type  VARCHAR(32)  NOT NULL,          -- document / question / error / kp / word / flashcard / link
    item_id    INTEGER      NOT NULL,
    title      VARCHAR(500) NOT NULL DEFAULT '', -- 收藏时的标题快照
    snippet    TEXT,                            -- 摘要快照（可选）
    meta       JSONB,                           -- 额外上下文（科目、路由参数等）
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_favorites_item UNIQUE (item_type, item_id)
);

COMMENT ON TABLE favorites IS
    '全站通用收藏：item_type+item_id 弱引用任意实体，title 为快照，对象删除后行保留';

-- 收藏夹列表（按时间倒序翻页）
CREATE INDEX IF NOT EXISTS idx_favorites_created
    ON favorites (created_at DESC);

-- 按类型筛选
CREATE INDEX IF NOT EXISTS idx_favorites_type
    ON favorites (item_type, created_at DESC);
