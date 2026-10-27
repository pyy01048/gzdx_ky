# -*- coding: utf-8 -*-
"""ETL 主流程：SQLite 抽取 → 管线转换 → JSONL 中间产物。

三条硬约束
----------
1. **只读**：SQLite 一律以 ``mode=ro`` 打开（见 :func:`config.read_only_sqlite_uri`）。
   本阶段不写 ``kaoyan.db``，连前辈脚本也不行；所有产物落到 JSONL。
2. **答案可回填**：``answer_candidates`` 表里有 1099 条经 cross_check 校验过的答案，
   题目缺答案时优先从这里取，并留 ``answer_source`` 证据，不允许把候选答案
   伪装成原题自带答案。
3. **脏数据不混进干净产物**：结构校验不过的记录进 ``*.repair.jsonl``，
   干净率（准确率）由 :mod:`verify` 独立复查，不看清洗器自述。

产物清单（落在 ``--out-dir``）
----------------------------
``questions.clean.jsonl`` / ``questions.repair.jsonl``
``documents.clean.jsonl`` / ``documents.repair.jsonl``
``chunks.clean.jsonl``     / ``chunks.repair.jsonl``
``run_manifest.json``      / ``verification_report.json``
``schema.postgres.sql``    （``--emit-ddl`` 时生成）
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from . import verify as ver
from . import watermark as wm
from .classifier import classify_origin, normalize_subject, split_source_prefix
from .config import DEFAULT_LIMIT, ETL_OUT_DIR, ensure_out_dirs, read_only_sqlite_uri
from .question_schema import CanonicalQuestion, normalize_options, validate_question

__all__ = ["EtlResult", "run_etl", "emit_postgres_ddl", "load_answer_candidates"]

_CLEAN = "clean"
_REPAIR = "repair"

# documents 表读取列（与 models.Document 对齐）
_DOC_COLUMNS = (
    "id", "file_name", "file_type", "file_path", "subject",
    "content", "doc_type", "content_category", "created_at",
)


def load_answer_candidates(conn: sqlite3.Connection) -> dict[int, dict]:
    """加载可用于回填的答案候选（按 question_id 聚合，取置信度最高的一条）。

    Args:
        conn: 只读数据库连接。

    Returns:
        ``{question_id: {"answer", "confidence", "source", "verified_by"}}``。
    """
    best: dict[int, dict] = {}
    try:
        rows = conn.execute(
            "SELECT question_id, answer, confidence, source, verified_by "
            "FROM answer_candidates WHERE answer IS NOT NULL AND TRIM(answer) <> ''"
        ).fetchall()
    except sqlite3.Error:
        return best
    for qid, answer, conf, source, verified_by in rows:
        if qid is None:
            continue
        try:
            score = float(conf or 0)
        except (TypeError, ValueError):
            score = 0.0
        cur = best.get(qid)
        if cur is None or score > cur["confidence"]:
            best[int(qid)] = {
                "answer": str(answer).strip(),
                "confidence": score,
                "source": source,
                "verified_by": verified_by,
            }
    return best


def _build_header_footer_index(conn: sqlite3.Connection, bundle: wm.RulesBundle, limit: int) -> wm.LineFrequencyIndex:
    """用 documents 正文建立页眉页脚频次索引。"""
    idx = wm.LineFrequencyIndex(bundle)
    if not bundle.hf_enabled:
        return idx
    for did, content in conn.execute(
        "SELECT id, content FROM documents "
        "WHERE content IS NOT NULL AND TRIM(content) <> '' LIMIT ?",
        (limit,),
    ):
        idx.add(str(did), content)
    idx.finalize()
    return idx


def _clean_stem_and_leaks(
    stem: str, leaks: list[str], bundle: wm.RulesBundle, hf: wm.LineFrequencyIndex
) -> tuple[str, bool]:
    """把从选项里剔出的题干碎片拼回题干。

    这些碎片原本就是题干的一部分（被切题器误切进选项），丢弃等于丢用户内容。

    **必须先清洗再拼回**：碎片来自未经处理的原始 ``options`` 列，里面可能本身就
    带着水印；若直接拼进已洗净的题干，等于把脏数据从后门又塞了回来，而且绕过
    了所有清洗规则（这类交叉污染在只测单行清洗时是测不出来的）。

    已存在于题干中的碎片不重复拼接。

    Args:
        stem: 已清洗的题干。
        leaks: 来自 :func:`question_schema.normalize_options` 的原始碎片。
        bundle: 水印规则集。
        hf: 页眉页脚索引。

    Returns:
        ``(新题干, 是否发生过回填)``。
    """
    if not leaks:
        return stem, False
    body = stem
    recovered = False
    compact = body.replace(" ", "")
    for leak in leaks:
        if not leak:
            continue
        cleaned, _hits = wm.strip_watermark(leak, bundle, hf)
        if not cleaned.strip():
            continue  # 整段都是水印，拼不拼都没意义
        if cleaned.replace(" ", "") in compact:
            continue
        body = f"{cleaned} {body}".strip()
        recovered = True
    return body, recovered


def _transform_question(
    row: dict, bundle: wm.RulesBundle, hf: wm.LineFrequencyIndex, answers: dict
) -> dict:
    """把一行 quiz_questions 转成 canonical 记录（含完整证据）。"""
    qid = row.get("id")
    raw_source = row.get("source") or ""
    prefix, source_name = split_source_prefix(raw_source)

    stem_raw = row.get("content") or ""
    analysis_raw = row.get("analysis") or ""
    stem_clean, hits = wm.strip_watermark(stem_raw, bundle, hf)
    analysis_clean, _ = wm.strip_watermark(analysis_raw, bundle, hf)

    options, diag = normalize_options(row.get("options"))
    stem_final, recovered = _clean_stem_and_leaks(stem_clean, diag.get("stem_leaks", []), bundle, hf)

    origin, conf, evidence = classify_origin(raw_source, None, stem_raw)
    canonical, bucket, alias_hit = normalize_subject(row.get("subject"), raw_source, None)

    answer = (row.get("answer") or "").strip()
    answer_source = "origin"
    if not answer and qid in answers:
        cand = answers[qid]
        answer = cand["answer"]
        answer_source = f"answer_candidates:{cand['source']}:{cand['verified_by']}"

    q = CanonicalQuestion(
        question_id=qid, stem=stem_final, options=options, answer=answer,
        analysis=analysis_clean, knowledge_points=[row.get("knowledge_point") or ""],
        question_type=row.get("question_type") or "", origin=origin,
        origin_confidence=conf, subject_raw=row.get("subject") or "",
        subject_norm=canonical, subject_bucket=bucket, source=raw_source,
    )
    verdict = validate_question(q)

    record = {
        "kind": "question",
        "question_id": qid,
        "stem": stem_final,
        "text": f"{stem_final}\n{analysis_clean}".strip(),
        "options": options,
        "answer": answer,
        "analysis": analysis_clean,
        "question_type": q.question_type,
        "origin": origin,
        "origin_confidence": conf,
        "origin_evidence": evidence,
        "subject_raw": q.subject_raw,
        "subject_norm": canonical,
        "subject_bucket": bucket,
        "subject_matched_alias": alias_hit,
        "source": raw_source,
        "source_prefix": prefix,
        "source_file": source_name,
        "answer_source": answer_source,
        "diagnostics": diag,
        "stem_recovered_from_options": recovered,
        "watermark_hits": hits,
        "validation": verdict,
    }
    return record


def _partition(records: Iterator[dict] | list[dict]) -> tuple[list[dict], list[dict]]:
    clean, repair = [], []
    for rec in records:
        if rec.get("validation", {}).get("ok"):
            clean.append(rec)
        else:
            repair.append(rec)
    return clean, repair


def emit_postgres_ddl(out_path: Path) -> str:
    """产出 PostgreSQL 目标表 DDL（含治理新增列）。

    Args:
        out_path: 输出文件路径。

    Returns:
        生成的 SQL 文本。
    """
    sql = """-- 由 pipeline.etl_sqlite_to_pg 生成（迁移用，只读不得反向写 SQLite）
