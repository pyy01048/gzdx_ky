-- =============================================================================
-- 081 校验门与兼容层：题目入库体检函数 / 触发器 / 历史数据迁移函数 / 旧名兼容视图
-- 依赖：000 - 080（必须最后执行）
-- =============================================================================

-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION validate_question_row() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    errs  jsonb := '[]'::jsonb;
    keys  text[];
    ch    text;
    found boolean;
BEGIN
    IF NEW.subject_id IS NULL THEN
        errs := errs || jsonb_build_object('code', 'missing_subject',
                                           'msg', '未关联权威科目');
    END IF;

    -- 题干洁净度
    IF check_stem_clean(NEW.content) IS NOT NULL THEN
        errs := errs || jsonb_build_object('code', check_stem_clean(NEW.content),
                                           'msg', '题干不洁净（过短或混入选项行）');
    END IF;

    -- 题型与选项一致性
    IF check_options_consistency(NEW.options, NEW.question_type) IS NOT NULL THEN
        errs := errs || jsonb_build_object(
            'code', check_options_consistency(NEW.options, NEW.question_type),
            'msg', '题型与选项数量不匹配');
    END IF;

    IF NEW.answer IS NULL OR btrim(NEW.answer) = '' THEN
        errs := errs || jsonb_build_object('code', 'missing_answer',
                                           'msg', '缺少答案');
    ELSIF NEW.question_type IN ('single', 'multiple') AND NEW.options IS NOT NULL THEN
        -- 校验答案的每个字符都能在选项 key 里找到（多选如 "AB"）
        keys := ARRAY(SELECT upper(o->>'key') FROM jsonb_array_elements(NEW.options) AS o);
        FOREACH ch IN ARRAY regexp_split_to_array(upper(btrim(NEW.answer)), '') LOOP
            IF ch <> '' AND NOT (ch = ANY(keys)) THEN
                errs := errs || jsonb_build_object('code', 'answer_key_mismatch',
                                                   'msg', '答案 ' || ch || ' 不在选项 key 中');
            END IF;
        END LOOP;
        IF NEW.question_type = 'single' AND array_length(regexp_split_to_array(btrim(NEW.answer), ''), 1) > 1 THEN
            errs := errs || jsonb_build_object('code', 'single_multi_answer',
                                               'msg', '单选题出现多个答案字符');
        END IF;
    END IF;

    IF NEW.analysis IS NULL OR btrim(NEW.analysis) = '' THEN
        errs := errs || jsonb_build_object('code', 'missing_analysis',
                                           'msg', '缺少解析');
    END IF;

    IF NEW.answer_type = 'objective'
       AND NEW.answer_confidence IS NOT NULL
       AND NEW.answer_confidence < 0.8 THEN
        errs := errs || jsonb_build_object('code', 'low_answer_confidence',
                                           'msg', '客观题答案置信度低于 0.8，禁止自动判分');
    END IF;

    NEW.validation_errors := errs;
    NEW.validation_status := CASE WHEN jsonb_array_length(errs) = 0
                                  THEN 'pass' ELSE 'warn' END;
    NEW.validated_at := now();
    RETURN NEW;
END $$;

CREATE OR REPLACE TRIGGER trg_quiz_questions_gate
BEFORE INSERT OR UPDATE OF content, options, answer, analysis,
                           question_type, answer_type, answer_confidence, subject_id
ON quiz_questions
FOR EACH ROW EXECUTE FUNCTION validate_question_row();

-- --------------------------------------------------------------------------- #
-- 兼容视图（过渡层）：旧表名 / 旧口径，供存量代码逐步迁移
--   约定：所有 *_compat / 旧名视图一律只读；新代码必须写新表。
-- --------------------------------------------------------------------------- #

-- 旧 subject_config：以中文科目名为主键，chapters / question_types 为 JSON 数组
CREATE OR REPLACE VIEW subject_config AS
SELECT s.name                                   AS subject,
       COALESCE((SELECT jsonb_agg(jsonb_build_object('code', c.code, 'title', c.title)
                                  ORDER BY c.sort_order)
                   FROM subject_chapters c
                  WHERE c.subject_id = s.id), '[]'::jsonb)  AS chapters,
       COALESCE(sc.question_types, '[]'::jsonb)  AS question_types,
       COALESCE(s.is_custom, FALSE)              AS is_custom,
       s.created_at                              AS created_at,
       s.updated_at                              AS updated_at
  FROM subjects s
  LEFT JOIN subject_configs sc ON sc.subject_id = s.id;

COMMENT ON VIEW subject_config IS
    '兼容视图（只读）：旧 subject_config 表口径，数据源改为 subjects + subject_chapters + subject_configs';

-- 旧 kaoyan_subjects：招生学科口径
CREATE OR REPLACE VIEW kaoyan_subjects AS
SELECT id, code, name, category, parent_code, exam_overlap, description, sort_order, created_at
  FROM disciplines;

