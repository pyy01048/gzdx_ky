# -*- coding: utf-8 -*-
"""V8 阶段3：知识库文档 → 题库 识别预览 + 受控入库 回归测试。

隔离说明
--------
全部请求走 conftest 改写的临时库（DATABASE_PATH 指向 tempfile 下的 qa_test.db），
绝不触碰 ``D:\\平台\\database\\kaoyan.db`` 真实数据。

覆盖
----
1. POST /scan 能从含大题小标题（一、填空题 / 二、选择题）的文档识别出候选题，
   且 **scan 完全只读**：调用后 quiz_questions 行数不变；
2. POST /confirm 只插入被勾选的候选题，source=「知识库:<文件名>」，行数增加；
3. 重复 confirm 同一批 → inserted=0、skipped_existing=N（幂等，不重复插入）；
4. doc_ids 不存在 → 404，detail 为 "文档不存在: [...]"（main.py 的 SPA 处理器已改为保留路由 detail，不再压成 "Not Found"）；
5. confirm 未传任何选择 → 400。
"""
from __future__ import annotations

import os

import pytest

from database import SessionLocal
from models import Document, QuizQuestion
from services.delete_guard import (
    ENV_ENABLED_VALUE,
    ENV_FLAG,
    require_physical_delete_enabled,
)


PREFIX = "QA-KB-IMPORT"


# 含可识别大题结构的文档正文。extract_questions 要求先出现"一、填空题"这类
# 大题小标题，再按"1. / 2. "题号切题，否则 marks 为空、识别不到任何题。
DOC_A_CONTENT = """一、填空题

1. 十进制数 12 转换为二进制是 ____。
2. 逻辑代数中 A 或非 A 的结果是 ____。

二、选择题

1. 下列电路中属于组合逻辑电路的是
A、触发器
B、译码器
C、计数器
D、寄存器
答案：B
"""

DOC_B_CONTENT = """一、判断题

1. 译码器在工作时不存在竞争冒险现象，输出是唯一确定的逻辑电平。
答案：错误
2. 触发器是具有记忆功能的时序逻辑电路基本单元，每个触发器可以存储一位二进制信息。
答案：正确
3. 计数器不仅能对输入脉冲的个数进行累计，还可以实现分频和定时功能。
答案：正确
"""


def _count_questions() -> int:
    db = SessionLocal()
    try:
        return db.query(QuizQuestion).count()
    finally:
        db.close()


@pytest.fixture
def kb_docs():
    """插入两篇带可识别题目的文档，返回 id；用例结束后清理。"""
    db = SessionLocal()
    created_ids: list[int] = []
    created_files: list[str] = []
    try:
        a = Document(
            file_name=f"{PREFIX}-数电真题A.txt",
            file_path="qa-a.txt", file_type="txt", size=len(DOC_A_CONTENT),
            subject="数字电子技术", index_status="indexed",
            knowledge_point_count=3, parse_progress=1.0,
            content=DOC_A_CONTENT, doc_type="raw",
        )
        b = Document(
            file_name=f"{PREFIX}-数电判断B.txt",
            file_path="qa-b.txt", file_type="txt", size=len(DOC_B_CONTENT),
            subject="数字电子技术", index_status="indexed",
            knowledge_point_count=1, parse_progress=1.0,
            content=DOC_B_CONTENT, doc_type="raw",
        )
        db.add_all([a, b])
        db.commit()
        created_ids = [a.id, b.id]
        created_files = [a.file_name, b.file_name]
        yield {"ids": created_ids, "files": created_files}
    finally:
        # 清理：删除本用例产生的题目（source 带唯一前缀）与文档
        # 物理删除闸门：quiz_questions 的 DELETE 不可逆，测试也不例外。
        # 本用例只删自己用唯一前缀创建的题目（范围可验证），因此在
        # 这里显式临时放行——测试环境本就需要这条路径可用。
        os.environ[ENV_FLAG] = ENV_ENABLED_VALUE
        try:
            require_physical_delete_enabled("quiz_questions")
            db.query(QuizQuestion).filter(
                QuizQuestion.source.like(f"知识库:{PREFIX}%")
            ).delete(synchronize_session=False)
        finally:
            os.environ.pop(ENV_FLAG, None)
        db.query(Document).filter(Document.id.in_(created_ids)).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()


