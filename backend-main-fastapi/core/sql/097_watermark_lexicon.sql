-- --------------------------------------------------------------------------- #
-- 097 水印自学习词库表（watermark_lexicon）
-- --------------------------------------------------------------------------- #
-- 背景（2026-10-15）
-- ----------------------
-- 智能水印识别采用「结构规律 + 统计证据 + 自学习词库」三层：
-- `services/content_sanitizer.learn_watermark_lexicon()` 从 documents 语料自动
-- 学习跨文档高频短行，自动启用高置信项、其余进候选队列等人工一键审核。
--
-- 该表的 DDL 起初**只写在 Python 里**（content_sanitizer.LEXICON_DDL），
-- 结果只有跑过学习函数的库（生产 kaoyan）才有表，测试库 kaoyan_test 没有 →
-- 相关用例报 `relation "watermark_lexicon" does not exist`
-- （实测 12 例）。违反项目铁律「建表与迁移必须走 apply_schema」。
-- 本分片把它收进 schema 主入口，两边库同时具备。
--
-- 幂等：CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，可反复重跑。
-- 顺序：无外键依赖，排在序列末尾（紧随 096）。
-- --------------------------------------------------------------------------- #

CREATE TABLE IF NOT EXISTS watermark_lexicon (
    phrase       TEXT PRIMARY KEY,
    doc_count    INTEGER NOT NULL DEFAULT 0,
    hit_count    INTEGER NOT NULL DEFAULT 0,
    confidence   REAL NOT NULL DEFAULT 0.5,
    enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    auto_learned BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE watermark_lexicon IS
    '水印自学习词库：自动学习+人工审核，enabled 的词条参与全站内容清洗';

-- 候选队列列表（只有 enabled=FALSE 的行）走这个索引
CREATE INDEX IF NOT EXISTS idx_watermark_lexicon_enabled
    ON watermark_lexicon (enabled);

-- 按命中热度排序（人工审核优先看高频项）
CREATE INDEX IF NOT EXISTS idx_watermark_lexicon_doc_count
    ON watermark_lexicon (doc_count DESC);