COMMENT ON VIEW kaoyan_subjects IS
    '兼容视图（只读）：旧 kaoyan_subjects 表口径，数据源改为 disciplines';

-- 旧 subject_prototypes：以中文科目名呈现原型向量
CREATE OR REPLACE VIEW subject_prototypes_by_name AS
SELECT s.name AS subject, p.engine, p.dim, p.prototype, p.n_samples, p.built_at
  FROM subject_prototypes p
  JOIN subjects s ON s.id = p.subject_id;

COMMENT ON VIEW subject_prototypes_by_name IS
    '兼容视图（只读）：旧 subject_prototypes 表口径，以中文科目名呈现原型向量';

-- 旧 knowledge_points：补出派生的 mastery 统计列
--
-- 2026-10-14 修正：原先这里写 ``SELECT kp.*, COALESCE(m.mastery,0) AS mastery``。
-- 但 094a 已经给 knowledge_points **真实加上了 mastery 物理列**，
-- 于是 kp.* 里本就含 mastery，再显式 AS mastery 就成了
--     DuplicateColumn: column "mastery" specified more than once
-- 而 mastery 的值又由 093 的触发器从 v_knowledge_mastery 同步而来，
-- 这里再派生一次属于重复计算。
-- 现在只补另外两个统计列（attempts / correct），mastery 直接取表列。
CREATE OR REPLACE VIEW knowledge_points_legacy AS
SELECT kp.*,
       COALESCE(m.attempts, 0) AS mastery_attempts,
       COALESCE(m.correct, 0)  AS mastery_correct
  FROM knowledge_points kp
  LEFT JOIN v_knowledge_mastery m ON m.knowledge_point_id = kp.id;

COMMENT ON VIEW knowledge_points_legacy IS
    '兼容视图（只读）：旧 knowledge_points 含 mastery 列，mastery 现由 v_knowledge_mastery 派生';

-- --------------------------------------------------------------------------- #
-- 历史选项迁移：把 ["A．文本"] 字符串数组转成 [{"key":"A","text":"文本"}]
--   用法（在导入存量数据后执行，可重复调用直到返回 0）：
--     SELECT migrate_legacy_options();
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION normalize_legacy_option(raw text) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE
        WHEN raw IS NULL OR btrim(raw) = '' THEN NULL
        ELSE jsonb_build_object(
            'key', upper(coalesce((regexp_match(raw, '^\s*([A-Za-z])\s*[．.、:：]'))[1], 'A')),
            'text', btrim(regexp_replace(raw, '^\s*[A-Za-z]\s*[．.、:：]\s*', '')))
    END;
$$;

COMMENT ON FUNCTION normalize_legacy_option(text) IS
    '把 "A．选项文本" 形式的旧选项字符串转成 {"key":"A","text":"选项文本"} 对象';

CREATE OR REPLACE FUNCTION migrate_legacy_options(batch_limit integer DEFAULT 5000)
RETURNS integer LANGUAGE plpgsql AS $$
DECLARE
    affected integer := 0;
BEGIN
    WITH legacy AS (
        SELECT id
          FROM quiz_questions
         WHERE options IS NOT NULL
           AND jsonb_typeof(options) = 'array'
           AND jsonb_array_length(options) > 0
           AND jsonb_typeof(options -> 0) = 'string'
         LIMIT batch_limit
    )
    UPDATE quiz_questions q
       SET options = COALESCE((
               SELECT jsonb_agg(normalize_legacy_option(o.elem) ORDER BY o.ord)
                 FROM legacy l,
                      jsonb_array_elements_text(l.options) WITH ORDINALITY AS o(elem, ord)
                WHERE l.id = q.id), '[]'::jsonb)
     WHERE q.id IN (SELECT id FROM legacy);

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END $$;

COMMENT ON FUNCTION migrate_legacy_options(integer) IS
    '批量把旧格式选项（字符串数组）迁移为规范对象数组，可重复调用直到返回 0';

-- --------------------------------------------------------------------------- #
-- 来源归类迁移：把 "知识库:" / "真题:" 前缀拆到正交列 source_kind
--   用法：SELECT migrate_legacy_source_kind();
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION migrate_legacy_source_kind() RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    affected integer := 0;
BEGIN
    UPDATE quiz_questions
       SET source_kind = CASE
               WHEN source LIKE '真题:%'      THEN 'past_exam'::source_kind
               WHEN source LIKE '知识库:%'    THEN 'textbook'::source_kind
               WHEN source LIKE 'ai:%'        THEN 'ai_generated'::source_kind
               ELSE source_kind
           END,
           source_label = regexp_replace(coalesce(source, ''), '^(知识库|真题|ai):', '')
     WHERE source IS NOT NULL
       AND (source LIKE '知识库:%' OR source LIKE '真题:%' OR source LIKE 'ai:%');

    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected;
END $$;

COMMENT ON FUNCTION migrate_legacy_source_kind() IS
    '把 source 列的历史前缀归类迁移到正交列 source_kind，并把剩余部分留作展示标签';
