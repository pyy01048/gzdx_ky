# -*- coding: utf-8 -*-
"""答案置信度与冲突复核服务（V13 · 规格 §1）。

职责（与 answer_cross_check.py 的分工）：
- cross_check：多源收集 / 清洗 / 一致性打分 / 置信度计算（保留既有修复，禁止回退）
- 本服务：**冲突持久化与人工复核闭环** —— verify 检出的冲突写入
  conflict_review_queue（open 状态全局唯一 = 幂等），resolve/reject 时
  对 answer_candidates 候选做降权（×0.8 / ×0.7，下限 0.1）。

数据字典严格按规格 §1.1：conflict_review_queue 含 answer_a/b、source_a/b、
confidence_a/b、suggested_winner、status(open/resolved/rejected)、resolution、
reviewer_note、reviewed_at；幂等索引 UNIQUE(question_id) WHERE status='open'。
"""
from __future__ import annotations

from services.dbapi_compat import wrap_conn
from utils.timeutil import utcnow  # 写库时间统一 naive UTC（P1-C2）
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

_CONFLICT_DDL = """
CREATE TABLE IF NOT EXISTS conflict_review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    answer_a TEXT NOT NULL DEFAULT '',
    answer_b TEXT NOT NULL DEFAULT '',
    source_a TEXT NOT NULL DEFAULT '',
    source_b TEXT NOT NULL DEFAULT '',
    confidence_a REAL NOT NULL DEFAULT 0.0,
    confidence_b REAL NOT NULL DEFAULT 0.0,
    suggested_winner TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    resolution TEXT,
    reviewer_note TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
)
"""
_CONFLICT_OPEN_UQ = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_conflict_open
ON conflict_review_queue(question_id) WHERE status='open'
"""
_IDX_CONFLICT_STATUS = """
CREATE INDEX IF NOT EXISTS idx_conflict_status
ON conflict_review_queue(status)
"""


def ensure_conflict_schema(db: Session) -> None:
    conn = wrap_conn(db.connection().connection)
    from services.ddl_compat import adapt_ddl
    conn.execute(adapt_ddl(_CONFLICT_DDL, conn))
    conn.execute(_CONFLICT_OPEN_UQ)
    conn.execute(_IDX_CONFLICT_STATUS)
    # resolve/reject 要对候选降权，answer_candidates（module A 表）必须就位：
    # 测试/独立部署可能未跑 ensure_module_a_schema，这里按同结构兜底建表。
    conn.execute("""
        CREATE TABLE IF NOT EXISTS answer_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            answer TEXT NOT NULL,
            explanation TEXT,
            confidence REAL NOT NULL DEFAULT 0.5,
            source TEXT NOT NULL,
            used_for_grading INTEGER NOT NULL DEFAULT 0,
            verified_by TEXT, verified_at DATETIME,
            FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE
        )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ansc_qid ON answer_candidates(question_id)")
    # 老库兼容：module_a_schema 建的 answer_candidates 缺规格新增列与唯一索引，
    # 逐个 ALTER（列已存在时忽略错误），upsert 依赖 (question_id, source) 唯一索引。
    # 逐条用 SAVEPOINT 隔离。
    #
    # 为什么必须这样：PG 里**一条语句失败会把整个事务打成 aborted**，此后
    # 任何语句都报 InFailedSqlTransaction。原实现是裸 try/except 吞掉，
    # 于是"第一条 ALTER 失败 → 后面三条全部失败 → 一个都不留痕"，
    # 症状是 provenance / reviewed 列**永远建不出来**，直到
    # /api/conflicts/*/resolve 报 column "provenance" does not exist 才被发现。
    # （同一个坑在 services/qa_foundation.py 也踩过一次，那里也是用 SAVEPOINT 修的。）
    import logging

    _log = logging.getLogger(__name__)
    for _ddl in (
        "ALTER TABLE answer_candidates ADD COLUMN provenance TEXT",
        "ALTER TABLE answer_candidates ADD COLUMN reviewed BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE answer_candidates ADD COLUMN created_at TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ansc_qid_src "
        "ON answer_candidates(question_id, source)",
    ):
        try:
            conn.execute("SAVEPOINT ansc_ddl")
            conn.execute(_ddl)
            conn.execute("RELEASE SAVEPOINT ansc_ddl")
        except Exception as exc:  # noqa: BLE001 - 列/索引已存在属正常
            # 回滚到保存点，事务复位，后续 DDL 才有机会执行
            try:
                conn.execute("ROLLBACK TO SAVEPOINT ansc_ddl")
            except Exception:  # noqa: BLE001
                pass
            _log.warning("answer_candidates 懒建 DDL 未生效（多半已存在）: %s",
                         str(exc)[:160])
    conn.commit()


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def register_conflict(db: Session, question_id: int, answer_a: str, answer_b: str,
                      source_a: str, source_b: str,
                      confidence_a: float = 0.0, confidence_b: float = 0.0,
                      suggested_winner: Optional[str] = None) -> bool:
    """冲突入队（幂等：该题已有 open 冲突时跳过，返回 False）。"""
    ensure_conflict_schema(db)
    conn = wrap_conn(db.connection().connection)
    cur = conn.execute(
        "INSERT OR IGNORE INTO conflict_review_queue "
        "(question_id, answer_a, answer_b, source_a, source_b, confidence_a, "
        "confidence_b, suggested_winner, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?, 'open', ?)",
        (question_id, answer_a or "", answer_b or "", source_a or "", source_b or "",
         float(confidence_a or 0), float(confidence_b or 0), suggested_winner, _now()),
    )
    conn.commit()
    return (cur.rowcount or 0) > 0  # 部分唯一索引命中 → IGNORE → rowcount=0


