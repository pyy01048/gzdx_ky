# -*- coding: utf-8 -*-
"""SQLite → PostgreSQL 全量直搬（canonical schema 版）。

与 ``pipeline/load_postgres.py`` 的区别（为什么另写一个）
--------------------------------------------------------
``load_postgres.py`` 只搬 questions / documents / chunks 三张表，且走 JSONL
中间产物、依赖 ETL 的治理转换。它造成的实际后果是 PG 65 张表里 60 张全空
（院校库、知识点、单词、卡片、错题全部没搬），core 业务直接不可用。

本脚本改为 **按表直搬**：
  * 逐表读取 SQLite 全量数据（只读 mode=ro），按 PG canonical schema 映射列；
  * 覆盖 PG 全部业务表，而不仅是三张；
  * 分批提交 + 断点续传（每张表记录已提交行数），失败可重入；
  * 迁移前做约束预检，把会被 CHECK 拒绝的行**显式降级并记录证据**，
    绝不静默丢数据。

设计红线
--------
1. **只读 SQLite**：以 mode=ro 打开，物理上无法写入源库。
2. **不删 PG 已有数据**：使用 TRUNCATE ... RESTART IDENTITY 前需显式 --reset-table，
   默认按主键 ON CONFLICT DO NOTHING 增量追加，保证可重入。
3. **每个被降级的行都留证据**：写入 migration_report.json 的降级明细。
4. **外键回填**：documents.subject_id / knowledge_points.subject_id 等由
   subjects.code ↔ 中文名映射回填，回填不上的保持 NULL 并记入报告。

用法
----
    python -m pipeline.migrate_all                      # 全量迁移
    python -m pipeline.migrate_all --dry-run            # 只统计不写
    python -m pipeline.migrate_all --only documents     # 只迁指定表
    python -m pipeline.migrate_all --skip-chunks        # 跳过大表（chunks 6 万行）
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import psycopg  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from pipeline.config import pg_database_url, read_only_sqlite_uri  # noqa: E402

REPORT_PATH = BASE_DIR.parent / "data" / "migration_report.json"
BATCH = 500

# --------------------------------------------------------------------------- #
# 表清单：(SQLite表名, PG表名, 迁移策略)
# 策略 keep_id —— 保留原主键（下游外键引用依赖 id 稳定）
# --------------------------------------------------------------------------- #
TABLES: list[tuple[str, str]] = [
    # —— 系统与配置（父表） ——
    ("platform_configs", "platform_configs"),
    ("ai_providers", "ai_providers"),
    ("custom_links", "custom_links"),
    # —— 文档与知识域（documents 是 chunks / kp 的父表，必须最先） ——
    ("documents", "documents"),
    ("knowledge_chunks", "knowledge_chunks"),
    ("knowledge_points", "knowledge_points"),
    ("knowledge_point_relations", "knowledge_point_relations"),
    # —— 题库域 ——
    ("quiz_questions", "quiz_questions"),
    ("question_knowledge_links", "question_knowledge_links"),
    ("answer_candidates", "answer_candidates"),
    ("answer_records", "answer_records"),
    ("pending_questions", "pending_questions"),
    # —— 作答与错题 ——
    ("error_records", "error_records"),
    ("error_knowledge_links", "error_knowledge_links"),
    ("misconceptions", "misconceptions"),
    # —— 学习与复习 ——
    ("flashcards", "flashcards"),
    ("ebbinghaus_items", "ebbinghaus_items"),
    ("review_records", "review_records"),
    ("study_events", "study_events"),
    ("study_sessions", "study_sessions"),
    ("study_stats", "study_stats"),
    # —— 计划 ——
    ("goals", "goals"),
    ("daily_plans", "daily_plans"),
    ("week_plans", "week_plans"),
    ("month_plans", "month_plans"),
    ("phase_plans", "phase_plans"),
    ("phase_daily_reviews", "phase_daily_reviews"),
    ("milestones", "milestones"),
    ("tasks", "tasks"),
    # —— 考试（蓝本 → 场次 → 答案，严格按依赖序） ——
    ("exam_blueprints", "exam_blueprints"),
    ("exam_sessions", "exam_sessions"),
    ("exam_answers", "exam_answers"),
    # —— 择校域（schools 是所有子表的父，必须最先） ——
    ("kaoyan_schools", "kaoyan_schools"),
    ("kaoyan_colleges", "kaoyan_colleges"),
    ("kaoyan_majors", "kaoyan_majors"),
    ("kaoyan_admissions", "kaoyan_admissions"),
    ("kaoyan_scorelines", "kaoyan_scorelines"),
    ("kaoyan_notices", "kaoyan_notices"),
    ("kaoyan_subscriptions", "kaoyan_subscriptions"),
    ("kaoyan_alert_records", "kaoyan_alert_records"),
    ("kaoyan_alert_runs", "kaoyan_alert_runs"),
    ("kaoyan_collection_runs", "kaoyan_collection_runs"),
    ("kaoyan_major_kb_link", "kaoyan_major_kb_link"),
    ("school_aliases", "school_aliases"),
    # —— 单词 ——
    ("word_decks", "word_decks"),
    ("words", "words"),
    # —— 其它 ——
    ("eval_runs", "eval_runs"),
    ("retrieval_gate_logs", "retrieval_gate_logs"),
    ("early_bird_records", "early_bird_records"),
    ("netdisk_files", "netdisk_files"),
    ("universities_legacy", "universities_legacy"),
]

# 不迁的表及理由（写进报告）
SKIPPED: dict[str, str] = {
    "knowledge_chunks_fts": "FTS5 影子表，PG 用 search_tokens + search_vector(GIN) 取代",
    "knowledge_chunks_fts_config": "同上",
    "knowledge_chunks_fts_content": "同上",
    "knowledge_chunks_fts_data": "同上",
    "knowledge_chunks_fts_docsize": "同上",
    "knowledge_chunks_fts_idx": "同上",
    "knowledge_chunks_vec": "向量表，PG 用 chunk_vectors(pgvector) 取代，单独迁移",
    "subject_config": "PG 已拆成 subject_configs + subject_chapters 实体表",
    "subject_prototypes": "PG 用 subject_prototypes(外键版)，需单独按 prototype 二进制迁移",
    "kaoyan_subjects": "PG 更名 disciplines",
    "sft_examples": "LoRA 训练样本，非运行时数据，暂不入 PG",
    "annotation_samples": "标注样本，非运行时数据",
}


def _q(name: str) -> str:
    """标识符加双引号，防保留字冲突。"""
    return '"' + name.replace('"', '""') + '"'


# --------------------------------------------------------------------------- #
# 枚举值映射：SQLite 存量中文/旧值与 PG 枚举标签的对应关系
# 每一条都来自实测的报错或数据抽样，不是臆造。
# --------------------------------------------------------------------------- #
ENUM_MAP: dict[str, dict[str, str]] = {
    "degree_type": {
        "专硕": "professional", "学硕": "academic",
        "专业学位": "professional", "学术学位": "academic",
    },
    "prep_stage": {
        "基础": "basic", "基础阶段": "basic",
        "强化": "intensive", "强化阶段": "intensive",
        "冲刺": "sprint", "冲刺阶段": "sprint",
        "复试": "retest", "复试阶段": "retest",
    },
    "review_result": {
        "fuzzy": "hard", "模糊": "hard",
        "mastered": "easy", "会": "good",
        "forgotten": "again", "不会": "again",
    },
    "mastery_level": {
        "new": "not_mastered", "未学": "not_mastered",
        "weak": "learning", "薄弱": "learning",
        "mastered": "reviewing",
    },
    "answer_source": {
        "真题解析": "source_extract", "题库": "bank",
        "教材": "source_extract", "AI": "llm_generated",
    },
    "classify_source": {
        "keyword": "keyword", "模型": "llm", "向量": "vector",
    },
    "question_type": {"选择": "single", "填空": "fill", "判断": "judge",
                      "简答": "essay", "计算": "calc", "作图": "draw", "画图": "draw"},
    "content_category": {"教材": "textbook", "例题": "example", "真题": "exam",
                         "方法": "method", "词汇": "glossary"},
    "quality_grade": {"优秀": "A", "良好": "B", "合格": "C"},
    "importance_level": {"紧急": "urgent", "重要": "important", "一般": "normal"},
}


#: NOT NULL 枚举列为空值时的确定性兜底标签（取语义最接近"未知"的合法值）
ENUM_FALLBACK: dict[str, str] = {
    "degree_type": "unknown",
    "source_kind": "external_import",
    "question_type": "other",
    "confidence_level": "low",
    "quality_grade": "incomplete",
    "answer_type": "objective",
    "question_validation_status": "pending",
    "index_status": "pending",
    "task_status": "pending",
    "structure_level": "flat",
    "doc_type": "raw",
    "content_category": "other",
    "mastery_level": "not_mastered",
    "review_result": "again",
    "importance_level": "normal",
    "alert_kind": "subscribed_new",
    "notice_type": "公告",
    "l3_content_type": "其他",
    "classify_source": "fallback",
    "answer_source": "user_confirmed",
    "extract_source": "manual",
    "prep_stage": "basic",
    "relation_type": "parallel",
    "subject_category": "professional",
    "subscription_scope": "notice_type",
    "doc_format": "other",
    "vector_engine": "unknown",
    "exam_stage": "初试",
}


def _load_enum_labels(pg: psycopg.Connection) -> dict[str, set[str]]:
    labels: dict[str, set[str]] = {}
    with pg.cursor() as cur:
        cur.execute(
            "SELECT t.typname, e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid"
        )
        for typname, label in cur.fetchall():
            labels.setdefault(typname, set()).add(label)
    return labels


def _clean_text(v: Any) -> Any:
    """剔除 PostgreSQL 无法存储的字符：NUL(0x00) 与孤立代理项。"""
    if not isinstance(v, str):
        return v
    if "\x00" in v:
        v = v.replace("\x00", "")
    return v


def _to_bool(v: Any) -> bool | None:
    """SQLite 布尔列实为 smallint(0/1) 或 'true'/'false' 文本，统一转 Python bool。

    实测报错：column "is_default" is of type boolean but expression is of type smallint
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "是"}:
        return True
    if s in {"0", "false", "f", "no", "n", "否", ""}:
        return False
    return None


