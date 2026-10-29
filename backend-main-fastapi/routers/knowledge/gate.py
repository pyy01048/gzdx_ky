"""RAG 检索门控路由（A3）：前缀 /api/gate。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.dbapi_compat import wrap_conn
from database import get_db
from services import retrieval_gate, blind_spot_pool
from services.module_a_schema import ensure_module_a_schema

router = APIRouter(prefix="/api/gate", tags=["RAG门控"])


class GateSearchRequest(BaseModel):
    query: str
    limit: int = 6
    subject: Optional[str] = None
    is_complex: Optional[bool] = None
    use_exam_lane: bool = True
    sink_abstain: bool = True  # abstain 时是否沉淀盲区池


@router.post("/search")
def gate_search(req: GateSearchRequest, db: Session = Depends(get_db)):
    """检索 + 双阈值门控：accept / retry(HyDE|step_back) / abstain。

    sink_abstain=True 时，abstain 结果自动沉淀 pending_questions（A4）。
    """
    ensure_module_a_schema(db)
    result = retrieval_gate.gate_and_retrieve(
        db,
        query=req.query,
        limit=req.limit,
        subject=req.subject,
        is_complex=req.is_complex,
        use_exam_lane=req.use_exam_lane,
    )
    # A4 联动：abstain/拒答沉淀盲区池
    if req.sink_abstain and (result["decision"] == "abstain" or result.get("would_abstain")):
        try:
            gap_id = blind_spot_pool.record_abstain(
                db,
                question=req.query,
                subject=req.subject,
                basis="",
                basis_ids=[],
                gap_type="no_material",
                suggestion="该知识点的教材/真题解析资料",
                suggested_action="import_file",
            )
            result["blind_spot_gap_id"] = gap_id
        except Exception as e:  # 沉淀失败不影响门控结果
            result["blind_spot_error"] = str(e)
    return result


@router.get("/stats")
def gate_stats(db: Session = Depends(get_db)):
    """门控打点统计：决策分布 / would_abstain 率 / 平均延迟。"""
    ensure_module_a_schema(db)
    conn = wrap_conn(db.connection().connection)
    rows = conn.execute(
        "SELECT decision, COUNT(*) AS n FROM retrieval_gate_logs GROUP BY decision"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM retrieval_gate_logs").fetchone()[0]
    abstain_n = conn.execute(
        "SELECT COUNT(*) FROM retrieval_gate_logs WHERE would_abstain = TRUE"
    ).fetchone()[0]
    avg_ms = conn.execute("SELECT AVG(latency_ms) FROM retrieval_gate_logs").fetchone()[0]
    return {
        "total": int(total),
        "by_decision": [{"decision": r[0], "count": int(r[1])} for r in rows],
        "would_abstain": int(abstain_n),
        "would_abstain_rate": round(abstain_n / total, 4) if total else 0.0,
        "avg_latency_ms": round(float(avg_ms or 0), 1),
    }
