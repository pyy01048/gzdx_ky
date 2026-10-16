# -*- coding: utf-8 -*-
"""将治理后的 JSONL 装载到 PostgreSQL canonical 表。

原则：只写 PostgreSQL，不修改 SQLite；每批事务提交，失败自动回滚。
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from datetime import datetime, timezone
import psycopg
from psycopg.types.json import Json

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.config import ETL_OUT_DIR, pg_database_url  # noqa: E402

def read_jsonl(path: Path):
    if not path.exists(): return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

def enum_or(value, allowed, fallback):
    return value if value in allowed else fallback

def load_questions(cur, rows):
    allowed_q = {"single","multiple","judge","fill","calc","essay","draw","proof","other"}
    allowed_source = {"past_exam","textbook","chapter_exercise","mock_exam","ai_generated","user_created","external_import"}
    count = 0
    for r in rows:
        v = r.get("validation") or {}
        if not v.get("ok"): continue
        opts = r.get("options") or None
        # 主观题不写空数组；规范数组必须包含 key/text 对象。
        if qtype := r.get("question_type"):
            if qtype not in {"single", "multiple", "judge"}:
                opts = None
        if not isinstance(opts, list) or len(opts) < 2 or not all(isinstance(x, dict) and 'key' in x and 'text' in x for x in opts):
            opts = None
        origin = enum_or(r.get("origin"), allowed_source, "external_import")
        # PG 约束要求真题必须带年份；缺少年份的历史前缀题先归入章节习题，进入待人工核验。
        if origin == "past_exam" and not r.get("year"):
            origin = "chapter_exercise"
        qtype = enum_or(r.get("question_type"), allowed_q, "other")
        cur.execute("""
            INSERT INTO quiz_questions
              (content, options, answer, analysis, question_type,
               answer_type, difficulty, source_kind, subject, knowledge_point,
               confidence, is_available, is_junk, is_retest, validation_status,
               validation_errors, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s::question_type,%s::answer_type,%s,%s::source_kind,
                    %s,%s,%s::confidence_level,true,false,false,%s::question_validation_status,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, (r.get("stem",""), Json(opts) if opts is not None else None,
              r.get("answer") or None, r.get("analysis") or None, qtype,
              "objective" if qtype in {"single","multiple","judge"} else "subjective",
              3, origin, r.get("subject_norm") or None, 
              ",".join(r.get("knowledge_points") or []) or None,
              "high" if r.get("origin_confidence", 0) >= .8 else "medium",
              "pass", json.dumps([], ensure_ascii=False), datetime.now(timezone.utc), datetime.now(timezone.utc)))
        count += 1
    return count

def load_documents(cur, rows):
    count = 0
    for r in rows:
        v = r.get("validation") or {}
        if not v.get("ok"): continue
        doc_format = enum_or((r.get("file_type") or "other").lower(), {"pdf","txt","doc","docx","md","image","pptx","ppt","xlsx","html","json","jpg","png","other"}, "other")
        cur.execute("""
            INSERT INTO documents
              (file_name, source_format, canonical_content, canonical_engine,
               canonical_version, content, subject, source_kind, index_status,
               parse_progress, knowledge_point_count, chunk_count, ocr_used,
               created_at, updated_at)
            VALUES (%s,%s::doc_format,%s,'etl-watermark-v1',1,%s,%s,%s::source_kind,
                    'pending'::index_status,0,0,0,false,%s,%s)
            ON CONFLICT DO NOTHING
        """, (r.get("file_name") or "未命名文档", doc_format,
              r.get("text") or "", r.get("text") or "", r.get("subject_norm") or None,
              enum_or(r.get("origin"), {"past_exam","textbook","chapter_exercise","mock_exam","ai_generated","user_created","external_import"}, "external_import"),
              datetime.now(timezone.utc), datetime.now(timezone.utc)))
        count += 1
    return count

def load_chunks(cur, rows):
    count = 0
    for r in rows:
        v = r.get("validation") or {}
        if not v.get("ok"): continue
        text = r.get("text") or ""
        cur.execute("""
            INSERT INTO knowledge_chunks
              (doc_name, chunk_index, text, search_tokens, subject, token_count, created_at, updated_at)
            VALUES (%s,0,%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, (r.get("doc_name") or "", text, text, r.get("subject_norm") or None,
              len(text), datetime.now(timezone.utc), datetime.now(timezone.utc)))
        count += 1
    return count

def main():
    p = argparse.ArgumentParser(description="装载治理 JSONL 到 PostgreSQL")
    p.add_argument("--input", default=str(ETL_OUT_DIR))
    p.add_argument("--database-url", default=None,
                   help="缺省走 pg_database_url()：DATABASE_URL > .env 的 PG_* 分项")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    root = Path(args.input)
    q, d, c = (read_jsonl(root / n) for n in ("questions.clean.jsonl","documents.clean.jsonl","chunks.clean.jsonl"))
    print(f"待装载：题目 {len(q)}，文档 {len(d)}，分块 {len(c)}")
    if args.dry_run: return
    with psycopg.connect(args.database_url or pg_database_url()) as conn:
        with conn.cursor() as cur:
            counts = {"questions": load_questions(cur,q), "documents": load_documents(cur,d), "chunks": load_chunks(cur,c)}
        conn.commit()
    print(json.dumps(counts, ensure_ascii=False))

if __name__ == "__main__": main()