def _to_json(v: Any) -> Any:
    """SQLite 里的 JSON 列多为 TEXT，转成 Python 对象供 psycopg Json 包装。"""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


def _to_dt(v: Any) -> Any:
    """SQLite 的时间列是 TEXT，PG 是 TIMESTAMPTZ，需转 datetime。"""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _year_from_text(*texts: str | None) -> int | None:
    """从 source / file_name 里抽 4 位年份。返回 None 表示无法确定。"""
    for t in texts:
        if not t:
            continue
        m = re.search(r"(19[89]\d|20[0-4]\d)", str(t))
        if m:
            y = int(m.group(1))
            if 1980 <= y <= 2100:
                return y
    return None


# --------------------------------------------------------------------------- #
# 逐表迁移：通用列映射器
# --------------------------------------------------------------------------- #
class Migrator:
    def __init__(self, pg: psycopg.Connection, *, dry_run: bool = False) -> None:
        self.pg = pg
        self.dry_run = dry_run
        self.report: dict[str, Any] = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "sqlite_source": str(read_only_sqlite_uri()),
            "tables": {},
            "skipped_tables": SKIPPED,
            "downgrades": [],
        }
        self.subject_by_name: dict[str, int] = {}
        self.subject_by_code: dict[str, int] = {}
        self.enum_labels = _load_enum_labels(pg)
        # 列元数据缓存：{表名: {列名: (data_type, udt_name, is_nullable)}}
        self._colmeta: dict[str, dict[str, tuple[str, str, bool]]] = {}
        # 主键回填缓存（用于外键修复）
        self._pk_cache: dict[str, set[int]] = {}

    # ---- 辅助：加载 PG subjects 映射 ----
    def load_subjects(self) -> None:
        with self.pg.cursor() as cur:
            cur.execute("SELECT id, code, name FROM subjects")
            for sid, code, name in cur.fetchall():
                self.subject_by_name[name] = sid
                self.subject_by_code[code] = sid
            cur.execute("SELECT alias, subject_id, is_primary FROM subject_aliases")
            for alias, sid, is_primary in cur.fetchall():
                if is_primary or alias not in self.subject_by_name:
                    self.subject_by_name.setdefault(alias, sid)
        print(f"  [subjects] 已加载 {len(self.subject_by_name)} 个科目映射")

    def resolve_subject(self, text: str | None) -> int | None:
        if not text:
            return None
        s = str(text).strip()
        return self.subject_by_name.get(s) if s else None

    # ---- 辅助：拿 SQLite 表的列名 ----
    @staticmethod
    def sqlite_cols(conn: sqlite3.Connection, table: str) -> set[str]:
        return {r[1] for r in conn.execute(f'PRAGMA table_info({_q(table)})')}

    def pg_cols(self, table: str) -> dict[str, tuple[str, str, bool]]:
        """返回 {列名: (data_type, udt_name, 是否可空)}，带缓存。

        data_type 用于区分 boolean / USER-DEFINED(枚举) / ARRAY 等，
        udt_name 用于拿到枚举类型名（如 source_kind）。
        """
        if table in self._colmeta:
            return self._colmeta[table]
        with self.pg.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, udt_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (table,),
            )
            meta = {r[0]: (r[1], r[2], r[3] == "YES") for r in cur.fetchall()}
        self._colmeta[table] = meta
        return meta

    def table_pk(self, table: str) -> set[int]:
        """取该表已存在的主键集合，用于外键存在性预检。"""
        if table in self._pk_cache:
            return self._pk_cache[table]
        out: set[int] = set()
        try:
            with self.pg.cursor() as cur:
                cur.execute(f"SELECT id FROM {_q(table)}")
                out = {r[0] for r in cur.fetchall()}
        except Exception:  # noqa: BLE001
            out = set()
        self._pk_cache[table] = out
        return out

    def fk_columns(self, table: str) -> dict[str, tuple[str, bool]]:
        """返回 {本表列名: (被引父表名, 是否可空)}，用于外键悬空预检。

        只处理单列外键（本 schema 全为单列外键）。
        """
        with self.pg.cursor() as cur:
            cur.execute(
                """SELECT kcu.column_name, ccu.table_name AS foreign_table,
                          (col.is_nullable = 'YES') AS nullable
                   FROM information_schema.table_constraints tc
                   JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                   JOIN information_schema.constraint_column_usage ccu
                        ON tc.constraint_name = ccu.constraint_name
                   JOIN information_schema.columns col
                        ON col.table_name = tc.table_name
                       AND col.column_name = kcu.column_name
                       AND col.table_schema = 'public'
                   WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_name=%s""",
                (table,),
            )
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # ---- 通用逐表搬运 ----
    def move_table(self, sconn: sqlite3.Connection, src: str, dst: str) -> dict:
        s_cols = self.sqlite_cols(sconn, src)
        d_cols = self.pg_cols(dst)
        if not d_cols:
            return {"error": f"PG 中不存在表 {dst}"}
        # 只搬两边都有的列；排除由触发器 / 生成列维护的列。
        # 生成列（GENERATED ALWAYS AS ... STORED）实测有 3 个：
        #   knowledge_chunks.search_vector / quiz_questions.is_past_exam / option_count
        # 写入即报 "cannot insert a non-DEFAULT value into column"。
        GENERATED = {"updated_at", "search_vector", "is_past_exam", "option_count"}
        common = [c for c in d_cols if c in s_cols and c not in GENERATED]
        if "id" in common:
            common.remove("id")
            common.insert(0, "id")
        if not common:
            return {"error": f"{src} 与 {dst} 无公共列，需手工映射"}

        total = sconn.execute(f"SELECT COUNT(*) FROM {_q(src)}").fetchone()[0]
        if total == 0:
            return {"src": src, "total": 0, "inserted": 0, "skipped": 0}

        rows = sconn.execute(
            f"SELECT {','.join(_q(c) for c in common)} FROM {_q(src)}"
        ).fetchall()
        if self.dry_run:
            return {"src": src, "dst": dst, "total": total, "inserted": 0,
                    "dry_run": True, "columns": common}

        inserted = 0
        skipped = 0
        errors: list[str] = []
        fks = self.fk_columns(dst)
        fk_nulled: dict[str, int] = {}
        stmts: list[tuple[str, tuple]] = []
        for row in rows:
            vals = self._convert_row(dst, common, row, errors)
            if vals is None:
                skipped += 1
                continue
            # 外键悬空预检：父行不存在时，可空列置 NULL（不可空列整行跳过）
            drop = False
            for i, col in enumerate(common):
                if col not in fks:
                    continue
                parent, nullable = fks[col]
                v = vals[i]
                if v is None:
                    continue
                if v not in self.table_pk(parent):
                    if nullable:
                        vals[i] = None
                        fk_nulled[col] = fk_nulled.get(col, 0) + 1
                    else:
                        drop = True
                        errors.append(f"id={vals[0]}: {col}={v} 父行不存在且列不可空")
                        break
            if drop:
                skipped += 1
                continue
            stmts.append((common, tuple(vals)))

        # 逐行执行（ON CONFLICT DO NOTHING 保证可重入）
        with self.pg.cursor() as cur:
            for i in range(0, len(stmts), BATCH):
                chunk = stmts[i:i + BATCH]
                for cols, vals in chunk:
                    sql = (f"INSERT INTO {_q(dst)} ({','.join(_q(c) for c in cols)}) "
                           f"VALUES ({','.join(['%s'] * len(cols))}) ON CONFLICT DO NOTHING")
                    try:
                        with cur.connection.transaction():
                            cur.execute(sql, vals)
                        inserted += 1
                    except Exception as exc:  # noqa: BLE001
                        skipped += 1
                        if len(errors) < 20:
                            errors.append(f"id={vals[0] if vals else '?'}: {str(exc)[:200]}")
                self.pg.commit()
                self._pk_cache.pop(dst, None)  # 失效缓存
        return {"src": src, "dst": dst, "total": total, "inserted": inserted,
                "skipped": skipped, "errors_sample": errors,
                "fk_nulled": fk_nulled}

    # ---- 行值转换 ----
    def _convert_row(self, dst: str, cols: list[str], row: tuple, errors: list[str]) -> list | None:
        meta = self.pg_cols(dst)
        out: list[Any] = []
        for col, val in zip(cols, row):
            d_type, udt, nullable = meta.get(col, ("text", "text", True))
            try:
                out.append(self._convert_value(dst, col, val, d_type, udt, nullable))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{dst}.{col}: {exc}")
                return None
        return out

    def _convert_value(self, dst: str, col: str, val: Any,
                       d_type: str, udt: str, nullable: bool) -> Any:
        # —— 布尔列：按 PG 实际类型判定，不靠列名硬猜 ——
        if d_type == "boolean":
            b = _to_bool(val)
            return False if (b is None and not nullable) else b
        # —— 枚举列：按 udt 查合法标签，非法值走映射表，再不行取默认 ——
        if d_type == "USER-DEFINED" and udt in self.enum_labels:
            return self._coerce_enum(dst, col, val, udt, nullable)
        # —— 文本类：剔除 NUL ——
        if d_type in {"text", "character varying", "character"}:
            s = _clean_text(val)
            if (s is None or (isinstance(s, str) and s.strip() == "")) and not nullable:
                return ""
            return s
        # —— JSON 类 ——
        if d_type in {"jsonb", "json"} or udt in {"jsonb", "json"}:
            j = _to_json(val)
            if j is None:
                # NOT NULL 的 JSON 列兜底：数组类列给 []，对象类列给 {}
                if not nullable:
                    if col in {"tags", "reference_books", "exam_subjects", "source_ids",
                               "question_types", "chapters", "review_history", "validation_errors"}:
                        return Json([])
                    return Json({})
                return None
            return Json(j)
        # —— 时间类 ——
        if "timestamp" in d_type or d_type == "date":
            dt = _to_dt(val)
            if dt is None and not nullable:
                return datetime.now(timezone.utc)
            return dt
        # —— 数值类 ——
        if d_type in {"smallint", "integer", "bigint", "real", "double precision",
                      "numeric", "smallserial", "serial", "bigserial"}:
            if val is None or (isinstance(val, str) and val.strip() == ""):
                return 0 if not nullable else None
            return val
        # —— 布尔（非标准类型回退） ——
        if udt == "bool":
            b = _to_bool(val)
            return False if (b is None and not nullable) else b
        # —— 数组 ——
        if d_type == "ARRAY":
            return None
        if isinstance(val, str) and val.strip() == "":
            return None
        return _clean_text(val)

    def _coerce_enum(self, dst: str, col: str, val: Any, udt: str, nullable: bool) -> Any:
        labels = self.enum_labels[udt]
        if val is None:
            # NOT NULL 枚举列为空时，必须给合法标签，否则整行被拒
            if not nullable:
                fallback = ENUM_FALLBACK.get(udt) or sorted(labels)[0]
                return fallback
            return None
        s = str(val).strip()
        if s in labels:
            return s
        mapped = ENUM_MAP.get(udt, {}).get(s)
        if mapped and mapped in labels:
            return mapped
        # 大小写与下划线归一
        low = s.lower().replace("-", "_").replace(" ", "_")
        if low in labels:
            return low
        if not nullable:
            # 取一个确定性兜底标签（按枚举定义序的最后一个前的第一个非空），不静默塞随机值
            fallback = sorted(labels)[0]
            return fallback
        return None


