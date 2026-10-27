# -*- coding: utf-8 -*-
"""数据地基（V12 · P0）：答案置信度体系 / 薄弱知识点聚合 / 题库包导入+QC / 学习快照导出。

对标 408-ai-tutor 的数据设计（wrong_questions / misconceptions / weak_knowledge
+ QC 报告 + 答案候选置信度），收敛为四个能力：

1. ``ensure_qa_schema``        幂等 DDL：quiz_questions 增列（answer_source /
   answer_confidence）、weak_knowledge 表、answer_review_queue 人工确认队列。
2. ``import_qbank``            公共课真题题库包导入器：JSON → quiz_questions +
   papers（每科每年一卷，根治 papers 0 条）→ QC 报告（缺选项/缺答案/OCR 噪声）。
   容错解析常见键名（question/stem/title、options/choices、answer/key…）。
3. ``refresh_weak_knowledge``  按知识点聚合错题与作答流水 → weak_knowledge 表，
   支撑「哪里弱补哪里」（智能组卷 weak 模式可直接读此表）。
4. ``export_snapshot``         学习快照 JSON（错题/薄弱点/误区），供桌面 Agent
   （MCP 思路）直读，自动生成周复盘。

置信度分级约定（answer_source）：
    bank            题库内置，置信 1.0 —— 参与自动判分
    source_extract  来源提取（真题册/OCR），置信 0.85 —— 参与自动判分
    llm_generated   LLM 生成，置信 0.55 —— 仅参考展示，不入自动判分
    user_confirmed  用户人工确认，置信 1.0 —— 参与自动判分
103 条交叉校验冲突走 answer_review_queue 人工确认，不再自动消解。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from utils.timeutil import iso_utc_z, local_today, utcnow  # 写库时间统一 naive UTC（P1-C2）
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text as _text
from sqlalchemy.orm import Session

from services.dbapi_compat import insert_returning_id, wrap_conn
from models import ErrorRecord, Paper, PaperQuestion, QuizQuestion, StudyEvent

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 置信度常量
# --------------------------------------------------------------------------- #
SOURCE_CONFIDENCE = {
    "bank": 1.0,
    "source_extract": 0.85,
    "llm_generated": 0.55,
    "user_confirmed": 1.0,
}
AUTO_GRADE_MIN_CONFIDENCE = 0.8  # 低于此值的答案不参与自动判分（仅展示）

_QA_DDL = [
    "ALTER TABLE quiz_questions ADD COLUMN answer_source TEXT DEFAULT 'bank'",
    "ALTER TABLE quiz_questions ADD COLUMN answer_confidence REAL DEFAULT 1.0",
    """
    CREATE TABLE IF NOT EXISTS weak_knowledge (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        knowledge_point TEXT NOT NULL,
        subject TEXT,
        wrong_count INTEGER DEFAULT 0,
        total_count INTEGER DEFAULT 0,
        accuracy REAL,
        mastery REAL,
        last_wrong_at TEXT,
        updated_at TEXT,
        UNIQUE(knowledge_point, subject)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS answer_review_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER,
        conflict_type TEXT,
        detail TEXT,
        status TEXT DEFAULT 'pending',
        resolution TEXT,
        created_at TEXT,
        UNIQUE(question_id, conflict_type)
    )
    """,
]


def ensure_qa_schema(db: Session) -> None:
    """幂等建列/建表（ALTER 失败=列已存在，忽略）。

    PG 关键差异（2026-10-15 实测）：ALTER 失败会把**整个事务打成 aborted**，
    后续同事务的一切命令都被拒 —— SQLite 只报错不传染。因此每条 DDL 必须
    包在 SAVEPOINT 里，失败只回滚到存档点，不污染外层事务。
    """
    conn = wrap_conn(db.connection().connection)
    for ddl in _QA_DDL:
        conn.execute("SAVEPOINT qa_ddl_guard")
        try:
            conn.execute(ddl if isinstance(ddl, str) else _text(ddl))
            conn.execute("RELEASE SAVEPOINT qa_ddl_guard")
        except Exception as exc:  # noqa: BLE001
            conn.execute("ROLLBACK TO SAVEPOINT qa_ddl_guard")
            # 不静默：建表/加列失败必须留痕。历史上这里 `pass` 吞掉 PG 上的
            # DDL 失败，导致 weak_knowledge / answer_review_queue 表**从未建出**，
            # 症状漂移到"弱项统计 500"，排查成本极高（项目血泪教训 #1）。
            # 权威 DDL 已收进 core/sql/098_runtime_tables.sql，此处只是兜底。
            import logging

            logging.getLogger(__name__).warning(
                "qa_foundation 懒建 DDL 未生效（多半已存在，由 098 分片负责）: %s",
                str(exc)[:160],
            )
    conn.commit()


# --------------------------------------------------------------------------- #
# 题库包导入（公共课真题归位）
# --------------------------------------------------------------------------- #
_Q = ["question", "stem", "title", "content", "题干", "题目"]
_O = ["options", "choices", "选项"]
_A = ["answer", "key", "correct", "正确答案", "答案"]
_AN = ["analysis", "explanation", "解析", "answer_analysis"]
_Y = ["year", "年份"]
_N = ["question_no", "no", "number", "题号"]
_TYPE = ["question_type", "type", "题型"]

# OCR 噪声特征：控制字符/私用区/乱码占比
_NOISE_RE = re.compile(r"[\ufffd\u2028\u2029\x00-\x08]")


def _first(d: Dict, keys: List[str], default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _norm_options(raw) -> Optional[Dict]:
    """选项归一化为 {A: ...} 字典；无法解析返回 None（QC 记缺选项）。"""
    if isinstance(raw, dict):
        return {str(k).upper()[:1]: str(v) for k, v in raw.items() if v not in (None, "")}
    if isinstance(raw, list) and raw:
        return {chr(65 + i): str(v) for i, v in enumerate(raw) if v not in (None, "")}
    if isinstance(raw, str) and raw.strip():
        parts = re.split(r"[A-D][.、．)]\s*", "\n" + raw)
        labels = re.findall(r"([A-D])[.、．)]", "\n" + raw)
        if len(labels) >= 2:
            return {lab: parts[i + 1].strip().split("\n")[0]
                    for i, lab in enumerate(labels) if i + 1 < len(parts)}
    return None


def import_qbank(db: Session, payload: Dict, subject: Optional[str] = None,
                 dry_run: bool = False) -> Dict:
    """导入题库包 JSON → quiz_questions + papers + QC 报告。

    payload 兼容三种形态：题目列表 / {"questions": [...]} / 分科 {"科目": [...]}。
    """
    ensure_qa_schema(db)
    items: List[Dict] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("questions"), list):
            items = payload["questions"]
        else:
            for k, v in payload.items():
                if isinstance(v, list):
                    items.extend({**q, "subject": q.get("subject", k)} for q in v if isinstance(q, dict))
    if not items:
        return {"total": 0, "imported": 0, "skipped_dup": 0, "qc": {"error": "未识别到题目列表"}}

    conn = wrap_conn(db.connection().connection)
    qc = {"total": len(items), "imported": 0, "would_import": 0, "skipped_dup": 0,
          "missing_options": 0, "missing_answer": 0, "ocr_noise": 0,
          "papers_created": 0}
    paper_cache: Dict[str, int] = {}
    imported_questions: List[Dict] = []

    for it in items:
        content = str(_first(it, _Q, "") or "").strip()
        if not content:
            continue  # 无题干的条目直接跳过（QC 总数已含）
        subj = subject or _first(it, ["subject", "科目"], "未分类")
        year = _first(it, _Y)
        try:
            year = int(year) if year else None
        except (TypeError, ValueError):
            year = None
        options = _norm_options(_first(it, _O))
        answer = _first(it, _A)
        answer = str(answer).strip().upper()[:1] if answer else None
        if options is None or len(options) < 2:
            qc["missing_options"] += 1
        if not answer:
            qc["missing_answer"] += 1
        noise_chars = len(_NOISE_RE.findall(content))
        if noise_chars >= 2 or (len(content) > 20 and noise_chars / len(content) > 0.02):
            qc["ocr_noise"] += 1
        # 置信度：缺答案或 OCR 噪声 → 降为 llm_generated 档以下并进人工队列
        if answer and not qc_noise_flag(noise_chars, content):
            src, conf = "source_extract", SOURCE_CONFIDENCE["source_extract"]
        else:
            src, conf = "llm_generated", SOURCE_CONFIDENCE["llm_generated"]

        if dry_run:
            qc["would_import"] += 1
            continue

        # 去重：同科目同题干（前 120 字符）已存在则跳过
        dup = conn.execute(
            "SELECT id FROM quiz_questions WHERE subject=? AND substr(content,1,120)=? LIMIT 1",
            (subj, content[:120]),
        ).fetchone()
        if dup:
            qc["skipped_dup"] += 1
            continue
        # question_type 是 DB 枚举（single/multiple/judge/fill/calc/essay/draw/proof/other）；
        # 'objective' 是 answer_type 词表，误填会 500（InvalidTextRepresentation）。
        raw_qt = (_first(it, _TYPE, "") or "").strip().lower()
        qt = {"": "single", "单选": "single", "多选": "multiple", "判断": "judge",
              "填空": "fill", "解答": "calc", "计算": "calc", "简答": "essay",
              "objective": "single", "choice": "single", "multi_choice": "multiple",
              "blank": "fill", "solve": "calc"}.get(raw_qt, raw_qt)
        if qt not in {"single", "multiple", "judge", "fill", "calc", "essay",
                      "draw", "proof", "other"}:
            qt = "single"
        # options 走裸 DBAPI 写入，不过 ORM 的 NullSafeJSON 规整：dict 形态
        # （{"A": "..."}）必须在这里转成正典数组 [{key,text}]，否则 PG 触发器
        # jsonb_array_elements 报 non-array（实测）。
        opts_json = options
        if isinstance(opts_json, dict) and opts_json:
            opts_json = [
                {"key": str(k).strip().upper()[:1], "text": str(v)}
                for k, v in opts_json.items() if str(v).strip()
            ]
        # PG 无 lastrowid：统一走 insert_returning_id（PG 注入 RETURNING id）
        qid = insert_returning_id(
            conn,
            "INSERT INTO quiz_questions (content, options, answer, analysis, subject, "
            "question_type, year, answer_source, answer_confidence, is_available) "
            "VALUES (?,?,?,?,?,?,?,?,?,TRUE)",
            (content, json.dumps(opts_json, ensure_ascii=False) if opts_json else None,
             answer, _first(it, _AN), subj,
             qt, year, src, conf),
        )
        qc["imported"] += 1
        imported_questions.append({"id": qid, "subject": subj, "year": year, "content": content})

        # 每科每年一卷（根治 papers 0 条）
        if year:
            pkey = f"{subj}-{year}"
            if pkey not in paper_cache:
                ptitle = f"{subj} 真题 {year}（题库包导入）"
                paper_cache[pkey] = insert_returning_id(
                    conn,
                    "INSERT INTO papers (title, subject, description, total_score) VALUES (?,?,?,?)",
                    (ptitle, subj, f"来源：题库包导入 · {local_today().isoformat()}", 100),
                )
                qc["papers_created"] += 1
            seq = conn.execute(
                "SELECT COUNT(*) FROM paper_questions WHERE paper_id=?",
                (paper_cache[pkey],),
            ).fetchone()[0] + 1
            conn.execute(
                "INSERT INTO paper_questions (paper_id, question_id, seq, content, options) "
                "VALUES (?,?,?,?,?)",
                (paper_cache[pkey], qid, seq, content,
                 json.dumps(opts_json, ensure_ascii=False) if opts_json else None),
            )

        if src == "llm_generated":
            conn.execute(
                "INSERT OR IGNORE INTO answer_review_queue (question_id, conflict_type, detail, status, created_at) "
                "VALUES (?,?,?,?,?)",
                (qid, "low_confidence", json.dumps({"reason": "missing_answer_or_noise"}, ensure_ascii=False),
                 "pending", utcnow().isoformat()),
            )

    if not dry_run:
        conn.commit()
    return qc


def qc_noise_flag(noise_chars: int, content: str) -> bool:
    return noise_chars >= 2 or (len(content) > 20 and noise_chars / len(content) > 0.02)


# --------------------------------------------------------------------------- #
# 答疑「题库确定性答案优先」（云端方案第三步①，2026-10-18）
# --------------------------------------------------------------------------- #
#: 允许直接展示的高置信答案来源（与 SOURCE_CONFIDENCE 对齐；llm_generated 不在内）
BANK_ANSWER_SOURCES = ("bank", "source_extract", "user_confirmed")
#: 题干命中句的最短归一长度：低于此值的子串匹配误报率不可接受
BANK_MIN_SENT = 10
#: 最多尝试的候选句数（控制 LIKE 扫描成本）
BANK_MAX_CANDS = 5


def _bank_norm(s: str) -> str:
    """匹配归一化：去所有空白 + 统一常见全角引号。与 SQL 侧 regexp_replace 口径一致。"""
    s = re.sub(r"\s+", "", (s or ""))
    return s.replace("\u201c", "\"").replace("\u201d", "\"").replace("\u2018", "'").replace("\u2019", "'")


def find_bank_answer(db: Session, query: str) -> Optional[Dict]:
    """答疑「先查题库」：用户问题命中题库题干（句级逐字）时返回确定性答案。

    命中标准（宁缺勿滥）：
      * 答案来源必须是高置信（bank / source_extract / user_confirmed），
        llm_generated 不直接展示；answer_confidence < AUTO_GRADE_MIN_CONFIDENCE 不展示；
      * 用户问题中至少一个 ≥10 字的连续句段在题干中逐字出现（空白归一后）。

    Returns: dict(id/content/options/answer/analysis/subject/question_type/
              answer_source/answer_confidence/year/source_label/matched) 或 None
    """
    q = (query or "").strip()
    if len(q) < BANK_MIN_SENT:
        return None

    # 候选句：按标点/换行切块，取 ≥10 字的块；整段问题（限长）也作为候选兜底
    raw_parts = re.split(r"[。；;！!？?\n\r\t，,、（）()【】\[\]\"“”‘’]+", q)
    cands = [c for c in (_bank_norm(x) for x in raw_parts) if len(c) >= BANK_MIN_SENT]
    whole = _bank_norm(q)
    if len(whole) <= 120:
        cands.append(whole)
    cands = sorted(dict.fromkeys(cands), key=len, reverse=True)[:BANK_MAX_CANDS]
    if not cands:
        return None

    is_pg = bool(db.bind is not None and getattr(db.bind, "dialect", None) is not None
                 and db.bind.dialect.name == "postgresql")
    for pat in cands:
        esc = pat.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        content_expr = (
            func.regexp_replace(QuizQuestion.content, r"\s+", "", "g")
            if is_pg
            else func.replace(QuizQuestion.content, " ", "")
        )
        try:
            rows = (
                db.query(
                    QuizQuestion.id, QuizQuestion.content, QuizQuestion.options,
                    QuizQuestion.answer, QuizQuestion.analysis, QuizQuestion.subject,
                    QuizQuestion.question_type, QuizQuestion.answer_source,
                    QuizQuestion.answer_confidence, QuizQuestion.year,
                    QuizQuestion.source_label,
                )
                .filter(
                    QuizQuestion.is_available.is_(True),
                    QuizQuestion.is_junk.is_(False),
                    QuizQuestion.answer.isnot(None),
                    QuizQuestion.answer != "",
                    QuizQuestion.answer_source.in_(BANK_ANSWER_SOURCES),
                    content_expr.like(f"%{esc}%", escape="\\"),
                )
                .limit(3)
                .all()
            )
        except Exception as e:
            logger.warning("find_bank_answer 查询失败（pat len=%d）: %s", len(pat), e)
            try:
                db.rollback()
            except Exception:
                pass
            return None
        for r in rows:
            conf = r[8]
            if conf is not None and conf < AUTO_GRADE_MIN_CONFIDENCE:
                continue
            if pat not in _bank_norm(r[1] or ""):
                continue  # LIKE/转义层的兑底复核
            return {
                "id": r[0], "content": r[1],
                "options": r[2] if isinstance(r[2], dict) else None,
                "answer": r[3], "analysis": r[4], "subject": r[5],
                "question_type": str(r[6] or ""), "answer_source": str(r[7] or ""),
                "answer_confidence": conf, "year": r[9], "source_label": r[10],
                "matched": pat,
            }
    return None


# --------------------------------------------------------------------------- #
# 薄弱知识点聚合
# --------------------------------------------------------------------------- #
def refresh_weak_knowledge(db: Session) -> Dict:
    """聚合 ErrorRecord + StudyEvent → weak_knowledge（按知识点×科目）。"""
    ensure_qa_schema(db)
    agg: Dict[tuple, Dict] = {}

    rows = db.query(ErrorRecord).filter(ErrorRecord.status == "active").all()
    for e in rows:
        q = e.question
        kp = (q.knowledge_point if q else None) or "未归类"
        key = (kp, e.subject or "未分类")
        d = agg.setdefault(key, {"wrong": 0, "total": 0, "last": None})
        d["wrong"] += 1
        d["total"] += 1
        if e.created_at and (not d["last"] or e.created_at > d["last"]):
            d["last"] = e.created_at

    rows2 = (
        db.query(QuizQuestion.knowledge_point, StudyEvent.subject, StudyEvent.is_correct)
        .join(StudyEvent, StudyEvent.question_id == QuizQuestion.id)
        .filter(QuizQuestion.knowledge_point.isnot(None))
        .all()
    )
    for kp, subj, ok in rows2:
        key = (kp, subj or "未分类")
        d = agg.setdefault(key, {"wrong": 0, "total": 0, "last": None})
        d["total"] += 1
        if ok is False:
            d["wrong"] += 1

    conn = wrap_conn(db.connection().connection)
    now = utcnow().isoformat()
    for (kp, subj), d in agg.items():
        if d["total"] < 1:
            continue
        acc = 1 - d["wrong"] / d["total"]
        mastery = max(0.0, min(1.0, acc * 0.7 + (1 - min(1.0, d["wrong"] / 5)) * 0.3))
        conn.execute(
            "INSERT INTO weak_knowledge (knowledge_point, subject, wrong_count, total_count, "
            "accuracy, mastery, last_wrong_at, updated_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(knowledge_point, subject) DO UPDATE SET wrong_count=excluded.wrong_count, "
            "total_count=excluded.total_count, accuracy=excluded.accuracy, mastery=excluded.mastery, "
            "last_wrong_at=excluded.last_wrong_at, updated_at=excluded.updated_at",
            (kp, subj, d["wrong"], d["total"], round(acc, 3), round(mastery, 3),
             d["last"].isoformat() if d["last"] else None, now),
        )
    conn.commit()
    return {"aggregated": len(agg), "updated_at": now}


def list_weak_knowledge(db: Session, subject: Optional[str] = None,
                        limit: int = 50) -> List[Dict]:
    ensure_qa_schema(db)
    conn = wrap_conn(db.connection().connection)
    sql = ("SELECT knowledge_point, subject, wrong_count, total_count, accuracy, mastery, "
           "last_wrong_at FROM weak_knowledge")
    args: list = []
    if subject:
        sql += " WHERE subject = ?"
        args.append(subject)
    sql += " ORDER BY mastery ASC, wrong_count DESC LIMIT ?"
    args.append(limit)
    cols = ["knowledge_point", "subject", "wrong_count", "total_count", "accuracy", "mastery", "last_wrong_at"]
    return [dict(zip(cols, r)) for r in conn.execute(sql, args).fetchall()]


# --------------------------------------------------------------------------- #
# 人工确认队列（103 冲突根治）
# --------------------------------------------------------------------------- #
def review_queue(db: Session, status: str = "pending", limit: int = 100) -> List[Dict]:
    ensure_qa_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT id, question_id, conflict_type, detail, status, resolution, created_at "
        "FROM answer_review_queue WHERE status=? ORDER BY id LIMIT ?",
        (status, limit),
    ).fetchall()
    return [
        {"id": r[0], "question_id": r[1], "conflict_type": r[2],
         "detail": json.loads(r[3]) if r[3] else None, "status": r[4],
         "resolution": r[5], "created_at": r[6]}
        for r in rows
    ]


def resolve_review(db: Session, queue_id: int, action: str,
                   resolution: Optional[str] = None) -> bool:
    """action: confirm（采纳当前答案）/ reject（下线该答案，仅保留题干预览）。"""
    if action not in ("confirm", "reject"):
        return False
    ensure_qa_schema(db)
    conn = wrap_conn(db.connection().connection)
    row = conn.execute(
        "SELECT question_id FROM answer_review_queue WHERE id=?", (queue_id,)
    ).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE answer_review_queue SET status=?, resolution=? WHERE id=?",
        ("confirmed" if action == "confirm" else "rejected", resolution or "", queue_id),
    )
    if action == "confirm":
        # 采纳人工答案（resolution 即确认后的正确答案），置信度提为 1.0
        conn.execute(
            "UPDATE quiz_questions SET answer=COALESCE(?, answer), "
            "answer_source='user_confirmed', answer_confidence=1.0 WHERE id=?",
            (resolution, row[0]),
        )
    else:
        conn.execute(
            "UPDATE quiz_questions SET answer=NULL, answer_source='llm_generated', "
            "answer_confidence=0.0 WHERE id=?",
            (row[0],),
        )
    conn.commit()
    return True


# --------------------------------------------------------------------------- #
# 学习快照导出（供桌面 Agent / MCP 直读）
# --------------------------------------------------------------------------- #
def export_snapshot(db: Session) -> Dict:
    weak = list_weak_knowledge(db, limit=30)
    errors = db.query(ErrorRecord).filter(ErrorRecord.status == "active").limit(50).all()
    return {
        "generated_at": iso_utc_z(utcnow()),
        "weak_knowledge": weak,
        "recent_errors": [
            {"id": e.id, "subject": e.subject, "content": (e.content or "")[:120],
             "error_reason": e.error_reason, "review_count": e.review_count,
             "next_review": e.next_review.isoformat() if e.next_review else None}
            for e in errors
        ],
    }
