"""物理删除闸门与分块入库的边界（`services/kb_service.py:391-425`）。

实测背景：闸门原先写在「查旧分块」之前，只要 `replace=True` 就先抛
`PhysicalDeleteBlocked`。而**所有**入库路径（上传重解析 / parse-all / 网盘 /
目录导入 / OCR 回捞 / smart_ingest / kb_ingest / 目录监听）都传 `replace=True`，
于是首次入库这种「一块都还没有」的情形也被挡死：正文写进去了、分块 0 条，
异常又被调用方的 `except` 吞成一行 print —— 文档静默进不了 RAG。

生产影响实测（temp/probe_zero_chunk_cause.py，只读）：库里现有 **232 篇**有正文却零分块，
但它们全部早于 `delete_guard.py` 落盘时间 2026-10-12 15:57（182 篇集中在当天 03-04 时），
所以这批**不是**这个闸门造的，是另一类成因（143 篇 `pending` 从没解析、89 篇 `indexed` 却零块）。
闸门这个缺陷的真实杀伤力是：任何**未设环境变量**的进程一旦加载带闸门的代码，
之后每一篇新文档都会静默零分块 —— 所以它是 P0，只是本轮实测还没让线上数据吃到这个亏。

同时必须守住闸门本来的职责：真要删已有分块时，未放行一律拦截，且**旧块不能被删掉**。

只用 conftest 的临时库（红线：绝不碰 D:\\平台\\database\\kaoyan.db）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from services.delete_guard import ENV_ENABLED_VALUE, ENV_FLAG, PhysicalDeleteBlocked

BODY = "第 1 章 逻辑代数基础\n" + "逻辑代数的基本运算与公式。" * 40


@pytest.fixture(autouse=True)
def _flag_off(monkeypatch, chunk_fts_mirror):  # noqa: ARG001
    """默认态：环境变量未设置 = 物理删除关闭（与生产 `.env` 一致）。

    ``chunk_fts_mirror``：本文件断言 FTS 镜像与分块同事务，需要镜像表存在（见 conftest）。
    """
    monkeypatch.delenv(ENV_FLAG, raising=False)


def _doc(db, file_name):
    from models import Document

    d = Document(file_name=file_name, subject="数字电子技术", content=BODY,
                 file_path=f"knowledge_base/数电/{file_name}", index_status="indexed")
    db.add(d)
    db.commit()
    return d.id


def _chunk_ids(db, doc_id):
    return [r[0] for r in db.execute(
        text("SELECT id FROM knowledge_chunks WHERE document_id=:d ORDER BY id"),
        {"d": doc_id})]


def _purge(db, doc_id):
    db.execute(text("DELETE FROM knowledge_chunks_fts WHERE document_id=:d"), {"d": doc_id})
    db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": doc_id})
    db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": doc_id})
    db.commit()


def _fts_cnt(db, doc_id):
    return int(db.execute(
        text("SELECT COUNT(*) FROM knowledge_chunks_fts WHERE document_id=:d"),
        {"d": doc_id}).scalar())


def test_first_time_ingest_produces_chunks_with_flag_off(db_schema):  # noqa: ARG001
    """回归本次发现的缺陷：零旧块时 replace=True 不该被闸门挡死。"""
    from database import SessionLocal
    from services.kb_service import ingest_text

    db = SessionLocal()
    try:
        doc_id = _doc(db, f"GATE-{__file__}-fresh.txt")
        n = ingest_text(db, doc_id, "GATE-fresh.txt", BODY,
                        subject="数字电子技术", replace=True)
        db.commit()
        assert n > 0, "首次入库被物理删除闸门挡住 → 文档有正文但零分块"
        assert len(_chunk_ids(db, doc_id)) == n
        _purge(db, doc_id)
    finally:
        db.close()


def test_replace_with_existing_chunks_stays_blocked_and_keeps_them(db_schema):  # noqa: ARG001
    """闸门职责不能被这次修复削弱：真要删旧块时未放行就拦截，且旧块原样保留。"""
    from database import SessionLocal
    from services.kb_service import ingest_text

    db = SessionLocal()
    try:
        doc_id = _doc(db, "GATE-existing.txt")
        first = ingest_text(db, doc_id, "GATE-existing.txt", BODY,
                            subject="数字电子技术", replace=True)
        db.commit()
        before = _chunk_ids(db, doc_id)
        assert len(before) == first > 0

        with pytest.raises(PhysicalDeleteBlocked):
            ingest_text(db, doc_id, "GATE-existing.txt", BODY + "追加一段正文。",
                        subject="数字电子技术", replace=True)

        db.rollback()
        assert _chunk_ids(db, doc_id) == before, "被拦截却把旧分块删了，就是最坏结果"
        _purge(db, doc_id)
    finally:
        db.close()


def test_replace_rechunks_when_flag_explicitly_enabled(db_schema, monkeypatch):  # noqa: ARG001
    """显式放行后，重新解析应当删旧块、长新块（测试环境自己开的开关）。"""
    from database import SessionLocal
    from services.kb_service import ingest_text

    db = SessionLocal()
    try:
        doc_id = _doc(db, "GATE-enabled.txt")
        first = ingest_text(db, doc_id, "GATE-enabled.txt", BODY,
                            subject="数字电子技术", replace=True)
        db.commit()
        assert first > 0

        monkeypatch.setenv(ENV_FLAG, ENV_ENABLED_VALUE)
        again = ingest_text(db, doc_id, "GATE-enabled.txt", BODY + BODY,
                            subject="数字电子技术", replace=True)
        db.commit()
        ids = _chunk_ids(db, doc_id)
        assert again > first, (first, again)
        assert len(ids) == again, f"旧块没清干净：{len(ids)} 行，本轮只该有 {again} 块"
        _purge(db, doc_id)
    finally:
        db.close()


def test_mirror_deletes_are_not_committed_ahead_of_the_chunks(db_schema, monkeypatch):  # noqa: ARG001
    """删 FTS/向量镜像必须和分块的删建同事务，不能自己先 commit。

    复核发现的中间态：原先 raw cursor 删完镜像就 commit，随后分块插入若失败，
    rollback 只能回滚 knowledge_chunks 那一侧 —— 结果「块还在、检索镜像没了」，
    文档从 RAG 里静默消失，而且没有任何报错。
    """
    from database import SessionLocal
    from services import kb_service

    db = SessionLocal()
    try:
        doc_id = _doc(db, "GATE-atomic.txt")
        first = kb_service.ingest_text(db, doc_id, "GATE-atomic.txt", BODY,
                                       subject="数字电子技术", replace=True)
        db.commit()
        assert first > 0 and _fts_cnt(db, doc_id) == first

        monkeypatch.setenv(ENV_FLAG, ENV_ENABLED_VALUE)

        def boom(*_a, **_kw):
            raise RuntimeError("模拟分块阶段崩溃")

        monkeypatch.setattr(kb_service, "chunk_text", boom)
        with pytest.raises(RuntimeError):
            kb_service.ingest_text(db, doc_id, "GATE-atomic.txt", BODY,
                                   subject="数字电子技术", replace=True)

        db.rollback()
        assert len(_chunk_ids(db, doc_id)) == first, "分块被删了"
        assert _fts_cnt(db, doc_id) == first, "检索镜像先于分块被提交删除 → 静默检索损坏"
        _purge(db, doc_id)
    finally:
        db.close()
