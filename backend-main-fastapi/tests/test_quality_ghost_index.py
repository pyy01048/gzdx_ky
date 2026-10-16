"""`GET /api/quality/corpus` 的 ghost 指标：状态写着 indexed，库里却一块都没有。

这类文档在列表页显示「已入库」，但 RAG 检索不到、答疑不会引用 —— 是「页面骗人」
里最难发现的一种（实测生产库 245 篇，其中 89 篇有 200 字以上正文）。
本测试只锁指标算得对，不做任何写库修复。

`NOT IN` 的 SQL 陷阱必须钉住：子查询里只要混进一个 NULL，整个结果集就变空，
指标会假成 0 —— 看起来「一切正常」，比原来更能骗人。

只用 conftest 的临时库（红线：绝不碰 D:\\平台\\database\\kaoyan.db）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


def test_ghost_index_counts_indexed_docs_without_chunks(db_schema):  # noqa: ARG001
    from database import SessionLocal
    from models import Document, KnowledgeChunk
    from routers.quality import _ghost_index

    db = SessionLocal()
    ids = []
    # 临时库是 session 级的，其它用例可能已经留下 indexed 零块的行，
    # 所以这里断言的是**增量**而不是绝对值 —— 全局计数会把跨用例污染当成指标。
    base = _ghost_index(db)["indexed_without_chunks"]
    try:
        ghost = Document(file_name="ghost.txt", subject="政治", index_status="indexed",
                         content="考研政治真题" * 60)
        real = Document(file_name="real.txt", subject="政治", index_status="indexed")
        pending = Document(file_name="p.txt", subject="政治", index_status="pending")
        db.add_all([ghost, real, pending])
        db.flush()
        ids = [ghost.id, real.id, pending.id]
        db.add(KnowledgeChunk(document_id=real.id, doc_name="real.txt", chunk_id=0,
                              subject="政治", text="可检索的分块"))
        # 孤儿块：document_id 为 NULL，绝不能把 NOT IN 的结果清成 0
        db.add(KnowledgeChunk(document_id=None, doc_name="orphan.txt", chunk_id=0,
                              subject="政治", text="没有归属的块"))
        db.commit()

        assert _ghost_index(db)["indexed_without_chunks"] == base + 1, \
            "该只多数出 indexed 且零分块的那一篇"

        # 补一块就该归零：指标跟着库里事实走，不是跟着状态字段走
        db.add(KnowledgeChunk(document_id=ghost.id, doc_name="ghost.txt", chunk_id=0,
                              subject="政治", text="补上的分块"))
        db.commit()
        assert _ghost_index(db)["indexed_without_chunks"] == base
    finally:
        for i in ids:
            db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:i"), {"i": i})
            db.execute(text("DELETE FROM documents WHERE id=:i"), {"i": i})
        db.execute(text("DELETE FROM knowledge_chunks WHERE document_id IS NULL"))
        db.commit()
        db.close()