CREATE TABLE IF NOT EXISTS quiz_questions_clean (
    id                BIGSERIAL PRIMARY KEY,
    legacy_id         BIGINT UNIQUE,
    stem              TEXT        NOT NULL,
    options           JSONB       NOT NULL DEFAULT '[]'::jsonb,
    answer            TEXT,
    analysis          TEXT,
    question_type     VARCHAR(32) NOT NULL DEFAULT 'single',
    origin            VARCHAR(16) NOT NULL DEFAULT 'unknown',
    origin_confidence REAL        NOT NULL DEFAULT 0,
    subject_norm      VARCHAR(64),
    subject_bucket    VARCHAR(32) NOT NULL DEFAULT 'unknown',
    source            TEXT,
    answer_source     TEXT,
    quality_score     REAL,
    migrated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_qqc_origin   ON quiz_questions_clean(origin);
CREATE INDEX IF NOT EXISTS idx_qqc_subject  ON quiz_questions_clean(subject_norm);
CREATE INDEX IF NOT EXISTS idx_qqc_bucket   ON quiz_questions_clean(subject_bucket);
"""
    out_path.write_text(sql, encoding="utf-8")
    return sql


def _write_jsonl(path: Path, records: list[dict]) -> int:
    if not records:
        return 0
    with path.open("w", encoding="utf-8") as fp:
        for rec in records:
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(records)


class EtlResult(dict):
    """ETL 结果（dict 形态，便于直接转 JSON）。"""


def run_etl(
    *,
    db_path: str | None = None,
    out_dir: str | Path | None = None,
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
    emit_ddl: bool = False,
    verify_only: bool = False,
    seed: int = ver.DEFAULT_SEED,
    threshold: float = ver.DEFAULT_ACCURACY_THRESHOLD,
    sample_size: int = ver.DEFAULT_SAMPLE_SIZE,
) -> EtlResult:
    """执行 ETL。

    Args:
        db_path: SQLite 路径（只读打开）。
        out_dir: 产物目录。
        limit: 每个源处理的最大行数。
        dry_run: True 时不写任何文件，只统计。
        emit_ddl: 是否同时输出 PG DDL。
        verify_only: 只读回已有 ``*.clean.jsonl`` 做验收，不重跑抽取。
        seed: 抽样种子。
        threshold: 准确率门禁。
        sample_size: 抽样数。

    Returns:
        :class:`EtlResult`，含各产物计数与验收报告。

    Raises:
        FileNotFoundError: ``verify_only`` 时找不到已有产物。
        ver.GateRejected: 仅当调用方显式要求 enforce 时（此处只在 report 中标明）。
    """
    out = ensure_out_dirs(out_dir if out_dir is not None else ETL_OUT_DIR)
    bundle = wm.load_rules()
    result = EtlResult(dry_run=dry_run, out_dir=str(out), limit=limit)

    if verify_only:
        clean_records: list[dict] = []
        for name in ("questions.clean.jsonl", "documents.clean.jsonl", "chunks.clean.jsonl"):
            fp = out / name
            if not fp.exists():
                raise FileNotFoundError(f"缺少待验收产物：{fp}（请先跑一次 ETL）")
            # 必须用 split("\n") 而非 splitlines()：splitlines() 会把 U+2028/U+2029
            # 等 Unicode 行分隔符也当换行，把一条完整的 JSON 行劈成两半导致解析失败。
            clean_records.extend(
                json.loads(line) for line in fp.read_text(encoding="utf-8").split("\n") if line.strip()
            )
        report = ver.verify_batch(
            clean_records, threshold=threshold, sample_size=sample_size, seed=seed, bundle=bundle
        )
        if not dry_run:
            (out / "verification_report.json").write_text(
                json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
        result.update(total=len(clean_records), verification=report.to_dict())
        return result

    conn = sqlite3.connect(read_only_sqlite_uri(db_path), uri=True)
    try:
        answers = load_answer_candidates(conn)
        hf = _build_header_footer_index(conn, bundle, limit)

        # 只读连接：任何 UPDATE/INSERT/DELETE 都会被 SQLite 直接拒绝
        rows = conn.execute(
            "SELECT id, content, options, answer, analysis, subject, question_type, "
            "knowledge_point, source FROM quiz_questions"
            " ORDER BY id LIMIT ?",
            (limit,),
        )
        records = [_transform_question(dict(zip(
            ["id", "content", "options", "answer", "analysis", "subject",
             "question_type", "knowledge_point", "source"], r)), bundle, hf, answers)
            for r in rows
        ]
        q_clean, q_repair = _partition(records)

        doc_records: list[dict] = []
        for doc in conn.execute(
            "SELECT " + ",".join(_DOC_COLUMNS) + " FROM documents LIMIT ?", (limit,)
        ):
            rowdict = dict(zip(_DOC_COLUMNS, doc))
            text, hits = wm.strip_watermark(rowdict.get("content") or "", bundle, hf)
            canonical, bucket, alias_hit = normalize_subject(
                rowdict.get("subject"), None, rowdict.get("file_name")
            )
            origin, conf, ev = classify_origin(None, rowdict.get("file_name"), text)
            ok = (ver.count_meaningful(text) >= ver.MIN_CONTENT_CHARS
                  and not wm.find_residue(text, bundle))
            doc_records.append({
                "kind": "document",
                "doc_id": rowdict.get("id"),
                "file_name": rowdict.get("file_name"),
                "file_type": rowdict.get("file_type"),
                "text": text,
                "origin": origin,
                "origin_confidence": conf,
                "subject_raw": rowdict.get("subject") or "",
                "subject_norm": canonical,
                "subject_bucket": bucket,
                "subject_matched_alias": alias_hit,
                "watermark_hits": hits,
                "meta": {"chars": len(text), "engine": "passthrough:sqlite_content"},
                "validation": {"ok": ok, "errors": [] if ok else ["empty_or_residue"],
                               "warnings": [], "score": 1.0 if ok else 0.0},
            })
        d_clean, d_repair = _partition(doc_records)

        chunk_records: list[dict] = []
        for cid, kid, text_raw, subj in conn.execute(
            "SELECT chunk_id, id, text, subject FROM knowledge_chunks"
            " WHERE text IS NOT NULL LIMIT ?",
            (limit,),
        ):
            text, hits = wm.strip_watermark(text_raw or "", bundle, hf)
            canonical, bucket, alias_hit = normalize_subject(subj, None, None)
            ok = (ver.count_meaningful(text) >= ver.MIN_CONTENT_CHARS
                  and not wm.find_residue(text, bundle))
            chunk_records.append({
                "kind": "chunk",
                "chunk_id": cid,
                "id": kid,
                "text": text,
                "subject_raw": subj or "",
                "subject_norm": canonical,
                "subject_bucket": bucket,
                "subject_matched_alias": alias_hit,
                "watermark_hits": hits,
                "meta": {"chars": len(text)},
                "validation": {"ok": ok, "errors": [] if ok else ["empty_or_residue"],
                               "warnings": [], "score": 1.0 if ok else 0.0},
            })
        c_clean, c_repair = _partition(chunk_records)
    finally:
        conn.close()

    report = ver.verify_batch(
        q_clean + d_clean + c_clean,
        threshold=threshold, sample_size=sample_size, seed=seed, bundle=bundle, hf=hf,
    )
    result.update(
        questions_total=len(records), questions_clean=len(q_clean), questions_repair=len(q_repair),
        documents_clean=len(d_clean), documents_repair=len(d_repair),
        chunks_clean=len(c_clean), chunks_repair=len(c_repair),
        answers_enriched=sum(1 for r in records if r["answer_source"].startswith("answer_candidates")),
        verification=report.to_dict(),
    )

    if dry_run:
        result.update(written=False)
        return result

    result["files"] = {
        "questions.clean.jsonl": _write_jsonl(out / "questions.clean.jsonl", q_clean),
        "questions.repair.jsonl": _write_jsonl(out / "questions.repair.jsonl", q_repair),
        "documents.clean.jsonl": _write_jsonl(out / "documents.clean.jsonl", d_clean),
        "documents.repair.jsonl": _write_jsonl(out / "documents.repair.jsonl", d_repair),
        "chunks.clean.jsonl": _write_jsonl(out / "chunks.clean.jsonl", c_clean),
        "chunks.repair.jsonl": _write_jsonl(out / "chunks.repair.jsonl", c_repair),
    }
    (out / "verification_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / "run_manifest.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "verification"},
                   ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if emit_ddl:
        emit_postgres_ddl(out / "schema.postgres.sql")
    result.update(written=True)
    return result