def list_conflicts(db: Session, status: str = "open", limit: int = 20,
                   offset: int = 0, question_id: Optional[int] = None) -> Dict:
    """规格 §1.4：{total, items:[...]}；status 非法 → ValueError（路由转 400）。"""
    if status not in ("open", "resolved", "rejected"):
        raise ValueError(f"status 非法: {status}")
    ensure_conflict_schema(db)
    conn = wrap_conn(db.connection().connection)
    where, args = "status=?", [status]
    if question_id:
        where += " AND question_id=?"
        args.append(question_id)
    total = conn.execute(
        f"SELECT COUNT(*) FROM conflict_review_queue WHERE {where}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT id, question_id, answer_a, answer_b, source_a, source_b, "
        "confidence_a, confidence_b, suggested_winner, status, resolution, "
        f"reviewer_note, reviewed_at, created_at FROM conflict_review_queue "
        f"WHERE {where} ORDER BY id LIMIT ? OFFSET ?",
        [*args, limit, offset]).fetchall()
    cols = ["id", "question_id", "answer_a", "answer_b", "source_a", "source_b",
            "confidence_a", "confidence_b", "suggested_winner", "status",
            "resolution", "reviewer_note", "reviewed_at", "created_at"]
    return {"total": total, "items": [dict(zip(cols, r)) for r in rows]}


def conflict_stats(db: Session) -> Dict:
    """看板：open/resolved/rejected 计数 + 按来源对分布。"""
    ensure_conflict_schema(db)
    conn = wrap_conn(db.connection().connection)
    counts = {"open": 0, "resolved": 0, "rejected": 0}
    for st, n in conn.execute(
            "SELECT status, COUNT(*) FROM conflict_review_queue GROUP BY status"):
        if st in counts:
            counts[st] = n
    by_source = {f"{a}_vs_{b}": n for a, b, n in conn.execute(
        "SELECT source_a, source_b, COUNT(*) FROM conflict_review_queue "
        "WHERE status='open' GROUP BY source_a, source_b")}
    return {"open": counts["open"], "resolved": counts["resolved"],
            "rejected": counts["rejected"], "by_source": by_source}


