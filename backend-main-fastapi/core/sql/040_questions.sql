-- =============================================================================
-- 040 题库域
-- 依赖：000 / 010 / 020 / 030
--
-- 关键设计（解决问题 2「题目无标准 schema」与问题 4「教材题 vs 真题混用」）：
--   1. options 从"无约束 JSON"升级为受 is_canonical_options() 校验的强类型数组：
--      元素必须是 {"key":"A","text":"..."} 对象，长度 2-10，杜绝 2/3/5/6/14 错乱。
--   2. 来源从"字符串前缀"升级为两个正交列：
--        source_kind —— 来源性质（真题/教材/章节习题/模拟/AI/自建/外部导入）
--        source_label —— 原始来源标签，纯展示，不再承载归类语义
--      另外用 GENERATED 列 is_past_exam 提供零成本筛选与索引。
--   3. 真题强制有年份：CHECK (source_kind <> 'past_exam' OR year IS NOT NULL)。
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- 选项结构校验门：options 必须是规范数组
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION is_canonical_options(payload jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT payload IS NULL
        OR (jsonb_typeof(payload) = 'array'
            AND jsonb_array_length(payload) BETWEEN 2 AND 10
            AND (SELECT bool_and(jsonb_typeof(e) = 'object'
                                 AND e ? 'key'
                                 AND e ? 'text')
                 FROM jsonb_array_elements(payload) AS e));
$$;

COMMENT ON FUNCTION is_canonical_options(jsonb) IS
    '题目选项结构门：NULL 或 2-10 个 {key,text} 对象的数组，阻断选项数错乱与结构不一致';

-- --------------------------------------------------------------------------- #
-- 题型与选项数一致性（软检查，返回问题码列表供校验门记录）
--   填空/计算/简答/作图 不应带选项；单选/多选必须有选项；判断题至多 2 项
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION check_options_consistency(payload jsonb, qtype question_type)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN qtype IN ('single','multiple') AND payload IS NULL
            THEN 'objective_missing_options'
        WHEN qtype = 'judge' AND payload IS NOT NULL AND jsonb_array_length(payload) <> 2
            THEN 'judge_options_not_two'
        WHEN qtype IN ('single','multiple') AND jsonb_array_length(payload) < 2
            THEN 'objective_options_too_few'
        WHEN qtype IN ('fill','calc','essay','draw','proof') AND payload IS NOT NULL
            THEN 'subjective_has_options'
        WHEN qtype = 'single' AND jsonb_array_length(payload) < 4
            THEN 'single_options_less_than_four'
        ELSE NULL
    END;
$$;

COMMENT ON FUNCTION check_options_consistency(jsonb, question_type) IS
    '题型与选项一致性检查：返回问题码或 NULL（通过）';

-- --------------------------------------------------------------------------- #
-- 题干洁净度（软检查）：题干里混入选项行或过短则报问题码
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION check_stem_clean(stem text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN coalesce(btrim(stem), '') = ''            THEN 'empty_stem'
        WHEN char_length(btrim(stem)) < 4              THEN 'stem_too_short'
        WHEN btrim(stem) ~ '(^|\n)\s*[A-F]\s*[．.、]'   THEN 'stem_contains_option'
        ELSE NULL
    END;
$$;

COMMENT ON FUNCTION check_stem_clean(text) IS
    '题干洁净度检查：返回问题码或 NULL（通过）';

-- --------------------------------------------------------------------------- #
-- 题目主表
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS quiz_questions (
    id                  BIGSERIAL    PRIMARY KEY,

    -- —— 题干与选项 —— #
    content             TEXT         NOT NULL,
    -- 规范格式：[{"key":"A","text":"选项内容"}, ...]，长度 2-10
    options             JSONB,
    images              JSONB DEFAULT '[]'::jsonb,
    option_count        SMALLINT     GENERATED ALWAYS AS (
                            CASE WHEN options IS NULL THEN 0
                                 ELSE jsonb_array_length(options) END) STORED,
    answer              TEXT,
    analysis            TEXT,
    rubric              TEXT,
    max_score           REAL,

    -- —— 题型与作答 —— #
    question_type       question_type NOT NULL DEFAULT 'single',
    answer_type         answer_type   NOT NULL DEFAULT 'objective',
    difficulty          SMALLINT     NOT NULL DEFAULT 3,

    -- —— 来源（正交双列，取代 "知识库:" / "真题:" 前缀）—— #
    source_kind         source_kind  NOT NULL DEFAULT 'external_import',
    is_past_exam        BOOLEAN      GENERATED ALWAYS AS (source_kind = 'past_exam') STORED,
    source_label        TEXT,
    origin_document_id  BIGINT       REFERENCES documents(id) ON DELETE SET NULL,
    origin_chunk_id     BIGINT       REFERENCES knowledge_chunks(id) ON DELETE SET NULL,

    -- —— 真题属性 —— #
    year                INTEGER,
    paper               VARCHAR(100),
    source_paper        VARCHAR(200),
    source_page         INTEGER,
    question_no         INTEGER,
    external_id         VARCHAR(100),

    -- —— 归属 —— #
    subject_id          BIGINT       REFERENCES subjects(id) ON DELETE SET NULL,
    subject             VARCHAR(50),
    chapter_id          BIGINT       REFERENCES subject_chapters(id) ON DELETE SET NULL,
    chapter             VARCHAR(200),
    knowledge_point     VARCHAR(200),

    -- —— 质量与治理 —— #
    confidence          confidence_level NOT NULL DEFAULT 'medium',
    quality             quality_grade,
    ai_generated        BOOLEAN      NOT NULL DEFAULT FALSE,
    verified            BOOLEAN      NOT NULL DEFAULT FALSE,
    variant_group       VARCHAR(50),
    answer_source       answer_source,
    answer_confidence   REAL,
    is_available        BOOLEAN      NOT NULL DEFAULT TRUE,
    is_junk             BOOLEAN      NOT NULL DEFAULT FALSE,
    is_retest           BOOLEAN      NOT NULL DEFAULT FALSE,
    figure_missing      SMALLINT     NOT NULL DEFAULT 0,
    -- 校验门结果：由 080 的 trg_quiz_questions_gate 触发器写入
    validation_status   question_validation_status NOT NULL DEFAULT 'pending',
    validation_errors   JSONB        NOT NULL DEFAULT '[]'::jsonb,
    validated_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

    -- 分层治理：结构性问题用 CHECK 硬拒（不可协商），内容质量问题交给
    -- 080 的校验门触发器标记 warn。这样存量脏数据能先导入、再统计、再批量修，
    -- 而不是在迁移第一步就把 ETL 卡死。
    CONSTRAINT uq_quiz_questions_external UNIQUE (external_id),
    CONSTRAINT ck_quiz_questions_options CHECK (is_canonical_options(options)),
    CONSTRAINT ck_quiz_questions_difficulty CHECK (difficulty BETWEEN 1 AND 5),
    CONSTRAINT ck_quiz_questions_year CHECK (year IS NULL OR (year BETWEEN 1980 AND 2100)),
    CONSTRAINT ck_quiz_questions_answer_conf CHECK (
        answer_confidence IS NULL OR (answer_confidence >= 0 AND answer_confidence <= 1)),
    -- 真题必须有年份，避免"真题被标成知识库"后年份丢失
    CONSTRAINT ck_quiz_questions_past_exam_year CHECK (source_kind <> 'past_exam' OR year IS NOT NULL)
);

COMMENT ON TABLE  quiz_questions IS '题库主表：题干/选项/答案强类型化，来源用正交列表达，入库过校验门';
COMMENT ON COLUMN quiz_questions.id IS '主键，BIGSERIAL';
COMMENT ON COLUMN quiz_questions.content IS '题干正文，不含选项；洁净度由 check_stem_clean 软检查';
COMMENT ON COLUMN quiz_questions.options IS '选项数组，规范格式 [{"key":"A","text":"..."}]，长度 2-10';
COMMENT ON COLUMN quiz_questions.images IS '题目配图数组：[{url,page,bbox,kind}] 或路径字符串；空数组=无图';
COMMENT ON COLUMN quiz_questions.option_count IS '选项数量派生列，自动维护，可直接用于筛选与统计';
COMMENT ON COLUMN quiz_questions.answer IS '正确答案；客观题存选项 key（多选如 "AB"），主观题存参考答案';
COMMENT ON COLUMN quiz_questions.analysis IS '解析';
COMMENT ON COLUMN quiz_questions.rubric IS '主观题评分细则';
COMMENT ON COLUMN quiz_questions.max_score IS '该题满分';
COMMENT ON COLUMN quiz_questions.question_type IS '题型枚举（实测取值 single/judge/fill/calc/essay/draw）';
COMMENT ON COLUMN quiz_questions.answer_type IS '作答类型：objective 可自动判分 / subjective 需人工或 LLM 评分';
COMMENT ON COLUMN quiz_questions.difficulty IS '难度 1-5';
COMMENT ON COLUMN quiz_questions.source_kind IS '来源性质（权威归类列）：past_exam 真题 / textbook 教材 / chapter_exercise 章节习题 等';
COMMENT ON COLUMN quiz_questions.is_past_exam IS '是否真题派生列，等价于 source_kind=past_exam，用于索引加速';
COMMENT ON COLUMN quiz_questions.source_label IS '原始来源标签，仅用于展示，不再承载归类语义';
COMMENT ON COLUMN quiz_questions.origin_document_id IS '来源文档 ID，可回溯到具体资料';
COMMENT ON COLUMN quiz_questions.origin_chunk_id IS '来源分块 ID，可回溯到具体片段';
COMMENT ON COLUMN quiz_questions.year IS '真题年份；source_kind=past_exam 时必填';
COMMENT ON COLUMN quiz_questions.paper IS '试卷标识，如 2026全国卷';
COMMENT ON COLUMN quiz_questions.source_paper IS '来源试卷名';
COMMENT ON COLUMN quiz_questions.source_page IS '来源页码';
COMMENT ON COLUMN quiz_questions.question_no IS '题号（试卷内序号）';
COMMENT ON COLUMN quiz_questions.external_id IS '外部题目唯一 ID，用于跨来源去重';
COMMENT ON COLUMN quiz_questions.subject_id IS '权威科目外键';
COMMENT ON COLUMN quiz_questions.subject IS '兼容列：科目中文名';
COMMENT ON COLUMN quiz_questions.chapter_id IS '权威章节外键';
COMMENT ON COLUMN quiz_questions.chapter IS '兼容列：章节名';
COMMENT ON COLUMN quiz_questions.knowledge_point IS '兼容列：知识点名称（正式关联走 question_knowledge_links）';
COMMENT ON COLUMN quiz_questions.confidence IS '入库置信度：high/medium/low';
COMMENT ON COLUMN quiz_questions.quality IS '质量评级：A/B/C/incomplete';
COMMENT ON COLUMN quiz_questions.ai_generated IS '答案解析是否由 AI 生成';
COMMENT ON COLUMN quiz_questions.verified IS 'AI 生成答案是否经过人工或多角色校验';
COMMENT ON COLUMN quiz_questions.variant_group IS '变式题组 ID，同组内为近似题';
COMMENT ON COLUMN quiz_questions.answer_source IS '答案来源：bank 题库自带 / source_extract 原文抽取 / llm_generated / user_confirmed';
COMMENT ON COLUMN quiz_questions.answer_confidence IS '答案置信度 0-1，低于 0.8 不参与自动判分';
COMMENT ON COLUMN quiz_questions.is_available IS '是否可用（下线标记）';
COMMENT ON COLUMN quiz_questions.is_junk IS '是否 OCR 碎片或答案串，列表默认排除';
COMMENT ON COLUMN quiz_questions.is_retest IS '是否复试题（0 初试 / 1 复试）';
COMMENT ON COLUMN quiz_questions.figure_missing IS '识别图缺失标记：题干引用图表但库内无图';
COMMENT ON COLUMN quiz_questions.validation_status IS '校验门结果：pending/pass/warn/fail';
COMMENT ON COLUMN quiz_questions.validation_errors IS '校验门输出的错误明细数组';
COMMENT ON COLUMN quiz_questions.validated_at IS '最近一次过校验门的时间';
COMMENT ON COLUMN quiz_questions.created_at IS '创建时间（UTC，带时区）';
COMMENT ON COLUMN quiz_questions.updated_at IS '最后更新时间';

-- 索引设计理由：
--   (subject_id, question_type) —— 刷题页最高频：按科目 + 题型抽题
--   (is_available, is_junk)     —— 列表默认过滤条件，复合后避免回表
--   (is_past_exam, year)        —— 真题专项练习，按年份倒序
CREATE INDEX IF NOT EXISTS idx_qq_subject_type ON quiz_questions (subject_id, question_type);
CREATE INDEX IF NOT EXISTS idx_qq_available    ON quiz_questions (is_available, is_junk);
CREATE INDEX IF NOT EXISTS idx_qq_past_exam    ON quiz_questions (is_past_exam, year DESC);
CREATE INDEX IF NOT EXISTS idx_qq_source_kind  ON quiz_questions (source_kind);
CREATE INDEX IF NOT EXISTS idx_qq_variant      ON quiz_questions (variant_group) WHERE variant_group IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_qq_quality      ON quiz_questions (quality) WHERE quality IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_qq_validation   ON quiz_questions (validation_status);
CREATE INDEX IF NOT EXISTS idx_qq_origin_doc   ON quiz_questions (origin_document_id);
CREATE INDEX IF NOT EXISTS idx_qq_chapter      ON quiz_questions (chapter_id);
-- 题干模糊兜底检索
CREATE INDEX IF NOT EXISTS idx_qq_content_trgm ON quiz_questions USING GIN (content gin_trgm_ops);

CREATE OR REPLACE TRIGGER trg_qq_updated BEFORE UPDATE ON quiz_questions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- --------------------------------------------------------------------------- #
-- 题目 ↔ 知识点 关联
-- --------------------------------------------------------------------------- #
CREATE TABLE IF NOT EXISTS question_knowledge_links (
    id                 BIGSERIAL PRIMARY KEY,
    question_id        BIGINT    NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    knowledge_point_id BIGINT    NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
    role               VARCHAR(20) NOT NULL DEFAULT 'primary',
    weight             REAL      NOT NULL DEFAULT 1.0,
    is_verified        BOOLEAN   NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_qkl UNIQUE (question_id, knowledge_point_id),
    CONSTRAINT ck_qkl_role CHECK (role IN ('primary','secondary')),
    CONSTRAINT ck_qkl_weight CHECK (weight >= 0 AND weight <= 1)
);

COMMENT ON TABLE  question_knowledge_links IS '题目与知识点的多对多关联，掌握度由此表聚合派生';
COMMENT ON COLUMN question_knowledge_links.question_id IS '题目 ID，题目删除时级联删除';
COMMENT ON COLUMN question_knowledge_links.knowledge_point_id IS '知识点 ID，知识点删除时级联删除';
COMMENT ON COLUMN question_knowledge_links.role IS '关联角色：primary 主考点 / secondary 次考点';
COMMENT ON COLUMN question_knowledge_links.weight IS '关联权重 0-1，聚合掌握度时作为加权系数';
COMMENT ON COLUMN question_knowledge_links.is_verified IS '是否人工校验过该关联';
COMMENT ON COLUMN question_knowledge_links.created_at IS '创建时间（UTC，带时区）';

CREATE INDEX IF NOT EXISTS idx_qkl_kp ON question_knowledge_links (knowledge_point_id, role);

-- 知识点题目数冗余维护（供知识点列表展示，避免 count(*)）
CREATE OR REPLACE FUNCTION refresh_kp_question_count() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    target_id BIGINT;
BEGIN
    target_id := COALESCE(NEW.knowledge_point_id, OLD.knowledge_point_id);
    IF target_id IS NULL THEN
        RETURN NULL;
    END IF;
    UPDATE knowledge_points
       SET question_count = (
               SELECT COUNT(*) FROM question_knowledge_links
                WHERE knowledge_point_id = target_id)
     WHERE id = target_id;
    RETURN NULL;
END $$;

CREATE OR REPLACE TRIGGER trg_qkl_count AFTER INSERT OR UPDATE OR DELETE ON question_knowledge_links
    FOR EACH ROW EXECUTE FUNCTION refresh_kp_question_count();

-- --------------------------------------------------------------------------- #
-- 试卷与组卷
