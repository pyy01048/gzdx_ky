# -*- coding: utf-8 -*-
"""C 批次1 回归：摘要清洗 / 失败重索引 / 章节 KP 幂等 / 科目字典+队列 / 端点鉴权。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

UID = 990007

MD_BODY = """# 第一章 函数与极限
## 1.1 映射与函数
函数的概念与表示法是考研数学的基础考点。
### 函数的有界性
有界性判定常用放缩与最值定理。
## 1.2 数列的极限
极限的 epsilon-N 定义与收敛准则。
# 第二章 导数与微分
## 2.1 导数概念
导数的几何意义与可导必连续。
"""

TABLE_HEAD = "| 科目 | 分值 | 题型 |\n|---|---|---|\n| 数学 | 150 | 解答 |\n正文开头其余内容。"


@pytest.fixture()
def seed(db_schema):
    from database import SessionLocal

    from models import Document, KnowledgeChunk, SubjectConfig

    db = SessionLocal()
    ids = {}
    added_subjects = []
    try:
        # 测试库科目字典可能未播种：显式补标准池（teardown 只删本 fixture  added 行）
        for nm in ("数学", "英语", "政治"):
            if db.query(SubjectConfig).filter(SubjectConfig.subject == nm).first() is None:
                db.add(SubjectConfig(subject=nm, is_custom=False))
                added_subjects.append(nm)
        db.commit()
        a = Document(
            file_name="085401_测试全书.md",
            source_format="md",
            index_status="indexed",
            subject="其他",
            content=MD_BODY,
            knowledge_point_count=0,
            chunk_count=2,
        )
        b = Document(
            file_name="失败有正文.pdf",
            source_format="pdf",
            index_status="failed",
            subject="数学",
            content="这是一段足够长的失败件正文。" * 30,
            knowledge_point_count=0,
        )
        c = Document(
            file_name="失败无正文.pdf",
            source_format="pdf",
            index_status="failed",
            subject="数学",
            content=None,
            knowledge_point_count=0,
        )
        d = Document(
            file_name="27考研数学李永乐线代讲义.pdf",
            source_format="pdf",
            index_status="indexed",
            subject="其他",
            content="线代正文" * 40,
            knowledge_point_count=0,
        )
        e = Document(
            file_name="未知资料xyz.pdf",
            source_format="pdf",
            index_status="indexed",
            subject="其他",
            content=TABLE_HEAD + "其余正文" * 40,
            knowledge_point_count=0,
        )
        db.add_all([a, b, c, d, e])
        db.commit()
        for k, v in (("a", a), ("b", b), ("c", c), ("d", d), ("e", e)):
            ids[k] = v.id
        db.add_all(
            [
                KnowledgeChunk(document_id=a.id, chunk_index=0, text="## 1.1 映射与函数\n函数的概念与表示法"),
                KnowledgeChunk(document_id=a.id, chunk_index=1, text="## 2.1 导数概念\n导数的几何意义"),
            ]
        )
        db.commit()
        yield ids
    finally:
        from models import DocumentClassifyQueue, KnowledgePoint

        db.query(DocumentClassifyQueue).filter(DocumentClassifyQueue.document_id.in_(list(ids.values()))).delete()
        db.query(KnowledgePoint).filter(KnowledgePoint.document_id.in_(list(ids.values()))).delete()
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id.in_(list(ids.values()))).delete()
        db.query(Document).filter(Document.id.in_(list(ids.values()))).delete()
        if added_subjects:
            db.query(SubjectConfig).filter(SubjectConfig.subject.in_(added_subjects)).delete()
        db.commit()
        db.close()


@pytest.fixture()
def admin_client(client, app_module):
    from utils.security import current_user

    prev = app_module.dependency_overrides.get(current_user)
    app_module.dependency_overrides[current_user] = lambda: SimpleNamespace(id=UID, role="admin", username="b1_admin")
    yield client
    if prev is None:
        app_module.dependency_overrides.pop(current_user, None)
    else:
        app_module.dependency_overrides[current_user] = prev


class TestSummaryClean:
    def test_table_to_plain(self):
        from services.document_governance import clean_md_summary

        out = clean_md_summary(TABLE_HEAD)
        assert "|" not in out and "---" not in out
        assert "数学" in out and "150" in out

    def test_empty_and_plain(self):
        from services.document_governance import clean_md_summary

        assert clean_md_summary(None) == ""
        assert clean_md_summary("普通摘要") == "普通摘要"


class TestReindex:
    def test_failed_with_content_reindexed(self, seed):
        from database import SessionLocal
        from services.document_governance import reindex_failed

        from models import Document, KnowledgeChunk

        db = SessionLocal()
        try:
            st = reindex_failed(db, doc_ids=[seed["b"], seed["c"]])
            assert st["reindexed"] == 1 and st["source_missing"] == 1
            b = db.query(Document).get(seed["b"])
            c = db.query(Document).get(seed["c"])
            assert b.index_status == "indexed" and b.parse_error is None
            assert db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == b.id).count() > 0
            assert c.index_status == "failed"
            assert "源文件缺失" in (c.parse_error or "")
        finally:
            db.close()


class TestHeadingKps:
    def test_extract_trace_and_idempotent(self, seed):
        from database import SessionLocal
        from services.document_governance import extract_heading_kps

        from models import Document, KnowledgePoint

        db = SessionLocal()
        try:
            doc = db.query(Document).get(seed["a"])
            r1 = extract_heading_kps(db, doc)
            db.commit()
            assert r1["kept"] >= 4
            rows = db.query(KnowledgePoint).filter(KnowledgePoint.document_id == doc.id).all()
            assert all(k.extract_source == "batch" for k in rows)
            assert any(k.source_chunk_id is not None for k in rows)  # 溯源
            assert any(k.chapter for k in rows)
            n1 = len(rows)
            r2 = extract_heading_kps(db, doc)
            db.commit()
            assert r2["kept"] == r1["kept"]
            n2 = db.query(KnowledgePoint).filter(KnowledgePoint.document_id == doc.id).count()
            assert n2 == n1  # 幂等：重跑不翻倍
            assert doc.knowledge_point_count == n2
        finally:
            db.close()


class TestClassify:
    def test_alias_and_queue(self, seed):
        from database import SessionLocal
        from services.document_governance import classify_subjects

        from models import Document, DocumentClassifyQueue

        db = SessionLocal()
        try:
            st = classify_subjects(db)
            assert st["reclassified"] >= 1
            d = db.query(Document).get(seed["d"])
            assert d.subject == "数学" and d.subject_source == "keyword"
            q = db.query(DocumentClassifyQueue).filter(DocumentClassifyQueue.document_id == seed["e"]).first()
            assert q is not None and q.status == "pending"
        finally:
            db.close()

    def test_resolve_endpoint(self, admin_client, seed):
        from database import SessionLocal
        from services.document_governance import classify_subjects

        db = SessionLocal()
        try:
            classify_subjects(db)  # 先入队，resolve 才有行可裁定
        finally:
            db.close()
        r = admin_client.post(f"/api/documents/classify-queue/{seed['e']}/resolve", json={"subject": "数学"})
        assert r.status_code == 200
        assert r.json()["resolved"] is True
        r2 = admin_client.post(f"/api/documents/classify-queue/{seed['e']}/resolve", json={"subject": "不存在的科目"})
        assert r2.status_code == 400
        rq = admin_client.get("/api/documents/classify-queue?status=resolved")
        assert rq.status_code == 200
        assert any(i["document_id"] == seed["e"] for i in rq.json()["items"])

    def test_queue_requires_admin(self, client, app_module, seed):
        from utils.security import current_user

        prev = app_module.dependency_overrides.get(current_user)
        app_module.dependency_overrides[current_user] = lambda: SimpleNamespace(id=UID, role="user", username="b1_user")
        try:
            r = client.get("/api/documents/classify-queue")
            assert r.status_code == 403
        finally:
            if prev is None:
                app_module.dependency_overrides.pop(current_user, None)
            else:
                app_module.dependency_overrides[current_user] = prev


class TestListOutput:
    def test_summary_cleaned_and_structured_flag(self, admin_client, seed):
        from database import SessionLocal
        from services.document_governance import extract_heading_kps

        from models import Document

        r = admin_client.get("/api/documents", params={"page_size": 100})
        assert r.status_code == 200
        items = {i["id"]: i for i in r.json()["items"]}
        e = items.get(seed["e"])
        assert e is not None
        assert "|" not in e["summary"]
        assert e["is_structured"] is False
        db = SessionLocal()
        try:
            doc = db.query(Document).get(seed["a"])
            extract_heading_kps(db, doc)
            db.commit()
        finally:
            db.close()
        r2 = admin_client.get("/api/documents", params={"page_size": 100})
        items2 = {i["id"]: i for i in r2.json()["items"]}
        assert items2[seed["a"]]["is_structured"] is True

    def test_reindex_endpoint_admin(self, admin_client, seed):
        r = admin_client.post(f"/api/documents/{seed['b']}/reindex")
        assert r.status_code == 200
        body = r.json()
        assert body["reindex"]["reindexed"] == 1
        assert body["index_status"] == "indexed"
