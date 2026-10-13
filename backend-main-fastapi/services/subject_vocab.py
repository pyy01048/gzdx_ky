# -*- coding: utf-8 -*-
"""documents.subject ↔ knowledge_chunks.subject 的**只读**对齐层（§1.5-E）。

为什么要有这一层
----------------
实测（2026-10-13，mode=ro）：``documents.subject`` 有 25 个取值，
``knowledge_chunks.subject`` 只有 18 个，其中 7 个（共 306 篇文档）在分块侧
一个同名都找不到。按学科名做等值 join 的每个入口（``/api/documents?subject=``、
``/api/documents/subjects``、``/api/taxonomy/coverage``）都会把这些文档算成
「0 块」，于是：

* 用户在资料页选「数学」，看不到 31 篇标着「公共课-数学」的文档；
* 选「数字电子技术」，看不到 186 篇标着「数模电」的合并口径文档；
* 择校页把「数模电」报成「已归档未入库」。

三条硬约束
----------
1. **只读**：本模块不写任何表，归一只发生在查询/聚合层。把 ``documents.subject``
   真改库要逐科批准（走 §2 的 CSV→人批流程）。
2. **别名右侧只能是 ``knowledge_chunks.subject`` 里真实存在的值**，
   且绝不把语料折进公共课去刷覆盖率（口径同
   ``scripts/export_subject_alias_candidates.py`` 的红线）。
3. **拿不准就不归一**：``真题综合``、``网络补充`` 留在 NOT_ALIASED 并写明实测原因 ——
   猜进任何一个学科池就是把覆盖数变成假数。
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

#: 学科池里空的写法（与 routers/quality.py 的 _VACUOUS_SUBJECTS 同一口径）
_VACUOUS = {"", "其他", "其它", "未知", "未分类", None}

#: 前缀/缩写写法 → 分块侧的规范名（一一对应，可安全折叠）
ONE_TO_ONE = {
    "公共课-数学": "数学",
    "公共课-政治": "政治",
    "公共课-英语": "英语",
    "408": "计算机学科专业基础408",
}

#: 合并学科 → 它实际覆盖的规范学科集合（一篇文档同时属于两侧）
COMBINED = {
    "数模电": ("数字电子技术", "模拟电子技术"),
}

#: 明确不归一，附实测原因（2026-10-13 只读复核）
NOT_ALIASED = {
    "真题综合": (
        "综合卷本就跨多学科：76 篇文档自带 660 个块，分属「其他/管理类联考综合/"
        "经济类联考综合/心理学专业基础」等；按 document_id 关联即可，"
        "折进任何单一学科都是虚报"
    ),
    "网络补充": (
        "是来源标签而不是学科：唯一 1 篇的块实际归在「计算机学科专业基础408」"
    ),
}


def canonical_targets(label: str | None) -> tuple[str, ...]:
    """文档侧标签 → 分块侧规范名；没有诚实的映射就返回空元组。"""
    s = (label or "").strip()
    if not s:
        return ()
    if s in COMBINED:
        return COMBINED[s]
    if s in ONE_TO_ONE:
        return (ONE_TO_ONE[s],)
    if s in NOT_ALIASED:
        return ()
    return (s,)


def alias_parent(label: str | None) -> str | None:
    """该标签是否只是某个规范名的别名；合并学科不算别名（它有两个父级）。"""
    return ONE_TO_ONE.get((label or "").strip())


def doc_subject_group(label: str | None) -> tuple[str, ...]:
    """查询侧展开：给定规范名或别名，返回 documents.subject 应当匹配的全部原值。

    规范名会带上它的所有别名写法，别名本身也返回自己（选「公共课-数学」
    仍旧只查那 31 篇，不反过来吞掉「数学」）。
    """
    s = (label or "").strip()
    if not s:
        return (label,) if label is not None else ()
    group = [s]
    for alias, std in ONE_TO_ONE.items():
        if std == s and alias not in group:
            group.append(alias)
    for combined, stds in COMBINED.items():
        if s in stds and combined not in group:
            group.append(combined)
    return tuple(group)


def alignment_rows(db: Session) -> list[dict]:
    """分学科体检：把「文档侧有、分块侧没有」的标签逐个实测定性。

    每行都带真实计数，方便人批时判断是「改标签」还是「根本没解析」。
    """
    from models import Document, KnowledgeChunk

    doc_counts = dict(
        db.query(Document.subject, func.count(Document.id))
        .group_by(Document.subject).all()
    )
    chunk_subjects = {
        (s or "").strip()
        for (s,) in db.query(KnowledgeChunk.subject).distinct().all()
    }
    chunk_counts = dict(
        db.query(KnowledgeChunk.subject, func.count(KnowledgeChunk.id))
        .group_by(KnowledgeChunk.subject).all()
    )

    rows: list[dict] = []
    for raw, n in sorted(doc_counts.items(), key=lambda x: -x[1]):
        label = (raw or "").strip()
        if not label or label in _VACUOUS or label in chunk_subjects:
            continue
        own_chunks = (
            db.query(func.count(KnowledgeChunk.id))
            .join(Document, Document.id == KnowledgeChunk.document_id)
            .filter(func.trim(Document.subject) == label)
            .scalar()
        ) or 0
        # 「有块的文档数」必须从块侧反查：从 Document 侧 outerjoin 出来的行
        # 对零块文档也存在（chunk 列为 NULL），distinct(Document.id) 会等于全部文档数。
        docs_with_chunks = (
            db.query(func.count(func.distinct(KnowledgeChunk.document_id)))
            .join(Document, Document.id == KnowledgeChunk.document_id)
            .filter(func.trim(Document.subject) == label)
            .scalar()
        ) or 0
        pending = (
            db.query(func.count(Document.id))
            .filter(func.trim(Document.subject) == label)
            .filter(Document.index_status != "indexed")
            .scalar()
        ) or 0
        targets = canonical_targets(label)
        if not targets:
            kind, reason = "not_aliased", NOT_ALIASED.get(label, "无可靠的规范名映射")
        elif label in COMBINED:
            kind = "combined_expanded"
            reason = f"合并口径，实际覆盖 {'/'.join(targets)}"
        elif label in ONE_TO_ONE:
            kind = "alias_folded"
            reason = f"前缀/缩写写法，折入规范名「{targets[0]}」"
        else:
            # 词表还没登记这种写法。绝不能报成 "折入规范名「自己」"——
            # 那等于把一个没人认领的标签洗成合法学科，覆盖率跟着变假。
            kind = "unknown_mapping"
            reason = "词表未登记：既无别名映射，也没写明为何不归一，需人工判定"
        rows.append({
            "subject": label,
            "documents": int(n or 0),
            "own_chunks": int(own_chunks or 0),
            "documents_with_chunks": int(docs_with_chunks or 0),
            "not_indexed": int(pending),
            "targets": list(targets),
            "target_chunks": [
                {"subject": t, "chunks": int(chunk_counts.get(t, 0) or 0)} for t in targets
            ],
            "kind": kind,
            "reason": reason,
        })
    return rows


def summary(db: Session) -> dict:
    """只读视图汇总，供 /api/quality 与看板消费。"""
    from models import Document

    rows = alignment_rows(db)
    return {
        "document_subjects": (
            db.query(func.count(func.distinct(Document.subject))).scalar() or 0
        ),
        "unaligned_labels": len(rows),
        "unaligned_documents": sum(r["documents"] for r in rows),
        # 只有「别名/合并口径」这两类能靠接口层归一连上语料；
        # not_aliased 要逐篇人工判定，unknown_mapping 是没人认领的写法，
        # 两者都不许自动折叠。
        "foldable_documents": sum(
            r["documents"] for r in rows
            if r["kind"] in ("alias_folded", "combined_expanded")
        ),
        "not_indexed_documents": sum(r["not_indexed"] for r in rows),
        # 口径：非 indexed 含 pending / indexing / failed，统称「还没可检索的块」，
        # 不写成 never_parsed —— failed 的那些解析过，只是没过质量闸门。
        "note": (
            "归一只发生在查询/聚合层，documents.subject 未改动；"
            "not_aliased 与 unknown_mapping 要逐科人批，"
            "not_indexed_documents 要先解析/补块"
        ),
        "rows": rows,
    }
