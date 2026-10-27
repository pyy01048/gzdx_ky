-- #17 院校后台：软删除 + 审计日志 + 合规字段
-- 目标: 
--   1. 为 kaoyan_* 业务表添加 enabled/deleted_at 字段
--   2. 创建 audit_logs 表记录写操作
--   3. 确保采集合规（不存敏感字段）

BEGIN;

-- 1. 为院校相关表添加软删除与启用标记
ALTER TABLE kaoyan_schools 
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE kaoyan_colleges 
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE kaoyan_majors 
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE kaoyan_admissions 
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE kaoyan_scorelines 
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- 补充缺失字段（兼容旧schema）
ALTER TABLE kaoyan_admissions 
    ADD COLUMN IF NOT EXISTS source VARCHAR(50),
    ADD COLUMN IF NOT EXISTS extra JSONB;

-- 注意：kaoyan_subjects 是视图，不添加字段

-- 2. 创建审计日志表（只追加不可改）
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    record_id BIGINT NOT NULL,
    action VARCHAR(50) NOT NULL, -- INSERT/UPDATE/DELETE/ENABLE/DISABLE
    operator_id BIGINT, -- 执行操作的用户ID（NULL表示系统操作）
    operator_ip INET, -- 操作者IP
    before_data JSONB, -- 变更前快照（DELETE时完整，UPDATE时仅变更字段）
    after_data JSONB, -- 变更后快照（INSERT时完整，UPDATE时仅变更字段）
    change_summary TEXT, -- 人类可读的变更摘要
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引优化查询
CREATE INDEX IF NOT EXISTS idx_audit_logs_table_record ON audit_logs(table_name, record_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_operator ON audit_logs(operator_id);

COMMENT ON TABLE audit_logs IS '审计日志：记录所有写操作，不可修改不可删除';
COMMENT ON COLUMN audit_logs.before_data IS '变更前数据快照';
COMMENT ON COLUMN audit_logs.after_data IS '变更后数据快照';

-- 3. 创建触发器函数自动记录审计日志
CREATE OR REPLACE FUNCTION fn_audit_log()
RETURNS TRIGGER AS $$
DECLARE
    v_action VARCHAR(50);
    v_before JSONB;
    v_after JSONB;
    v_summary TEXT;
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_action := 'INSERT';
        v_before := NULL;
        v_after := to_jsonb(NEW);
        v_summary := format('插入 %I 记录 ID=%s', TG_TABLE_NAME, NEW.id);
    ELSIF TG_OP = 'UPDATE' THEN
        v_action := 'UPDATE';
        v_before := to_jsonb(OLD);
        v_after := to_jsonb(NEW);
        -- 仅记录实际变更的字段
        v_before := jsonb_strip_nulls(
            (SELECT jsonb_object_agg(key, value) 
             FROM jsonb_each(v_before) 
             WHERE value != (v_after->key))
        );
        v_after := jsonb_strip_nulls(
            (SELECT jsonb_object_agg(key, value) 
             FROM jsonb_each(v_after) 
             WHERE value != (v_before->key))
        );
        v_summary := format('更新 %I 记录 ID=%s', TG_TABLE_NAME, NEW.id);
    ELSIF TG_OP = 'DELETE' THEN
        v_action := 'DELETE';
        v_before := to_jsonb(OLD);
        v_after := NULL;
        v_summary := format('删除 %I 记录 ID=%s', TG_TABLE_NAME, OLD.id);
    END IF;

    INSERT INTO audit_logs(table_name, record_id, action, before_data, after_data, change_summary)
    VALUES (TG_TABLE_NAME, COALESCE(NEW.id, OLD.id), v_action, v_before, v_after, v_summary);

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- 4. 为关键表绑定审计触发器
DROP TRIGGER IF EXISTS trg_audit_kaoyan_schools ON kaoyan_schools;
CREATE TRIGGER trg_audit_kaoyan_schools
    AFTER INSERT OR UPDATE OR DELETE ON kaoyan_schools
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

DROP TRIGGER IF EXISTS trg_audit_kaoyan_colleges ON kaoyan_colleges;
CREATE TRIGGER trg_audit_kaoyan_colleges
    AFTER INSERT OR UPDATE OR DELETE ON kaoyan_colleges
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

DROP TRIGGER IF EXISTS trg_audit_kaoyan_majors ON kaoyan_majors;
CREATE TRIGGER trg_audit_kaoyan_majors
    AFTER INSERT OR UPDATE OR DELETE ON kaoyan_majors
    FOR EACH ROW EXECUTE FUNCTION fn_audit_log();

COMMIT;
