"""评测与数据质量只读接口（eval_runs + 语料体检口径）。

口径来自 docx/14：所有数字都是从库里聚合出来的，不做任何"估计"；
识别侧的 precision/recall 只存在于 eval_runs.metrics（人工判分样本上算的），
本路由不重算，避免两套口径。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, case, cast, func, select
from sqlalchemy.orm import Session

from database import get_db
from models import Document, EvalRun, KnowledgeChunk

router = APIRouter(prefix="/api/quality", tags=["quality"])

#: 学科池里"没学科"的取值：弃权块与未打标块
_VACUOUS_SUBJECTS = ("其他", "其它", "未知", "未分类", "")


def _run_row(r: EvalRun) -> dict:
    return {
        "id": r.id, "kind": r.kind, "arm": r.arm or "",
        "primary_metric": r.primary_metric, "n_samples": r.n_samples,
        "dataset_fingerprint": r.dataset_fingerprint or "",
        "report_path": r.report_path or "", "notes": r.notes or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


@router.get("/eval-runs")
async def list_eval_runs(
    kind: Optional[str] = Query(None, description="qa|recognition|recognition_policy|corpus_probe"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """运行历史列表（按时间倒序），趋势图的数据源。"""
    q = db.query(EvalRun)
    if kind:
        q = q.filter(EvalRun.kind == kind)
    rows = q.order_by(EvalRun.id.desc()).limit(limit).all()
    return {"items": [_run_row(r) for r in rows], "total": q.count()}


@router.get("/eval-runs/{run_id}")
async def get_eval_run(run_id: int, db: Session = Depends(get_db)):
    """单次运行的完整 metrics（脚本 report 原文）。"""
    r = db.get(EvalRun, run_id)
    if r is None:
        raise HTTPException(status_code=404, detail=f"eval_run {run_id} 不存在")
    out = _run_row(r)
    out["metrics"] = r.metrics or {}
    return out


@router.get("/latest")
async def latest(db: Session = Depends(get_db),
                 kind: str = Query("recognition", description="运行类型")):
    """某类评测的最新一次运行（看板首屏用）。"""
    r = (db.query(EvalRun).filter(EvalRun.kind == kind)
         .order_by(EvalRun.id.desc()).first())
    if r is None:
        return {"kind": kind, "run": None, "metrics": {}}
    out = _run_row(r)
    out["metrics"] = r.metrics or {}
    return {"kind": kind, "run": out, "metrics": out["metrics"]}


def _subject_stats(db: Session) -> list:
    """按学科聚合块数、平均置信、低置信数、弃权数（学科=其他）。"""
    rows = (
        db.query(
            KnowledgeChunk.subject,
            func.count(KnowledgeChunk.id),
            func.avg(KnowledgeChunk.classify_confidence),
            func.sum(case((KnowledgeChunk.classify_confidence < 0.40, 1), else_=0)),
            # classify_source 在 PostgreSQL 是 ENUM 类型，`LIKE` 不能直接作用于枚举
            # （实测：operator does not exist: classify_source ~~ character varying）。
            # 先 CAST 成 text 再匹配。注意 PG 侧该枚举的合法值只有
            # vector/keyword/fusion/llm/no_bge/fallback，不含 "junk:" 前缀，
            # 故此计数在 PG 后端恒为 0 —— 垃圾块改由 knowledge_chunks.l3_content_type
            # 与 quiz_content_gate 的口径判定，见 services/quiz_content_gate.py。
            func.sum(case((cast(KnowledgeChunk.classify_source, String).like("junk:%"), 1), else_=0)),
        )
        .group_by(KnowledgeChunk.subject)
        .all()
    )
    out = []
    for subj, n, avg_conf, low, junk in rows:
        s = (subj or "").strip()
        out.append({
            "subject": s or "未标注",
            "chunks": int(n or 0),
            "avg_confidence": round(float(avg_conf or 0.0), 4),
            "low_conf_chunks": int(low or 0),
            "abstained_chunks": int(junk or 0),
            "in_subject_pool": s not in _VACUOUS_SUBJECTS,
        })
    return sorted(out, key=lambda x: -x["chunks"])


def _ghost_index(db: Session) -> dict:
    """「状态写着 indexed、库里却一块都没有」的文档数 —— 只读体检，不写任何数据。

    这类文档在列表页显示「已入库」，RAG 里搜不到，答疑也就永远不会引用它。
    子查询里必须排掉 `document_id IS NULL` 的孤儿块，否则 SQL 的 `NOT IN` 遇 NULL
    直接返回空集，数字会假成 0。
    """
    has_chunk = select(KnowledgeChunk.document_id).where(
        KnowledgeChunk.document_id.isnot(None)).scalar_subquery()
    ghost = int(db.query(func.count(Document.id)).filter(
        Document.index_status == "indexed", Document.id.notin_(has_chunk)).scalar() or 0)
    return {"indexed_without_chunks": ghost}


@router.get("/corpus")
async def corpus_quality(db: Session = Depends(get_db)):
    """语料级质量规模：分学科块数/置信/弃权，加上文档学科分布。"""
    stats = _subject_stats(db)
    total_chunks = sum(x["chunks"] for x in stats)
    pooled = sum(x["chunks"] for x in stats if x["in_subject_pool"])
    docs = db.query(Document.subject, func.count(Document.id)).group_by(Document.subject).all()
    return {
        "total_chunks": total_chunks,
        "total_documents": int(sum(n for _, n in docs) or 0),
        "in_pool_chunks": pooled,
        "abstained_chunks": total_chunks - pooled,
        "abstained_rate": round((total_chunks - pooled) / total_chunks, 4) if total_chunks else 0.0,
        "subjects": stats,
        "ghost_index": _ghost_index(db),
        "document_subjects": sorted(
            [{"subject": (s or "未标注"), "documents": int(n)} for s, n in docs],
            key=lambda x: -x["documents"])[:30],
    }


@router.get("/subject-alignment")
async def subject_alignment(db: Session = Depends(get_db)):
    """学科词表对齐体检（只读）：documents.subject 有哪些写法在分块侧没有同名值。

    每一行都带实测计数，用来判断该科是「别名折叠就能连上语料」还是「还没解析出块」：
    ``kind=not_aliased/unknown_mapping`` 要逐科人工判定，``not_indexed`` 高的要先解析。
    本端点不写库、不改标签，归一只发生在查询/聚合层。
    """
    from services import subject_vocab

    return subject_vocab.summary(db)


@router.get("/tree-overlay")
async def tree_overlay(db: Session = Depends(get_db)):
    """知识地图（KbMap）质量层：学科 → 章节 的块数/平均置信/弃权数。

    章节口径用 knowledge_chunks.l2_chapter（打标写入的原文小节名），
    与 /api/taxonomy/tree 的章节名不保证一一对应，前端按名字匹配、匹配不上就挂到学科上。
    """
    sub = _subject_stats(db)
    rows = (
        db.query(
            KnowledgeChunk.subject,
            KnowledgeChunk.l2_chapter,
            func.count(KnowledgeChunk.id),
            func.avg(KnowledgeChunk.classify_confidence),
            # 同 _subject_stats：classify_source 在 PG 是 ENUM，LIKE 前需 CAST 成 text
            func.sum(case((cast(KnowledgeChunk.classify_source, String).like("junk:%"), 1), else_=0)),
        )
        .filter(KnowledgeChunk.l2_chapter.isnot(None))
        .filter(KnowledgeChunk.l2_chapter != "")
        .group_by(KnowledgeChunk.subject, KnowledgeChunk.l2_chapter)
        .all()
    )
    chapters: dict = {}
    for subj, ch, n, avg_conf, junk in rows:
        chapters.setdefault((subj or "").strip(), []).append({
            "chapter": (ch or "").strip()[:200],
            "chunks": int(n or 0),
            "avg_confidence": round(float(avg_conf or 0.0), 4),
            "abstained_chunks": int(junk or 0),
        })
    return {
        "subjects": [
            {**x, "chapters": sorted(chapters.get(x["subject"], []),
                                     key=lambda c: -c["chunks"])[:40]}
            for x in sub
        ]
    }


@router.get("/major-coverage")
async def major_coverage(db: Session = Depends(get_db)):
    """择校可靠度：专业初试科目 ↔ 知识库语料覆盖（L1 精确口径）。

    只按**专业课名 == documents.subject 精确相等**判定覆盖，公共课（数学/英语/
    政治）人人必考、匹配了等于没匹配，所以排除；不猜专业代码→学科的映射，
    匹配不上就报 uncovered，宁可少报也不虚报。
    """
    from services import major_coverage as mc

    supply = mc.subject_supply(db)
    return {
        "summary": mc.coverage_summary(db, supply),
        "subjects": [
            {"subject": k, **v}
            for k, v in sorted(supply.items(), key=lambda kv: -kv[1]["documents"])
        ],
        "by_school": mc.school_rollup(db, supply),
    }