def _downgrade(conn, question_id: int, keep_answer: Optional[str], factor: float) -> None:
    """同题其它候选降权（保持答案不变的候选也降，规格 §1.4 行为 3）。"""
    conn.execute(
        "UPDATE answer_candidates SET confidence = GREATEST(0.1, confidence * ?) "
        "WHERE question_id = ?", (factor, question_id))


def resolve_conflict(db: Session, queue_id: int, resolution: str,
                     reviewer_note: Optional[str] = None) -> Dict:
    """结案-采纳：候选写入 user_confirmed(1.0, provenance=conflict:{id})，
    其它候选 ×0.8；open 幂等（非 open → ValueError → 路由 409）。"""
    ensure_conflict_schema(db)
    conn = wrap_conn(db.connection().connection)
    row = conn.execute(
        "SELECT question_id, status FROM conflict_review_queue WHERE id=?",
        (queue_id,)).fetchone()
    if not row:
        raise LookupError("conflict 不存在")
    if row[1] != "open":
        raise ValueError(f"conflict 已结案（{row[1]}），重复提交拒绝")
    qid = row[0]
    conn.execute(
        "INSERT INTO answer_candidates (question_id, answer, source, confidence, "
        "provenance, reviewed, created_at) VALUES (?,?,?,?,?,TRUE,?) "
        "ON CONFLICT(question_id, source) DO UPDATE SET answer=excluded.answer, "
        "confidence=excluded.confidence, provenance=excluded.provenance, "
        "reviewed=TRUE, created_at=excluded.created_at",
        (qid, resolution, "user_confirmed", 1.0, f"conflict:{queue_id}", _now()))
    _downgrade(conn, qid, resolution, 0.8)
    conn.execute(
        "UPDATE conflict_review_queue SET status='resolved', resolution=?, "
        "reviewer_note=?, reviewed_at=? WHERE id=?",
        (resolution, reviewer_note, _now(), queue_id))
    # 结案后同步题目主答案与置信度（供判分链直接读）
    conn.execute(
        "UPDATE quiz_questions SET answer=?, answer_source='user_confirmed', "
        "answer_confidence=1.0 WHERE id=?", (resolution, qid))
    conn.commit()
    return {"id": queue_id, "status": "resolved", "question_id": qid}


def reject_conflict(db: Session, queue_id: int,
                    reviewer_note: Optional[str] = None) -> Dict:
    """结案-驳回：两侧候选 ×0.7（下限 0.1），status=rejected。"""
    ensure_conflict_schema(db)
    conn = wrap_conn(db.connection().connection)
    row = conn.execute(
        "SELECT question_id, status FROM conflict_review_queue WHERE id=?",
        (queue_id,)).fetchone()
    if not row:
        raise LookupError("conflict 不存在")
    if row[1] != "open":
        raise ValueError(f"conflict 已结案（{row[1]}）")
    conn.execute(
        "UPDATE answer_candidates SET confidence = GREATEST(0.1, confidence * 0.7) "
        "WHERE question_id = ?", (row[0],))
    conn.execute(
        "UPDATE conflict_review_queue SET status='rejected', reviewer_note=?, "
        "reviewed_at=? WHERE id=?", (reviewer_note, _now(), queue_id))
    conn.commit()
    return {"id": queue_id, "status": "rejected"}


def seed_legacy_conflicts(db: Session, rows: List[Dict]) -> Dict:
    """历史冲突批量入队（幂等；空表才可 seed 之外的单题走 register_conflict）。"""
    inserted = 0
    for r in rows:
        if register_conflict(db, r["question_id"], r.get("answer_a", ""),
                             r.get("answer_b", ""), r.get("source_a", ""),
                             r.get("source_b", ""), r.get("confidence_a", 0.0),
                             r.get("confidence_b", 0.0)):
            inserted += 1
    return {"seeded": inserted}
