-- C 批次1：科目待分类队列（评估报告 #24：目录名匹配失败进队列而非静默落「其他」）
-- 幂等：IF NOT EXISTS；不改任何既有表结构。
CREATE TABLE IF NOT EXISTS document_classify_queue (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    file_name VARCHAR(500),
    suggested_subject VARCHAR(100),
    reason VARCHAR(200),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    resolved_subject VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_document_classify_queue_status
    ON document_classify_queue (status);
