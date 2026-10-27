-- =============================================================================
-- 092 subject_config 兼容视图可写化（INSTEAD OF INSERT/UPDATE/DELETE 触发器）
-- 依赖：010（subjects / subject_chapters / subject_configs）、081（subject_config 视图）
--
-- 问题（实测）
-- -----------
-- 081 把 `subject_config` 建成**只读兼容视图**（数据源 subjects + subject_chapters
-- + subject_configs），但存量代码有 6 处直接读写它：
--   routers/taxonomy.py:122   INSERT INTO subject_config
--   routers/taxonomy.py:151/247  SELECT
--   services/subject_registry.py:145  INSERT
--   services/taxonomy.py:512 / services/kb_service.py:713  SELECT
-- 结果：切到 PG 后 POST /api/taxonomy/subjects 直接 500——
--   "cannot insert into view subject_config: Views that do not select from a
--    single table are not automatically updatable."
--
-- 修复策略（为什么用触发器而不是改 Python）
-- ----------------------------------------
-- 存量路由尚未完成 ADR-002 的"改外键"迁移，此时逐处改 Python 会同时动 6 个文件
-- 且易漏；在视图上装 INSTEAD OF 触发器，可让**旧代码零改动透明可用**，
-- 等业务路由真正迁到实体表后再撤掉兼容层（ADR-002 Phase 2 的既定动作）。
--
-- 映射关系
-- --------
--   subject_config.subject        → subjects.name（不存在则建）
--   subject_config.chapters[]     → subject_chapters（全删重插，保持与 JSON 语义一致）
--   subject_config.question_types → subject_configs.question_types
--   subject_config.is_custom      → subjects.is_custom
-- =============================================================================

-- --------------------------------------------------------------------------- #
-- subject code 生成：中文名 → 稳定的英文/拼音代码
-- 中文科目名没有现成 code，用 'custom_' + 短哈希保证唯一且可复现。
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION subject_code_from_name(p_name TEXT)
RETURNS VARCHAR(32)
LANGUAGE plpgsql
AS $$
BEGIN
    -- 已存在同名科目则复用其 code
    RETURN COALESCE(
        (SELECT code FROM subjects WHERE name = p_name LIMIT 1),
        'custom_' || substr(md5(p_name), 1, 12)
    );
END;
$$;

COMMENT ON FUNCTION subject_code_from_name(TEXT) IS
    '由科目中文名生成稳定 code：已存在的复用，新科目用 custom_+md5 前12位';

-- --------------------------------------------------------------------------- #
-- INSERT 触发器
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION subject_config_ins()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_id    BIGINT;
    v_ch    JSONB;
    v_item  JSONB;
    v_ord   INTEGER := 0;
    v_code  TEXT;
    v_title TEXT;
BEGIN
    -- 1) 科目主行
    SELECT id INTO v_id FROM subjects WHERE name = NEW.subject;
    IF v_id IS NULL THEN
        INSERT INTO subjects (code, name, category, is_custom, sort_order)
        VALUES (subject_code_from_name(NEW.subject), NEW.subject, 'professional',
                COALESCE(NEW.is_custom, FALSE),
                COALESCE((SELECT MAX(sort_order) + 1 FROM subjects), 100))
        RETURNING id INTO v_id;
    END IF;

    -- 2) 章节：全删重插，与 JSON 数组语义一致
    DELETE FROM subject_chapters WHERE subject_id = v_id;
    v_ch := COALESCE(NEW.chapters, '[]'::jsonb);
    IF jsonb_typeof(v_ch) = 'array' THEN
        FOR v_item IN SELECT * FROM jsonb_array_elements(v_ch) LOOP
            v_ord := v_ord + 1;
            -- 支持两种元素形态：字符串 "第1章 xxx" 或对象 {"code":..,"title":..}
            IF jsonb_typeof(v_item) = 'object' THEN
                v_code  := COALESCE(v_item->>'code', 'ch' || lpad(v_ord::text, 2, '0'));
                v_title := COALESCE(v_item->>'title', v_item->>'name', '');
            ELSE
                v_code  := 'ch' || lpad(v_ord::text, 2, '0');
                v_title := trim(both '"' from v_item::text);
            END IF;
            IF v_title <> '' THEN
                INSERT INTO subject_chapters (subject_id, code, title, sort_order)
                VALUES (v_id, v_code, v_title, v_ord)
                ON CONFLICT (subject_id, code) DO UPDATE SET title = EXCLUDED.title;
            END IF;
        END LOOP;
    END IF;

    -- 3) 题型配置
    INSERT INTO subject_configs (subject_id, question_types, is_custom)
    VALUES (v_id, COALESCE(NEW.question_types, '[]'::jsonb), COALESCE(NEW.is_custom, FALSE))
    ON CONFLICT (subject_id) DO UPDATE
       SET question_types = EXCLUDED.question_types,
           is_custom = EXCLUDED.is_custom;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_subject_config_ins ON subject_config;