def test_scan_detects_candidates_and_is_readonly(client, kb_docs):
    """scan 识别出候选，且不写库（行数不变）。"""
    before = _count_questions()

    r = client.post("/api/kb-import/scan", json={"doc_ids": kb_docs["ids"]})
    assert r.status_code == 200, r.text
    body = r.json()

    # 汇总字段
    assert body["scanned_docs"] == 2
    assert body["total_candidates"] >= 3, body
    assert "elapsed_seconds" in body
    assert isinstance(body["items"], list) and len(body["items"]) == 2

    by_doc = {it["doc_id"]: it for it in body["items"]}
    doc_a_id = kb_docs["ids"][0]
    a_item = by_doc[doc_a_id]
    assert a_item["doc_title"] == f"{PREFIX}-数电真题A.txt"
    # 文档 A 应识别出 3 道：2 填空 + 1 选择
    assert a_item["candidate_count"] == 3, a_item["candidates"]
    cands = a_item["candidates"]
    # index 从 0 起、连续
    assert [c["index"] for c in cands] == [0, 1, 2]
    # 字段映射齐全
    c0 = cands[0]
    for key in ("content", "question_type", "subject", "chapter",
                "knowledge_point", "difficulty", "content_hash"):
        assert key in c0
    assert c0["question_type"] == "fill"
    assert c0["subject"] == "数字电子技术"
    # 选择题带选项与答案
    c2 = cands[2]
    assert c2["question_type"] == "single"
    assert len(c2["options"]) == 4
    assert c2["answer"] == "B"

    # 只读红线：行数不变
    after = _count_questions()
    assert after == before, "scan 接口绝不允许写库"


def test_scan_filters_by_file_type(client, kb_docs):
    """file_type 必须真正过滤文档，而不是被静默忽略后扫全库。"""
    # 与 doc_ids 取交集：两篇 fixture 都是 txt，按 pdf 过滤应为 0
    r = client.post(
        "/api/kb-import/scan",
        json={"doc_ids": kb_docs["ids"], "file_type": "pdf"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scanned_docs"] == 0, body
    assert body["items"] == []
    assert body["file_type"] == "pdf"

    # 仅按类型：返回的文档数应等于库内该类型文档数，且包含两篇 fixture
    r2 = client.post("/api/kb-import/scan", json={"file_type": "txt"})
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["scanned_docs"] > 0
    assert set(kb_docs["ids"]).issubset({it["doc_id"] for it in body2["items"]})
    db = SessionLocal()
    try:
        expected = db.query(Document).filter(Document.source_format == "txt").count()
    finally:
        db.close()
    assert body2["scanned_docs"] == expected


def test_scan_rejects_unknown_file_type(client):
    """拼错的类型应 400，而不是返回一个看似成功的空结果。"""
    r = client.post("/api/kb-import/scan", json={"file_type": "exe"})
    assert r.status_code == 400, r.text
    assert "不支持的文件类型" in r.json()["message"]


def test_confirm_inserts_and_is_idempotent(client, kb_docs):
    """confirm 插入被勾选题；重复 confirm 不重复插入。"""
    doc_a_id = kb_docs["ids"][0]
    before = _count_questions()

    # 勾选文档 A 的第 0、2 题
    r = client.post(
        "/api/kb-import/confirm",
        json={"selected": [{"doc_id": doc_a_id, "index": 0},
                           {"doc_id": doc_a_id, "index": 2}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 2, body
    assert body["skipped_existing"] == 0
    assert body["by_subject"].get("数字电子技术") == 2

    after = _count_questions()
    assert after == before + 2, f"应插入 2 题：{before} -> {after}"

    # 落库字段抽查：source = 知识库:<文件名>
    db = SessionLocal()
    try:
        qs = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.source == f"知识库:{kb_docs['files'][0]}")
            .all()
        )
        assert len(qs) == 2
        for q in qs:
            assert q.question_type in ("fill", "single")
            assert q.subject == "数字电子技术"
    finally:
        db.close()

    # 重复 confirm 同一批 → 全部跳过，不新增
    r2 = client.post(
        "/api/kb-import/confirm",
        json={"selected": [{"doc_id": doc_a_id, "index": 0},
                           {"doc_id": doc_a_id, "index": 2}]},
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["inserted"] == 0, body2
    assert body2["skipped_existing"] == 2, body2
    assert _count_questions() == after


def test_confirm_accepts_doc_ids_candidate_indexes(client, kb_docs):
    """形式 B 入参 doc_ids + candidate_indexes 也能正确入库。"""
    doc_b_id = kb_docs["ids"][1]
    before = _count_questions()
    r = client.post(
        "/api/kb-import/confirm",
        json={"doc_ids": [doc_b_id], "candidate_indexes": [[0]]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 1, body
    assert _count_questions() == before + 1


def test_scan_doc_not_found_404(client):
    """scan 传入不存在的 doc_id → 404，且 detail 是人话（不是被改写的 Not Found）。"""
    r = client.post("/api/kb-import/scan", json={"doc_ids": [99999999]})
    assert r.status_code == 404
    assert "文档不存在" in r.json()["message"]


def test_confirm_doc_not_found_404(client):
    """confirm 传入不存在的 doc_id → 404。"""
    r = client.post(
        "/api/kb-import/confirm",
        json={"selected": [{"doc_id": 99999999, "index": 0}]},
    )
    assert r.status_code == 404
    assert "文档不存在" in r.json()["message"]


def test_confirm_no_selection_400(client):
    """confirm 未传任何选择 → 400（全局 HTTP 异常处理器返回 {code,message} 结构）。"""
    r = client.post("/api/kb-import/confirm", json={})
    assert r.status_code == 400, r.text
    body = r.json()
    assert body["code"] == "INVALID_PARAMETER"
    assert "selected" in body["message"] or "选择" in body["message"]
