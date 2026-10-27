-- --------------------------------------------------------------------------- #
-- 095 quiz_questions 导入分类闸门列（classify_confidence / classify_source / needs_review）
-- --------------------------------------------------------------------------- #
-- 背景（2026-10-14）
-- ----------------------
-- ``models.QuizQuestion`` 声明了三个「导入自动分类可信闸门」列，但本分片此前
-- **没有对应迁移**：ORM 的 ``Base.metadata.create_all()`` 只对**新建**表生效，
-- 存量库（生产 kaoyan 与测试 kaoyan_test）均无这三列 →
--
--   UndefinedColumn: column quiz_questions.classify_confidence does not exist
--
-- 而 ``services.quiz_classifier_v2.ensure_quiz_classify_columns`` 只在
-- ``POST /api/quiz/import-questions`` 路径里调用（见 routers/quiz.py），
-- 于是**任何其它读 quiz_questions 的路径都会 500**（列表 / 统计 / PUT 等）。
-- 迁移必须进 schema 主入口，不能依赖「导入时顺手自愈」。
--
-- 类型选择（与 ORM / 分类器实现逐条对齐，勿随意改）
-- --------------------------------------------------
--   classify_confidence FLOAT      ← models.QuizQuestion.classify_confidence
--   classify_source     VARCHAR(30) ← models.QuizQuestion.classify_source
--   needs_review        BOOLEAN    ← models.QuizQuestion.needs_review
--
-- ⚠️ classify_source 刻意**不用**已有的 classify_source ENUM 类型
--    （000_extensions_and_enums.sql:136 / pg_types.ENUM_CATALOG）：
--    那个 ENUM 的标签是 ('vector','keyword','fusion','llm','no_bge','fallback')，
--    是 knowledge_chunks 的取值域；而 quiz_classifier_v2 会写入该域之外的
--    'disagree'（两路判定冲突）与 'none'（未判定）
--    （见 quiz_classifier_v2.py:64/283/292/293/454/460/461），
--    建成 ENUM 会立刻报 invalid input value for enum classify_source: "disagree"。
--    models.py 与作者的 ensure_ DDL（quiz_classifier_v2.py:526）也都是 VARCHAR(30)，
--    本文件与之保持一致。
--
-- 幂等：全部 ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，可反复重跑。
-- 顺序：依赖 040_questions.sql（quiz_questions）与 000_extensions_and_enums.sql，
--      故排在分片序列末尾。
-- --------------------------------------------------------------------------- #

-- 1. 分类整体置信度（0~1，科目×题型置信下限）
ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS classify_confidence FLOAT;

COMMENT ON COLUMN quiz_questions.classify_confidence IS
    '导入自动分类整体置信度 0-1（科目×题型置信下限）';

-- 2. 分类来源留痕：keyword/vector/fusion/llm/disagree/none
ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS classify_source VARCHAR(30);

COMMENT ON COLUMN quiz_questions.classify_source IS
    '分类来源留痕：keyword/vector/fusion/llm/disagree/none（非 classify_source ENUM 取值域）';

-- 3. 低置信待人工复核（进复核队列）
--    DEFAULT FALSE：存量行与未走分类器的行一律视为「无需复核」，不回填污染队列。
ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS needs_review BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN quiz_questions.needs_review IS
    '分类低置信待人工复核（进复核队列）；models 侧声明了 index=True，故下方建索引';

-- 4. 复核队列筛选索引（models.QuizQuestion.needs_review 的 index=True）
CREATE INDEX IF NOT EXISTS idx_quiz_needs_review ON quiz_questions (needs_review);