CREATE OR REPLACE TRIGGER trg_subject_config_ins
    INSTEAD OF INSERT ON subject_config
    FOR EACH ROW EXECUTE FUNCTION subject_config_ins();

-- --------------------------------------------------------------------------- #
-- UPDATE 触发器（科目改名时同步 subjects.name）
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION subject_config_upd()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_id  BIGINT;
    v_ch  JSONB;
    v_item JSONB;
    v_ord INTEGER := 0;
    v_code TEXT;
    v_title TEXT;
BEGIN
    SELECT id INTO v_id FROM subjects WHERE name = OLD.subject;
    IF v_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- 改名（subject 是视图主键，改名即换科目名）
    IF NEW.subject IS DISTINCT FROM OLD.subject THEN
        UPDATE subjects SET name = NEW.subject, updated_at = now() WHERE id = v_id;
    END IF;
    IF NEW.is_custom IS DISTINCT FROM OLD.is_custom THEN
        UPDATE subjects SET is_custom = NEW.is_custom, updated_at = now() WHERE id = v_id;
    END IF;

    -- 章节全量重写
    IF NEW.chapters IS DISTINCT FROM OLD.chapters THEN
        DELETE FROM subject_chapters WHERE subject_id = v_id;
        v_ch := COALESCE(NEW.chapters, '[]'::jsonb);
        IF jsonb_typeof(v_ch) = 'array' THEN
            FOR v_item IN SELECT * FROM jsonb_array_elements(v_ch) LOOP
                v_ord := v_ord + 1;
                IF jsonb_typeof(v_item) = 'object' THEN
                    v_code  := COALESCE(v_item->>'code', 'ch' || lpad(v_ord::text, 2, '0'));
                    v_title := COALESCE(v_item->>'title', v_item->>'name', '');
                ELSE
                    v_code  := 'ch' || lpad(v_ord::text, 2, '0');
                    v_title := trim(both '"' from v_item::text);
                END IF;
                IF v_title <> '' THEN
                    INSERT INTO subject_chapters (subject_id, code, title, sort_order)
                    VALUES (v_id, v_code, v_title, v_ord)
                    ON CONFLICT (subject_id, code) DO UPDATE SET title = EXCLUDED.title;
                END IF;
            END LOOP;
        END IF;
    END IF;

    IF NEW.question_types IS DISTINCT FROM OLD.question_types THEN
        INSERT INTO subject_configs (subject_id, question_types, is_custom)
        VALUES (v_id, COALESCE(NEW.question_types, '[]'::jsonb), COALESCE(NEW.is_custom, FALSE))
        ON CONFLICT (subject_id) DO UPDATE SET question_types = EXCLUDED.question_types;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_subject_config_upd ON subject_config;
CREATE OR REPLACE TRIGGER trg_subject_config_upd
    INSTEAD OF UPDATE ON subject_config
    FOR EACH ROW EXECUTE FUNCTION subject_config_upd();

-- --------------------------------------------------------------------------- #
-- DELETE 触发器
-- 语义对齐 models.SubjectConfig 的注释：「删除配置行不影响业务表里既有的科目标签字符串」。
-- 故只删 subjects 行（级联带走 chapters/configs），不触碰 quiz_questions 等。
-- --------------------------------------------------------------------------- #
CREATE OR REPLACE FUNCTION subject_config_del()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM subjects WHERE name = OLD.subject;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_subject_config_del ON subject_config;
CREATE OR REPLACE TRIGGER trg_subject_config_del
    INSTEAD OF DELETE ON subject_config
    FOR EACH ROW EXECUTE FUNCTION subject_config_del();
