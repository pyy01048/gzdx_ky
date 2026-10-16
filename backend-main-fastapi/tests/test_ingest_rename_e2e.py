"""#27 端到端：`POST /api/documents/{id}/parse` 在入库那一刻就按内容定显示名。

`tests/test_doc_rename_write_through.py` 测的是规则本身；本文件测**接线位置**——
改名必须发生在分块之前，否则 `knowledge_chunks.doc_name`（答疑引用标题
`services/ai_service.py:834` 用的就是它）会带着 `第1章.pptx` 这种垃圾名，
列表页改好了、引用还是旧的。

AI 知识点抽取那一步是 best-effort，这里打桩掉：既不让测试依赖 Ollama，
也不影响「正文 → 改名 → 分块」这条主链路。

只用 conftest 的临时库（红线：绝不碰 D:\\平台\\database\\kaoyan.db）。
"""
from __future__ import annotations

import pytest

BODY = "第 1 章 逻辑代数基础\n" + "逻辑代数的基本运算与公式。" * 40


@pytest.fixture
def _no_llm(monkeypatch):
    from services.ai_service import AIService

    async def fake_chat(self, messages, **kwargs):  # noqa: ARG001
        return {"content": "[]"}

    monkeypatch.setattr(AIService, "chat", fake_chat)


def _seed(client, tmp_path, file_name):
    from database import SessionLocal
    from models import Document

    src = tmp_path / "src.txt"
    src.write_text(BODY, encoding="utf-8")

    db = SessionLocal()
    try:
        # 前置清理：历史运行残留的同正文文档会触发质量闸门「完全相同（重复导入）」
        from sqlalchemy import text

        stale = db.execute(text(
            "SELECT id FROM documents WHERE content = :c"), {"c": BODY}).fetchall()
        for (sid,) in stale:
            db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": sid})
            db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": sid})
        db.commit()
        doc = Document(file_name=file_name, subject="", file_path=str(src),
                       file_type="txt", index_status="pending", parse_progress=0)
        db.add(doc)
        db.commit()
        return doc.id, str(src)
    finally:
        db.close()


def test_parse_endpoint_renames_before_chunking(client, _no_llm, tmp_path):
    from database import SessionLocal
    from models import KnowledgeChunk

    doc_id, src = _seed(client, tmp_path, "第1章.pdf")
    r = client.post(f"/api/documents/{doc_id}/parse")
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        from models import Document

        doc = db.query(Document).filter(Document.id == doc_id).first()
        assert doc.content.startswith("第 1 章 逻辑代数基础"), "正文该照常落库"
        assert doc.file_name == "第 1 章 逻辑代数基础.pdf", doc.file_name
        assert doc.file_path == src, "file_path 一动，#26 的预览/下载就断"

        chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc_id).all()
        assert chunks, "解析后应产出分块"
        assert {c.doc_name for c in chunks} == {doc.file_name}, \
            f"分块 doc_name 没带上新名：{sorted({c.doc_name for c in chunks})}"

        # 再点一次解析：幂等，不能改出「第 1 章 第 1 章 …」这类叠字
        r2 = client.post(f"/api/documents/{doc_id}/parse")
        assert r2.status_code == 200, r2.text
        db.expire_all()
        again = db.query(Document).filter(Document.id == doc_id).first()
        assert again.file_name == "第 1 章 逻辑代数基础.pdf", again.file_name
        assert db.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == doc_id).count() == len(chunks)
    finally:
        from sqlalchemy import text

        db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": doc_id})
        db.execute(text("DELETE FROM knowledge_points WHERE document_id=:d"), {"d": doc_id})
        db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": doc_id})
        db.commit()
        db.close()


def test_parse_endpoint_leaves_informative_name_alone(client, _no_llm, tmp_path):
    """已经看得懂的名字不许被解析动作改掉（只降低信息名）。"""
    from database import SessionLocal
    from models import Document

    doc_id, _src = _seed(client, tmp_path, "1998-2012年.pdf")
    r = client.post(f"/api/documents/{doc_id}/parse")
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        assert doc.file_name == "1998-2012年.pdf", doc.file_name
        from sqlalchemy import text

        db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": doc_id})
        db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": doc_id})
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 状态诚实度：indexed 必须等于「库里真有可检索的分块」
# --------------------------------------------------------------------------- #
def test_parse_without_any_chunk_is_not_marked_indexed(client, _no_llm, tmp_path, monkeypatch):
    """分块 0 条却标 indexed，就是「UI 说已入库、RAG 搜不到」的源头（存量实测 89 篇）。"""
    from database import SessionLocal
    from models import Document
    from services import kb_service

    monkeypatch.delenv("KAOYAN_ALLOW_PHYSICAL_DELETE", raising=False)
    monkeypatch.setattr(kb_service, "ingest_document", lambda db, doc, replace=False: 0)

    doc_id, _src = _seed(client, tmp_path, "第1章.pdf")
    r = client.post(f"/api/documents/{doc_id}/parse")
    assert r.status_code == 200, r.text
    assert r.json()["chunk_count"] == 0

    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        assert doc.index_status == "failed", doc.index_status
    finally:
        from sqlalchemy import text

        db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": doc_id})
        db.commit()
        db.close()


def test_blocked_reparse_keeps_existing_chunks_and_stays_indexed(client, _no_llm, tmp_path,
                                                                 monkeypatch):
    """闸门拦住重建时旧分块和检索镜像都还在，照样能被 RAG 搜到 —— 标 failed 是另一句谎话。"""
    from sqlalchemy import text

    from database import SessionLocal
    from models import Document, KnowledgeChunk
    from services import kb_service

    monkeypatch.delenv("KAOYAN_ALLOW_PHYSICAL_DELETE", raising=False)

    def blocked(db, doc, replace=False):
        from services.delete_guard import require_physical_delete_enabled

        require_physical_delete_enabled("knowledge_chunks")
        return 0

    monkeypatch.setattr(kb_service, "ingest_document", blocked)

    doc_id, _src = _seed(client, tmp_path, "第1章.pdf")
    db = SessionLocal()
    try:
        db.execute(text("INSERT INTO knowledge_chunks (document_id, doc_name, chunk_index,"
                        " subject, text) VALUES (:d, '第1章.pdf', 0, '数字电子技术',"
                        " '逻辑代数的基本运算与公式')"), {"d": doc_id})
        db.commit()
        assert db.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == doc_id).count() == 1

        r = client.post(f"/api/documents/{doc_id}/parse")
        assert r.status_code == 200, r.text

        db.expire_all()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        assert doc.index_status == "indexed", doc.index_status
        assert db.query(KnowledgeChunk).filter(
            KnowledgeChunk.document_id == doc_id).count() == 1, "被拦住了还不该删旧块"

        db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": doc_id})
        db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": doc_id})
        db.commit()
    finally:
        db.close()
