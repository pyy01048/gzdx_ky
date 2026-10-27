# -*- coding: utf-8 -*-
"""P0-1 刷题生词提取 + P0-2 主观题批改 后端回归测试。

覆盖：
1. POST /api/quiz/{question_id}/extract-words
   - 从题干/选项/解析提取英文单词，去重、过滤停用词
   - 标注 exists（按当前用户词库精确匹配）
2. POST /api/words 查重（重复返回 409 + detail 含已有 id）
3. WordCreate.source_label 透传 tag；batch-import 透传 source_label
4. POST /api/quiz/submit 主观题不精确判分
   - 传 self_score 时 correct 按及格线；返回体含 is_subjective/self_score/max_score
   - 不传 self_score 时 correct=None、needs_review=True
5. POST /api/quiz/grade-subjective
   - 绑定题目上下文，返回 score/max_score/evaluation/reference_answer
"""
from __future__ import annotations

import uuid

import pytest

from database import SessionLocal
from models import QuizQuestion, Word
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)


def _make_english_question(db, subject="英语"):
    """创建一道含英文单词的英语题，返回 question_id。"""
    q = QuizQuestion(
        content="The ubiquitous smartphone has transformed modern life.",
        options=["ubiquitous", "rare", "common", "invisible"],
        answer="A",
        analysis="Ubiquitous means everywhere present.",
        subject=subject,
        chapter="QA-阅读", knowledge_point="QA-词汇",
        difficulty=2, source="模拟", question_type="single",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q.id


def _make_subjective_question(db, subject="数学"):
    """创建一道主观题（essay），返回 question_id。"""
    q = QuizQuestion(
        content="请论述微积分在工程中的应用。",
        options=None,
        answer="微积分是研究变化的数学工具，广泛应用于工程优化与建模。",
        analysis="从连续变化、极限、导数、积分等角度展开即可。",
        subject=subject,
        chapter="QA-高数", knowledge_point="QA-微积分",
        difficulty=3, source="自建", question_type="essay",
        answer_type="subjective",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q.id


# --------------------------------------------------------------------------- #
# P0-1：生词提取
# --------------------------------------------------------------------------- #
class TestExtractWords:
    def test_extract_words_shape_and_content(self, db_schema):  # noqa: ARG001
        db = SessionLocal()
        try:
            qid = _make_english_question(db)
        finally:
            db.close()

        resp = client.post(f"/api/quiz/{qid}/extract-words")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["question_id"] == qid
        assert isinstance(body["words"], list)
        words = [w["word"] for w in body["words"]]
        # 题干里的实词应被提取
        assert "ubiquitous" in words
        assert "smartphone" in words
        assert "transformed" in words
        assert "modern" in words
        # 停用词 the/has 等不应出现
        assert "the" not in words
        assert "has" not in words
        # 首次出现顺序去重：ubiquitous 在题干和选项都出现，只保留一次
        assert words.count("ubiquitous") == 1
        # 每个词带 exists/source 字段
        for item in body["words"]:
            assert set(item) >= {"word", "exists", "source"}
            assert isinstance(item["exists"], bool)

    def test_extract_words_exists_flag(self, db_schema):  # noqa: ARG001
        db = SessionLocal()
        try:
            qid = _make_english_question(db)
            # 预置当前测试用户词库中已有 ubiquitous
            if not db.query(Word).filter(Word.word == "ubiquitous").first():
                db.add(Word(word="ubiquitous", meaning="无处不在",
                            status="not_mastered", user_id=0))
                db.commit()
        finally:
            db.close()

        resp = client.post(f"/api/quiz/{qid}/extract-words")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ub = next(w for w in body["words"] if w["word"] == "ubiquitous")
        assert ub["exists"] is True
        # smartphone 不应在词库
        sp = next(w for w in body["words"] if w["word"] == "smartphone")
        assert sp["exists"] is False

    def test_extract_words_nonexistent_question(self, db_schema):  # noqa: ARG001
        resp = client.post("/api/quiz/99999999/extract-words")
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# P0-1：create_word 查重 + source_label 透传
# --------------------------------------------------------------------------- #
class TestCreateWordDedup:
    def _cleanup(self, word):
        db = SessionLocal()
        try:
            db.query(Word).filter(Word.word == word, Word.user_id == 0).delete(
                synchronize_session=False)
            db.commit()
        finally:
            db.close()

    def test_create_word_duplicate_returns_409(self, db_schema):  # noqa: ARG001
        word = f"dupword{uuid.uuid4().hex[:8]}"
        self._cleanup(word)
        payload = {"word": word, "meaning": "重复测试词"}
        try:
            r1 = client.post("/api/words", json=payload)
            assert r1.status_code == 200, r1.text
            rid = r1.json()["id"]

            r2 = client.post("/api/words", json=payload)
            assert r2.status_code == 409, (
                f"重复创建应 409，实际 {r2.status_code}: {r2.text}"
            )
            detail = r2.json()["detail"]
            assert detail["exists"] is True
            assert detail["word"] == word
            assert detail["id"] == rid
        finally:
            self._cleanup(word)

    def test_create_word_source_label_writes_tag(self, db_schema):  # noqa: ARG001
        word = f"sourcelabel{uuid.uuid4().hex[:8]}"
        self._cleanup(word)
        try:
            resp = client.post("/api/words", json={
                "word": word,
                "meaning": "来源标注测试",
                "source_label": "刷题生词",
            })
            assert resp.status_code == 200, resp.text
            assert resp.json()["tag"] == "刷题生词"
        finally:
            self._cleanup(word)

    def test_create_word_source_label_keeps_existing_tag(self, db_schema):  # noqa: ARG001
        word = f"sourcetag{uuid.uuid4().hex[:8]}"
        self._cleanup(word)
        try:
            resp = client.post("/api/words", json={
                "word": word,
                "meaning": "来源标注测试",
                "tag": "高频",
                "source_label": "刷题生词",
            })
            assert resp.status_code == 200, resp.text
            assert resp.json()["tag"] == "高频"
        finally:
            self._cleanup(word)

    def test_batch_import_source_label(self, db_schema):  # noqa: ARG001
        w1 = f"batchsrc{uuid.uuid4().hex[:8]}"
        w2 = f"batchsrc2{uuid.uuid4().hex[:8]}"
        db = SessionLocal()
        try:
            db.query(Word).filter(Word.word.in_([w1, w2]), Word.user_id == 0).delete(
                synchronize_session=False)
            db.commit()
        finally:
            db.close()
        try:
            resp = client.post("/api/words/batch-import", json={
                "words": [
                    {"word": w1, "meaning": "批量1", "source_label": "刷题生词"},
                    {"word": w2, "meaning": "批量2"},
                ]
            })
            assert resp.status_code == 200, resp.text
            assert resp.json()["imported"] == 2
            db = SessionLocal()
            try:
                row1 = db.query(Word).filter(Word.word == w1, Word.user_id == 0).first()
                row2 = db.query(Word).filter(Word.word == w2, Word.user_id == 0).first()
                assert row1 is not None and row1.tag == "刷题生词"
                assert row2 is not None and row2.tag is None
            finally:
                db.close()
        finally:
            db = SessionLocal()
            try:
                db.query(Word).filter(Word.word.in_([w1, w2]), Word.user_id == 0).delete(
                    synchronize_session=False)
                db.commit()
            finally:
                db.close()


# --------------------------------------------------------------------------- #
# P0-2：主观题 submit 不精确判分
# --------------------------------------------------------------------------- #
class TestSubmitSubjective:
    def _make_subjective(self):
        db = SessionLocal()
        try:
            return _make_subjective_question(db)
        finally:
            db.close()

    def test_submit_subjective_with_self_score(self, db_schema):  # noqa: ARG001
        qid = self._make_subjective()
        # self_score=8, max_score=10，及格线 6 → correct=True
        resp = client.post("/api/quiz/submit", json={
            "question_id": qid,
            "my_answer": "微积分在工程中有广泛应用。",
            "self_score": 8,
            "max_score": 10,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_subjective"] is True
        assert body["question_type"] == "essay"
        assert body["self_score"] == 8
        assert body["max_score"] == 10
        assert body["correct"] is True

    def test_submit_subjective_below_passing(self, db_schema):  # noqa: ARG001
        qid = self._make_subjective()
        resp = client.post("/api/quiz/submit", json={
            "question_id": qid,
            "my_answer": "不知道。",
            "self_score": 3,
            "max_score": 10,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_subjective"] is True
        assert body["correct"] is False

    def test_submit_subjective_without_self_score(self, db_schema):  # noqa: ARG001
        qid = self._make_subjective()
        resp = client.post("/api/quiz/submit", json={
            "question_id": qid,
            "my_answer": "微积分是重要工具。",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_subjective"] is True
        assert body["correct"] is None
        assert body["needs_review"] is True

    def test_submit_objective_still_exact_match(self, db_schema):  # noqa: ARG001
        db = SessionLocal()
        try:
            qid = _make_english_question(db)
        finally:
            db.close()
        # 正确答案 A
        resp = client.post("/api/quiz/submit", json={
            "question_id": qid,
            "my_answer": "A",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_subjective"] is False
        assert body["correct"] is True


# --------------------------------------------------------------------------- #
# P0-2：grade-subjective AI 批改端点
# --------------------------------------------------------------------------- #
class TestGradeSubjective:
    def test_grade_subjective_shape(self, db_schema):  # noqa: ARG001
        db = SessionLocal()
        try:
            qid = _make_subjective_question(db)
        finally:
            db.close()
        resp = client.post("/api/quiz/grade-subjective", json={
            "question_id": qid,
            "my_answer": "微积分研究变化率与累积量，工程中用于优化设计。",
            "max_score": 10,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["question_id"] == qid
        assert "max_score" in body
        assert "evaluation" in body
        assert "reference_answer" in body
        # score 可能为 None（LLM 不可用降级），也可能是数字
        assert body["score"] is None or isinstance(body["score"], (int, float))

    def test_grade_subjective_missing_question(self, db_schema):  # noqa: ARG001
        resp = client.post("/api/quiz/grade-subjective", json={
            "question_id": 99999999,
            "my_answer": "测试",
        })
        assert resp.status_code == 404