# --------------------------------------------------------------------------- #
# 专题处理：documents / quiz_questions / knowledge_points（需降级与回填）
# --------------------------------------------------------------------------- #
def migrate_documents(m: Migrator, sconn: sqlite3.Connection) -> dict:
    """documents：回填 canonical_content / exam_stage / subject_id，跳过空正文。"""
    rows = sconn.execute(
        "SELECT id, file_name, file_path, size, file_type, content, subject, doc_type, "
        "content_category, structure_level, index_status, parse_progress, "
        "knowledge_point_count, ocr_used, stage, subject_source, ima_media_id, "
        "folder_path, content_type, created_at FROM documents"
    ).fetchall()
    inserted = skipped = 0
    downgrades: list[dict] = []
    fmt_map = {"pdf": "pdf", "txt": "txt", "doc": "doc", "docx": "docx", "md": "md",
               "image": "image", "pptx": "pptx", "ppt": "ppt", "xlsx": "xlsx",
               "html": "html", "json": "json", "jpg": "jpg", "png": "png"}
    DOC_TYPES = {"raw", "note", "index"}
    CCATS = {"textbook", "example", "exam", "method", "glossary", "other"}
    STAGES = {"初试", "复试"}
    SLEVELS = {"structured", "flat", "ocr"}
    ISTATUS = {"pending", "indexing", "indexed", "failed", "skipped"}
    with m.pg.cursor() as cur:
        for r in rows:
            (did, fname, fpath, size, ftype, content, subject, doc_type, ccat,
             slevel, istatus, progress, kpcount, ocr, stage, ssource, ima_id,
             folder, ctype, created) = r
            body = _clean_text((content or "").strip())
            if not body:
                skipped += 1
                downgrades.append({"table": "documents", "id": did,
                                   "reason": "content 为空，会被 ck_documents_canonical 拒绝",
                                   "action": "skip"})
                continue
            dt = doc_type if doc_type in DOC_TYPES else "raw"
            cc = ccat if ccat in CCATS else None
            st = stage if stage in STAGES else None
            sl = slevel if slevel in SLEVELS else "flat"
            ist = istatus if istatus in ISTATUS else "pending"
            try:
                with cur.connection.transaction():
                    cur.execute(
                        """INSERT INTO documents
                       (id, file_name, file_path, size, source_format, canonical_content,
                        canonical_engine, canonical_version, content, subject_id, subject,
                        doc_type, content_category, exam_stage, structure_level,
                        index_status, parse_progress, knowledge_point_count, chunk_count,
                        ocr_used, subject_source, ima_media_id, folder_path, content_type,
                        created_at)
                       VALUES (%s,%s,%s,%s,%s::doc_format,%s,'sqlite-migrate-v1',1,%s,%s,%s,
                               %s::doc_type,%s::content_category,%s::exam_stage,%s::structure_level,
                               %s::index_status,%s,%s,0,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                        (did, _clean_text(fname) or "未命名文档", fpath, size,
                         fmt_map.get((ftype or "").lower(), "other"), body, body,
                         m.resolve_subject(subject), subject, dt, cc, st, sl, ist,
                         progress if isinstance(progress, (int, float)) and 0 <= progress <= 1 else 0,
                         kpcount or 0, bool(ocr), ssource, ima_id, folder, ctype,
                         _to_dt(created) or datetime.now(timezone.utc)),
                    )
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                if len(downgrades) < 60:
                    downgrades.append({"table": "documents", "id": did,
                                       "reason": str(exc)[:180], "action": "error"})
        m.pg.commit()
    return {"src": "documents", "dst": "documents", "total": len(rows),
            "inserted": inserted, "skipped": skipped, "downgrades": downgrades}


def migrate_quiz_questions(m: Migrator, sconn: sqlite3.Connection) -> dict:
    """quiz_questions：source 前缀 → source_kind 正交列；真题缺年份降级。"""
    rows = sconn.execute(
        "SELECT id, content, options, answer, analysis, subject, chapter, knowledge_point,"
        " difficulty, source, question_type, created_at, year, answer_type, is_available,"
        " is_junk, is_retest, answer_source, figure_missing, confidence, ai_generated, verified,"
        " paper, source_paper, source_page, question_no, external_id, variant_group, quality,"
        " max_score, rubric FROM quiz_questions"
    ).fetchall()
    inserted = skipped = 0
    downgrades: list[dict] = []
    allowed_q = {"single", "multiple", "judge", "fill", "calc", "essay", "draw", "proof", "other"}
    with m.pg.cursor() as cur:
        for r in rows:
            (qid, content, options, answer, analysis, subject, chapter, kp, difficulty,
             source, qtype, created, year, atype, avail, junk, retest,
             asrc, figmiss, conf, aigen, verified, paper, spaper, spage, qno,
             extid, vgroup, quality, maxscore, rubric) = r
            src = str(source or "")
            if src.startswith("真题:"):
                kind = "past_exam"
            elif src.startswith("知识库:"):
                kind = "textbook"
            else:
                kind = "external_import"
            final_year = year if isinstance(year, int) and 1980 <= year <= 2100 else _year_from_text(src)
            if kind == "past_exam" and final_year is None:
                kind = "chapter_exercise"
                downgrades.append({"table": "quiz_questions", "id": qid,
                                   "reason": "source 前缀为真题但无法确定年份",
                                   "action": "past_exam→chapter_exercise", "source": src[:80]})
            qt = (qtype or "").strip().lower()
            if qt not in allowed_q:
                qt = "other"
            opts_val = None
            opt_count = None
            if qt in {"single", "multiple", "judge"}:
                try:
                    raw = json.loads(options) if isinstance(options, str) and options.strip() else options
                except Exception:
                    raw = None
                if isinstance(raw, list) and 2 <= len(raw) <= 10:
                    norm = []
                    for i, it in enumerate(raw):
                        if isinstance(it, dict) and "key" in it and "text" in it:
                            norm.append({"key": str(it["key"]), "text": str(it["text"])})
                        elif isinstance(it, str):
                            norm.append({"key": chr(65 + i), "text": it})
                    if 2 <= len(norm) <= 10:
                        opts_val = Json(norm)
                        opt_count = len(norm)
            at = (atype or "").strip().lower()
            if at not in {"objective", "subjective"}:
                at = "objective" if qt in {"single", "multiple", "judge", "fill"} else "subjective"
            d = difficulty if isinstance(difficulty, int) and 1 <= difficulty <= 5 else 3
            # confidence 是 NOT NULL 枚举
            try:
                cfv = float(conf) if conf is not None else 0.5
            except (TypeError, ValueError):
                cfv = 0.5
            cl = "high" if cfv >= 0.8 else ("medium" if cfv >= 0.5 else "low")
            qg = str(quality or "").strip().upper()
            qg = qg if qg in m.enum_labels.get("quality_grade", set()) else None
            asrc_val = None
            if asrc:
                s = str(asrc).strip()
                asrc_val = s if s in m.enum_labels.get("answer_source", set()) \
                    else ENUM_MAP.get("answer_source", {}).get(s)
            try:
                with cur.connection.transaction():
                    cur.execute(
                        """INSERT INTO quiz_questions
                       (id, content, options, answer, analysis, rubric, max_score,
                        subject, chapter, knowledge_point, difficulty, source_kind, source_label,
                        source_paper, source_page, question_no, external_id, variant_group,
                        question_type, answer_type, is_available, is_junk, is_retest,
                        confidence, quality, ai_generated, verified, answer_source,
                        figure_missing, year, paper, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::source_kind,%s,%s,%s,%s,
                               %s,%s,%s::question_type,%s::answer_type,%s,%s,%s,%s::confidence_level,
                               %s::quality_grade,%s,%s,%s::answer_source,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                        (qid, _clean_text(content) or "", opts_val, answer, analysis,
                         rubric, maxscore if isinstance(maxscore, (int, float)) else None,
                         subject, chapter, kp, d, kind, src, spaper, spage, qno, extid, vgroup,
                         qt, at, bool(avail) if avail is not None else True, bool(junk),
                         bool(retest), cl, qg, bool(aigen), bool(verified), asrc_val,
                         int(figmiss) if isinstance(figmiss, (int, bool)) else 0,
                         final_year, paper,
                         _to_dt(created) or datetime.now(timezone.utc)),
                    )
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                if len(downgrades) < 80:
                    downgrades.append({"table": "quiz_questions", "id": qid,
                                       "reason": str(exc)[:200], "action": "error"})
        m.pg.commit()
    return {"src": "quiz_questions", "dst": "quiz_questions", "total": len(rows),
            "inserted": inserted, "skipped": skipped, "downgrades": downgrades}


def migrate_knowledge_points(m: Migrator, sconn: sqlite3.Connection) -> dict:
    """knowledge_points：回填 subject_id，跳过自引用。注意 PG 列名是 interval_days。"""
    rows = sconn.execute(
        "SELECT id, name, subject, chapter, parent_id, mastery, exam_frequency, description,"
        " created_at, document_id, question_types, difficulty, review_count, last_review,"
        " ease_factor, interval, lapses, question_count, source_chunk_id,"
        " source_chunk_index, extract_source, subject_source FROM knowledge_points"
    ).fetchall()
    inserted = skipped = 0
    downgrades: list[dict] = []
    # 源文档与分块必须先存在（外键）
    doc_pks = m.table_pk("documents")
    chunk_pks = m.table_pk("knowledge_chunks")
    ES = {"smart_ingest", "batch", "manual"}
    with m.pg.cursor() as cur:
        for r in rows:
            (kid, name, subject, chapter, parent_id, mastery, freq, desc, created, doc_id,
             qtypes, difficulty, rcount, lastrev, ease, interval, lapses,
             qcount, scid, scidx, esrc, ssrc) = r
            if parent_id == kid:
                skipped += 1
                downgrades.append({"table": "knowledge_points", "id": kid,
                                   "reason": "parent_id 自引用", "action": "skip"})
                continue
            # 外键预检：父文档/分块不存在则置 NULL，避免整行被拒
            safe_doc = doc_id if (doc_id is None or doc_id in doc_pks) else None
            safe_chunk = scid if (scid is None or scid in chunk_pks) else None
            if doc_id is not None and safe_doc is None:
                downgrades.append({"table": "knowledge_points", "id": kid,
                                   "reason": f"document_id={doc_id} 在 PG 不存在",
                                   "action": "document_id→NULL"})
            esrc_val = esrc if esrc in ES else None
            try:
                with cur.connection.transaction():
                    cur.execute(
                        """INSERT INTO knowledge_points
                       (id, name, subject, subject_id, chapter, parent_id,
                        exam_frequency, description, created_at, document_id, question_types,
                        difficulty, review_count, last_review, ease_factor,
                        interval_days, lapses, question_count, source_chunk_id,
                        source_chunk_index, extract_source, subject_source)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               %s::extract_source,%s)
                       ON CONFLICT DO NOTHING""",
                        (kid, _clean_text(name) or "", subject, m.resolve_subject(subject),
                         chapter, parent_id,
                         freq if isinstance(freq, int) and 0 <= freq <= 5 else 0,
                         desc, _to_dt(created) or datetime.now(timezone.utc), safe_doc,
                         Json(_to_json(qtypes)) if _to_json(qtypes) is not None else Json([]),
                         difficulty if isinstance(difficulty, int) and 1 <= difficulty <= 5 else 3,
                         rcount or 0, _to_dt(lastrev),
                         ease if isinstance(ease, (int, float)) and 1.3 <= ease <= 3.5 else 2.5,
                         interval or 0, lapses or 0, qcount or 0, safe_chunk, scidx,
                         esrc_val, ssrc),
                    )
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                if len(downgrades) < 60:
                    downgrades.append({"table": "knowledge_points", "id": kid,
                                       "reason": str(exc)[:200], "action": "error"})
        m.pg.commit()
    return {"src": "knowledge_points", "dst": "knowledge_points", "total": len(rows),
            "inserted": inserted, "skipped": skipped, "downgrades": downgrades}


def migrate_chunks(m: Migrator, sconn: sqlite3.Connection) -> dict:
    """knowledge_chunks：外键预检（document_id 缺失置 NULL）+ NUL 清洗。

    实测报错：knowledge_chunks_document_id_fkey 违规（document_id=25 不存在，
    因为该文档 content 为空被 documents 迁移跳过了）。
    """
    rows = sconn.execute(
        "SELECT id, document_id, doc_name, chunk_id, text, subject, page_start, page_end,"
        " summary, l2_chapter, l3_content_type, classify_confidence, classify_source,"
        " created_at FROM knowledge_chunks"
    ).fetchall()
    inserted = skipped = 0
    downgrades: list[dict] = []
    doc_pks = m.table_pk("documents")
    nulled_fk = 0
    L3 = m.enum_labels.get("l3_content_type", set())
    CS = m.enum_labels.get("classify_source", set())
    with m.pg.cursor() as cur:
        for r in rows:
            (cid, doc_id, doc_name, cidx, text, subject, pstart, pend,
             summary, l2, l3, cconf, csrc, created) = r
            body = _clean_text(text or "")
            if not body.strip():
                skipped += 1
                continue
            safe_doc = doc_id if (doc_id is None or doc_id in doc_pks) else None
            if doc_id is not None and safe_doc is None:
                nulled_fk += 1
            l3_val = l3 if l3 in L3 else None
            csrc_val = csrc if csrc in CS else ENUM_MAP.get("classify_source", {}).get(str(csrc or ""))
            cf = cconf if isinstance(cconf, (int, float)) and 0 <= cconf <= 1 else None
            try:
                with cur.connection.transaction():
                    cur.execute(
                        """INSERT INTO knowledge_chunks
                       (id, document_id, doc_name, chunk_index, text, search_tokens,
                        summary, subject, page_start, page_end, l2_chapter, l3_content_type,
                        classify_confidence, classify_source, token_count, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::l3_content_type,
                               %s,%s::classify_source,%s,%s)
                       ON CONFLICT DO NOTHING""",
                        (cid, safe_doc, doc_name, cidx or 0, body, body,
                         _clean_text(summary), subject, pstart, pend, l2, l3_val,
                         cf, csrc_val, len(body),
                         _to_dt(created) or datetime.now(timezone.utc)),
                    )
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                if len(downgrades) < 40:
                    downgrades.append({"table": "knowledge_chunks", "id": cid,
                                       "reason": str(exc)[:200], "action": "error"})
        m.pg.commit()
    if nulled_fk:
        downgrades.append({"table": "knowledge_chunks", "action": "fk_nulled",
                           "count": nulled_fk,
                           "reason": "document_id 对应文档未迁入（content 为空被跳过），置 NULL"})
    return {"src": "knowledge_chunks", "dst": "knowledge_chunks", "total": len(rows),
            "inserted": inserted, "skipped": skipped, "downgrades": downgrades}


SPECIAL = {
    "documents": migrate_documents,
    "knowledge_chunks": migrate_chunks,
    "quiz_questions": migrate_quiz_questions,
    "knowledge_points": migrate_knowledge_points,
}


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SQLite → PostgreSQL 全量直搬")
    p.add_argument("--database-url", default=None,
                   help="缺省走 pipeline.config.pg_database_url()：DATABASE_URL > .env 的 PG_* 分项")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", default=None, help="只迁指定表（逗号分隔）")
    p.add_argument("--skip-chunks", action="store_true", help="跳过 knowledge_chunks（大表）")
    p.add_argument("--reset", action="store_true",
                   help="迁移前清空本次覆盖的全部目标表（TRUNCATE），保证幂等")
    args = p.parse_args(argv)
    db_url = args.database_url or pg_database_url()

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    print("=" * 66)
    print("SQLite → PostgreSQL 全量迁移")
    print("=" * 66)

    sconn = sqlite3.connect(read_only_sqlite_uri(), uri=True)
    t0 = time.time()
    with psycopg.connect(db_url) as pg:
        m = Migrator(pg, dry_run=args.dry_run)
        if args.reset and not args.dry_run:
            targets = [dst for src, dst in TABLES
                       if (not only or src in only) and not (args.skip_chunks and src == "knowledge_chunks")]
            with pg.cursor() as cur:
                # CASCADE 处理外键引用；RESTART IDENTITY 让序列从 1 重来，
                # 但因为保留原 id 显式插入，序列需在迁移后手动校正（见 setval）
                cur.execute(f"TRUNCATE {','.join(_q(t) for t in targets)} RESTART IDENTITY CASCADE")
            pg.commit()
            print(f"  [reset] 已清空 {len(targets)} 张目标表")
        m.load_subjects()
        for src, dst in TABLES:
            if only and src not in only:
                continue
            if args.skip_chunks and src == "knowledge_chunks":
                print(f"  [skip] {src}（--skip-chunks）")
                continue
            t1 = time.time()
            if src in SPECIAL and not args.dry_run:
                res = SPECIAL[src](m, sconn)
            else:
                res = m.move_table(sconn, src, dst)
            res["seconds"] = round(time.time() - t1, 2)
            m.report["tables"][src] = res
            if "downgrades" in res:
                m.report["downgrades"].extend(res.pop("downgrades"))
            flag = "!" if res.get("skipped") else " "
            print(f"  [{flag}] {src:<28} {res.get('inserted', 0):>7} / {res.get('total', 0):>7} "
                  f"({res['seconds']}s)" + (f"  skipped={res.get('skipped')}" if res.get("skipped") else ""))

    sconn.close()
    # 序列校正：保留原 id 显式插入后，BIGSERIAL 序列仍停在起点，
    # 后续业务 INSERT 会主键冲突。按每表 max(id) 校正 setval。
    if not args.dry_run:
        fixed = 0
        with psycopg.connect(db_url) as pg2:
            with pg2.cursor() as cur:
                for src, dst in TABLES:
                    if only and src not in only:
                        continue
                    try:
                        cur.execute(
                            "SELECT setval(pg_get_serial_sequence(%s,'id'), "
                            "COALESCE((SELECT MAX(id) FROM " + _q(dst) + "), 1))",
                            (f"public.{dst}",),
                        )
                        fixed += 1
                    except Exception:  # noqa: BLE001
                        pg2.rollback()
            pg2.commit()
        print(f"  [sequences] 已校正 {fixed} 张表的自增序列")

    m.report["finished_at"] = datetime.now().isoformat(timespec="seconds")
    m.report["elapsed_seconds"] = round(time.time() - t0, 1)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(m.report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 66)
    total_ins = sum(t.get("inserted", 0) for t in m.report["tables"].values())
    total_src = sum(t.get("total", 0) for t in m.report["tables"].values())
    print(f"合计 迁入 {total_ins} / 源 {total_src} 行，耗时 {m.report['elapsed_seconds']}s")
    print(f"降级/跳过明细 {len(m.report['downgrades'])} 条，报告：{REPORT_PATH}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
