# -*- coding: utf-8 -*-
"""个人题库 HTTP 契约测试（TDD RED，不实现业务代码）。

测试边界：
- 复用 conftest 的隔离测试库、同步 ASGI ``client`` 与 ``current_user`` override；
  本机 Starlette/httpx 版本不兼容原生 TestClient，故使用 conftest 的等价同步门面。
- 只 import 现有 User/QuizQuestion 模型，不 import 任何尚不存在的个人题库 ORM。
- 所有业务断言经 HTTP 驱动；SQL 仅用于播种公共题、检查答题留痕/软删除及 best-effort 清理。
- 固定普通用户 99201/99202；每个用例的唯一标记隔离题库名、题干与清理范围。
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from database import SessionLocal
from sqlalchemy import event, inspect, text
from utils.security import current_user, optional_user
from utils.timeutil import local_today

from models import (
    AnswerRecord,
    ErrorKnowledgeLink,
    ErrorRecord,
    KnowledgePoint,
    QuizQuestion,
    QuizQuestionState,
    User,
)

_UID_BASE = 1_000_000_000 + int(uuid.uuid4().hex[:8], 16) % 1_000_000_000
UID_A = _UID_BASE
UID_B = _UID_BASE + 1
SETS = "/api/quiz/personal/sets"
QUESTIONS = "/api/quiz/personal/questions"
PRACTICE = "/api/quiz/personal/practice"


def _principal(uid: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        username=f"pqc_{uid}",
        display_name=f"pqc_{uid}",
        role="user",
        is_active=True,
        must_change_password=False,
        token_version=0,
        last_login_at=None,
        created_at=None,
    )


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _cleanup_test_rows(db, marker: str) -> None:
    """SQL best-effort 清理：只命中固定测试 UID 或唯一题干/题库标记。"""
    db.rollback()
    try:
        table_names = inspect(db.get_bind()).get_table_names()
    except Exception:
        return

    columns = {}
    for table in table_names:
        try:
            columns[table] = {col["name"] for col in inspect(db.get_bind()).get_columns(table)}
        except Exception:
            columns[table] = set()

    # 先清答题/错题/复习子表；其余含 user_id 的个人表按两轮拓扑无关顺序 best-effort 清理。
    priority = [
        "error_knowledge_links",
        "answer_records",
        "error_records",
        "review_records",
        "review_schedules",
        "study_events",
        "study_stats",
    ]
    owned_tables = [table for table in table_names if table != "users" and "user_id" in columns.get(table, set())]
    ordered = [t for t in priority if t in owned_tables]
    ordered.extend(sorted(set(owned_tables) - set(ordered)))
    params = {"uid_a": UID_A, "uid_b": UID_B}

    for _ in range(2):
        for table in ordered:
            try:
                db.execute(
                    text(f"DELETE FROM {_quoted(table)} WHERE user_id IN (:uid_a, :uid_b)"),
                    params,
                )
                db.commit()
            except Exception:
                db.rollback()

    # 公共题没有 user_id；个人自建题若落在独立表，也由唯一 content 标记回收。
    for table in table_names:
        if "content" not in columns.get(table, set()):
            continue
        try:
            db.execute(
                text(f"DELETE FROM {_quoted(table)} WHERE content = :content OR content LIKE :prefix"),
                {"content": marker, "prefix": f"{marker}%"},
            )
            db.commit()
        except Exception:
            db.rollback()


@pytest.fixture()
def pq(app_module, db_schema, client):  # noqa: ARG001 - db_schema/client 负责建表与同步 ASGI 门面
    """双普通用户 + 两道可见公共题；不创建任何个人题库资产。"""
    db = SessionLocal()
    marker = f"PQC-{uuid.uuid4().hex[:12]}"
    dependencies = (current_user, optional_user)
    saved = {dep: app_module.dependency_overrides.get(dep) for dep in dependencies}

    def login(uid: int) -> None:
        principal = _principal(uid)
        app_module.dependency_overrides[current_user] = lambda: principal
        app_module.dependency_overrides[optional_user] = lambda: principal

    try:
        for uid in (UID_A, UID_B):
            if db.get(User, uid) is None:
                db.add(
                    User(
                        id=uid,
                        username=f"pqc_{uid}",
                        password_hash="!disabled-personal-quiz-contract",
                        display_name=f"pqc_{uid}",
                        role="user",
                        is_active=True,
                        must_change_password=False,
                        token_version=0,
                    )
                )
        db.commit()

        common = {
            "options": [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
            "answer": "A",
            "analysis": f"{marker} 公共题解析",
            "difficulty": 2,
            "source_label": "个人题库契约测试",
            "source_kind": "external_import",
            "answer_type": "objective",
            "answer_confidence": 1.0,
            "is_available": True,
            "is_junk": False,
            "question_type": "single",
        }
        public_math = QuizQuestion(
            **common,
            content=f"{marker} 公共数学题",
            subject="数学",
            chapter="公共第一章",
        )
        public_english = QuizQuestion(
            **{**common, "answer": "B"},
            content=f"{marker} 公共英语题",
            subject="英语",
            chapter="公共第二章",
        )
        db.add_all([public_math, public_english])
        db.commit()
        public_math_id = public_math.id
        public_english_id = public_english.id
        # T2 内容可用性门禁：trg_quiz_questions_gate 触发器在 INSERT 时因
        # subject_id IS NULL 等条件设 validation_status='warn'。出题接口只返回
        # validation_status='pass' 的题，这里用 SQL 直接置 pass（UPDATE
        # validation_status 不触发该触发器，因其只监听 content/options/answer
        # 等列的变更），让公共题能被出题接口召回。
        db.execute(
            text("UPDATE quiz_questions SET validation_status = 'pass' WHERE id IN (:a, :b)"),
            {"a": public_math_id, "b": public_english_id},
        )
        db.commit()

        login(UID_A)
        yield SimpleNamespace(
            api=client,
            db=db,
            marker=marker,
            login=login,
            public_math_id=public_math_id,
            public_english_id=public_english_id,
        )
    finally:
        for dep, previous in saved.items():
            if previous is None:
                app_module.dependency_overrides.pop(dep, None)
            else:
                app_module.dependency_overrides[dep] = previous
        _cleanup_test_rows(db, marker)
        db.close()


def _ok(response) -> dict:
    assert 200 <= response.status_code < 300, (
        f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text}"
    )
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


def _create_bank(api, name: str, description: str | None = None) -> int:
    payload = {"name": name}
    if description is not None:
        payload["description"] = description
    body = _ok(api.post(SETS, json=payload))
    bank_id = body.get("id")
    assert isinstance(bank_id, int), body
    return bank_id


def _create_question(api, marker: str, **overrides) -> int:
    payload = {
        "content": f"{marker} 契约自建题",
        "options": ["A.甲", "B.乙"],
        "answer": "A",
        "analysis": f"{marker} 初始解析",
        "subject": "数学",
        "chapter": "第一章",
        "question_type": "single",
        "difficulty": 2,
    }
    payload.update(overrides)
    body = _ok(api.post(QUESTIONS, json=payload))
    question_id = body.get("id")
    assert isinstance(question_id, int), body
    # T2 内容可用性门禁：出题接口只返回 validation_status='pass' 的题。
    # API 创建时默认 'pending'，这里用 SQL 直接置 pass 模拟校验门通过，
    # 否则后续 GET /questions 因门禁过滤返回空，断言全挂。
    _mark_validation_pass(question_id)
    return question_id


def _mark_validation_pass(question_id: int) -> None:
    """把题的 validation_status 置 'pass'，模拟校验门通过（T2 契约）。

    trg_quiz_questions_gate 触发器只在 UPDATE OF content/options/answer/...
    时触发，单独 UPDATE validation_status 不会被覆盖。
    """
    db = SessionLocal()
    try:
        db.execute(
            text("UPDATE quiz_questions SET validation_status = 'pass' WHERE id = :qid"),
            {"qid": question_id},
        )
        db.commit()
    finally:
        db.close()


def _questions(api, **params) -> dict:
    body = _ok(api.get(QUESTIONS, params=params))
    assert set(body) >= {"items", "total", "page", "page_size", "summary"}, body
    assert set(body["summary"]) >= {"total", "mastered", "unmastered"}, body
    return body


def _ids(body: dict) -> set[int]:
    return {item["id"] for item in body["items"]}


def _global_ids(body: dict) -> set[int]:
    # 现有全局列表使用 questions；保留 items 兼容，避免把返回壳形状当业务实现细节。
    items = body.get("questions", body.get("items", []))
    return {item["id"] for item in items}


def _set_mastery(api, question_id: int, state: str) -> None:
    _ok(api.put(f"{QUESTIONS}/{question_id}/mastery", json={"mastery_state": state}))


def _question_row_count(db, content: str) -> int:
    """不依赖个人题 ORM/表名，确认软删除后唯一题干行仍存在。"""
    total = 0
    for table in inspect(db.get_bind()).get_table_names():
        if "question" not in table.lower():
            continue
        try:
            cols = {col["name"] for col in inspect(db.get_bind()).get_columns(table)}
        except Exception:
            continue
        if "content" not in cols:
            continue
        try:
            total += int(
                db.execute(
                    text(f"SELECT COUNT(*) FROM {_quoted(table)} WHERE content = :content"),
                    {"content": content},
                ).scalar()
                or 0
            )
        except Exception:
            db.rollback()
    return total


def test_new_user_gets_honest_empty_views_without_template_bank(pq):
    pq.login(UID_B)
    assert _ok(pq.api.get(SETS)) == {"items": [], "total": 0}

    body = _questions(pq.api)
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1 and body["page_size"] == 20
    assert body["summary"] == {"total": 0, "mastered": 0, "unmastered": 0}
    assert _ok(pq.api.get(PRACTICE)) == {"items": [], "total": 0}


def test_bank_crud_and_cross_account_isolation(pq):
    api = pq.api
    pq.login(UID_A)
    name = f"{pq.marker}-题库"
    bank_id = _create_bank(api, name, "初始描述")

    banks = _ok(api.get(SETS))
    assert banks["total"] == 1
    assert banks["items"][0]["id"] == bank_id
    assert banks["items"][0]["name"] == name

    pq.login(UID_B)
    assert _ok(api.get(SETS)) == {"items": [], "total": 0}
    assert api.put(f"{SETS}/{bank_id}", json={"name": "越权改名"}).status_code == 404
    assert api.delete(f"{SETS}/{bank_id}").status_code == 404
    assert api.post(f"{SETS}/{bank_id}/items", json={"question_id": pq.public_math_id}).status_code == 404

    pq.login(UID_A)
    _ok(api.post(f"{SETS}/{bank_id}/items", json={"question_id": pq.public_math_id}))
    pq.login(UID_B)
    assert api.delete(f"{SETS}/{bank_id}/items/{pq.public_math_id}").status_code == 404

    pq.login(UID_A)
    renamed = f"{pq.marker}-改名"
    _ok(api.put(f"{SETS}/{bank_id}", json={"name": renamed, "description": "更新描述"}))
    bank = _ok(api.get(SETS))["items"][0]
    assert bank["name"] == renamed and bank["description"] == "更新描述"

    _ok(api.delete(f"{SETS}/{bank_id}/items/{pq.public_math_id}"))
    assert _questions(api)["total"] == 0
    public_detail = api.get(f"/api/quiz/questions/{pq.public_math_id}")
    assert public_detail.status_code == 200, public_detail.text

    # 删库必须级联移除成员关系，但不能删除公共题本体。
    _ok(api.post(f"{SETS}/{bank_id}/items", json={"question_id": pq.public_math_id}))
    _ok(api.delete(f"{SETS}/{bank_id}"))
    assert _ok(api.get(SETS)) == {"items": [], "total": 0}
    assert _questions(api)["total"] == 0
    assert api.get(f"/api/quiz/questions/{pq.public_math_id}").status_code == 200
    assert api.delete(f"{SETS}/{bank_id}").status_code == 404


def test_public_question_membership_is_idempotent_and_does_not_delete_question(pq):
    api = pq.api
    pq.login(UID_A)
    bank_a = _create_bank(api, f"{pq.marker}-A库")
    for _ in range(2):
        _ok(api.post(f"{SETS}/{bank_a}/items", json={"question_id": pq.public_math_id}))
    body = _questions(api)
    assert body["total"] == 1 and _ids(body) == {pq.public_math_id}

    pq.login(UID_B)
    bank_b = _create_bank(api, f"{pq.marker}-B库")
    _ok(api.post(f"{SETS}/{bank_b}/items", json={"question_id": pq.public_math_id}))
    assert _ids(_questions(api)) == {pq.public_math_id}

    pq.login(UID_A)
    _ok(api.delete(f"{SETS}/{bank_a}/items/{pq.public_math_id}"))
    assert _questions(api)["total"] == 0
    pq.login(UID_B)
    assert _ids(_questions(api)) == {pq.public_math_id}

    pq.login(UID_A)
    listing = _ok(api.get("/api/quiz/questions", params={"q": pq.marker}))
    assert pq.public_math_id in _global_ids(listing)
    assert api.get(f"/api/quiz/questions/{pq.public_math_id}").status_code == 200


def test_self_created_options_normalize_partial_edit_and_soft_delete(pq):
    api = pq.api
    pq.login(UID_A)
    bank_id = _create_bank(api, f"{pq.marker}-自建题库")
    string_content = f"{pq.marker} 字符串选项自建题"
    object_content = f"{pq.marker} 对象选项自建题"
    string_id = _create_question(
        api,
        pq.marker,
        content=string_content,
        bank_id=bank_id,
        options=["A.甲", "B.乙"],
    )
    object_id = _create_question(
        api,
        pq.marker,
        content=object_content,
        bank_id=bank_id,
        options=[{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}],
        answer="B",
        subject="英语",
        chapter="第二章",
    )

    body = _questions(api)
    assert body["total"] == 2
    items = {item["id"]: item for item in body["items"]}
    canonical = [{"key": "A", "text": "甲"}, {"key": "B", "text": "乙"}]
    assert items[string_id]["options"] == canonical
    assert items[object_id]["options"] == canonical
    assert items[object_id]["answer"] == "B"

    _ok(api.put(f"{QUESTIONS}/{string_id}", json={"analysis": "只更新解析"}))
    _mark_validation_pass(string_id)
    edited = _questions(api, q=string_content)["items"][0]
    assert edited["analysis"] == "只更新解析"
    assert edited["content"] == string_content
    assert edited["options"] == canonical and edited["answer"] == "A"

    _ok(api.put(f"{QUESTIONS}/{string_id}", json={"bank_id": None, "analysis": "不调整题库"}))
    _mark_validation_pass(string_id)
    assert _ids(_questions(api, bank_id=bank_id)) == {string_id, object_id}

    _ok(api.delete(f"{QUESTIONS}/{string_id}"))
    assert _questions(api, q=string_content)["total"] == 0
    assert _questions(api)["total"] == 1
    assert _question_row_count(pq.db, string_content) == 1

    pq.login(UID_B)
    assert _questions(api)["total"] == 0
    assert api.put(f"{QUESTIONS}/{object_id}", json={"analysis": "越权"}).status_code == 404
    assert api.delete(f"{QUESTIONS}/{object_id}").status_code == 404


def test_combined_filters_pagination_and_summary(pq):
    api = pq.api
    pq.login(UID_A)
    bank_id = _create_bank(api, f"{pq.marker}-筛选库")
    single_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 组合筛选唯一题",
        bank_id=bank_id,
        subject="数学",
        chapter="第一章",
        question_type="single",
    )
    multiple_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 多选题",
        bank_id=bank_id,
        options=["A.甲", "B.乙", "C.丙", "D.丁"],
        answer="AB",
        question_type="multiple",
    )
    essay_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 英语论述题",
        bank_id=bank_id,
        options=None,
        answer="参考答案",
        subject="英语",
        chapter="第二章",
        question_type="essay",
    )
    judge_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 判断题",
        bank_id=bank_id,
        options=None,
        answer="正确",
        chapter="第二章",
        question_type="judge",
    )
    for question_id in (pq.public_math_id, pq.public_english_id):
        _ok(api.post(f"{SETS}/{bank_id}/items", json={"question_id": question_id}))

    body = _questions(api)
    assert body["total"] == 6
    assert body["summary"] == {"total": 6, "mastered": 0, "unmastered": 6}

    _set_mastery(api, single_id, "mastered")
    _set_mastery(api, pq.public_math_id, "mastered")
    assert _questions(api)["summary"] == {"total": 6, "mastered": 2, "unmastered": 4}

    combined = _questions(
        api,
        bank_id=bank_id,
        subject="数学",
        chapter="第一章",
        question_type="single",
        q="组合筛选唯一题",
    )
    assert combined["total"] == 1 and _ids(combined) == {single_id}

    mastered = _questions(api, bank_id=bank_id, mastery_state="mastered")
    assert mastered["total"] == 2 and _ids(mastered) == {single_id, pq.public_math_id}
    unmastered = _questions(api, bank_id=bank_id, mastery_state="unmastered")
    assert unmastered["total"] == 4
    assert _ids(unmastered) == {multiple_id, essay_id, judge_id, pq.public_english_id}

    page_two = _questions(api, bank_id=bank_id, page=2, page_size=1)
    assert page_two["total"] == 6
    assert page_two["page"] == 2 and page_two["page_size"] == 1
    assert len(page_two["items"]) == 1


def test_practice_filters_and_never_leaks_answer_or_analysis(pq):
    api = pq.api
    pq.login(UID_A)
    bank_id = _create_bank(api, f"{pq.marker}-练习库")
    own_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 练习自建题",
        bank_id=bank_id,
        analysis="绝不能出现在练习列表的解析",
    )
    essay_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 练习英语题",
        bank_id=bank_id,
        subject="英语",
        chapter="第二章",
        question_type="essay",
        options=None,
        answer="英语参考答案",
    )
    _ok(api.post(f"{SETS}/{bank_id}/items", json={"question_id": pq.public_math_id}))

    body = _ok(api.get(PRACTICE, params={"bank_id": bank_id, "limit": 20}))
    assert body["total"] == 3 and len(body["items"]) == 3
    assert {item["id"] for item in body["items"]} == {own_id, essay_id, pq.public_math_id}
    for item in body["items"]:
        assert "answer" not in item and "analysis" not in item

    limited = _ok(api.get(PRACTICE, params={"bank_id": bank_id, "limit": 1}))
    assert limited["total"] == 3 and len(limited["items"]) == 1
    assert "answer" not in limited["items"][0] and "analysis" not in limited["items"][0]

    _set_mastery(api, own_id, "mastered")
    filtered = _ok(
        api.get(
            PRACTICE,
            params={
                "bank_id": bank_id,
                "mastery_state": "unmastered",
                "subject": "数学",
                "chapter": "公共第一章",
                "question_type": "single",
                "limit": 1,
            },
        )
    )
    assert filtered["total"] == 1
    assert [item["id"] for item in filtered["items"]] == [pq.public_math_id]
    assert "answer" not in filtered["items"][0] and "analysis" not in filtered["items"][0]

    pq.login(UID_B)
    assert _ok(api.get(PRACTICE, params={"bank_id": bank_id})) == {"items": [], "total": 0}


def test_objective_submit_auto_mastery_and_manual_override_are_per_user(pq):
    api = pq.api
    pq.login(UID_A)
    bank_id = _create_bank(api, f"{pq.marker}-掌握库")
    _ok(api.post(f"{SETS}/{bank_id}/items", json={"question_id": pq.public_math_id}))
    own_id = _create_question(api, pq.marker, content=f"{pq.marker} 自动掌握题", bank_id=bank_id)

    correct = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": pq.public_math_id, "my_answer": "A", "mode": "personal"},
        )
    )
    assert correct["correct"] is True
    assert correct["correct_answer"] == "A" and correct["analysis"]
    mastered = _questions(api, mastery_state="mastered")
    assert _ids(mastered) == {pq.public_math_id}

    wrong = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": own_id, "my_answer": "B", "mode": "personal"},
        )
    )
    assert wrong["correct"] is False
    assert wrong["correct_answer"] == "A" and wrong["analysis"]
    assert _ids(_questions(api, mastery_state="unmastered")) == {own_id}

    _set_mastery(api, own_id, "mastered")
    assert _ids(_questions(api, mastery_state="mastered")) == {own_id, pq.public_math_id}
    _set_mastery(api, own_id, "unmastered")
    assert _ids(_questions(api, mastery_state="unmastered")) == {own_id}

    pq.login(UID_B)
    own_bank = _create_bank(api, f"{pq.marker}-B掌握库")
    _ok(api.post(f"{SETS}/{own_bank}/items", json={"question_id": pq.public_math_id}))
    assert _ids(_questions(api, mastery_state="unmastered")) == {pq.public_math_id}


def test_subjective_submit_without_self_score_keeps_manual_mastery(pq):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 主观题",
        options=None,
        answer="主观题参考答案",
        analysis="主观题解析",
        question_type="essay",
    )
    _set_mastery(api, question_id, "mastered")

    result = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": question_id, "my_answer": "我的主观作答", "mode": "personal"},
        )
    )
    assert result["correct"] is None
    assert result["correct_answer"] == "主观题参考答案"
    assert result["analysis"] == "主观题解析"
    assert _ids(_questions(api, mastery_state="mastered")) == {question_id}


def test_private_question_is_invisible_globally_and_cross_account_actions_404(pq):
    api = pq.api
    pq.login(UID_A)
    private_content = f"{pq.marker} 跨账号私有题"
    private_id = _create_question(api, pq.marker, content=private_content)

    pq.login(UID_B)
    listing_response = api.get("/api/quiz/questions", params={"q": pq.marker})
    listing = _ok(listing_response)
    visible_ids = _global_ids(listing)
    assert private_id not in visible_ids and private_content not in listing_response.text
    assert pq.public_math_id in visible_ids and pq.public_english_id in visible_ids

    detail = api.get(f"/api/quiz/questions/{private_id}")
    assert detail.status_code == 404 and private_content not in detail.text
    assert api.get(f"/api/quiz/questions/{pq.public_math_id}").status_code == 200
    assert api.put(f"{QUESTIONS}/{private_id}", json={"analysis": "越权修改"}).status_code == 404
    assert api.delete(f"{QUESTIONS}/{private_id}").status_code == 404
    assert api.put(f"{QUESTIONS}/{private_id}/mastery", json={"mastery_state": "mastered"}).status_code == 404
    submit = api.post(
        "/api/quiz/submit",
        json={"question_id": private_id, "my_answer": "A", "mode": "personal"},
    )
    assert submit.status_code == 404 and private_content not in submit.text

    pq.db.expire_all()
    records = pq.db.execute(
        text("SELECT COUNT(*) FROM answer_records WHERE user_id = :uid AND question_id = :qid"),
        {"uid": UID_B, "qid": private_id},
    ).scalar()
    assert records == 0, "越权提交不得产生 answer_record"

    pq.login(UID_A)
    item = _questions(api, q=private_content)["items"][0]
    assert item["id"] == private_id and item["analysis"] == f"{pq.marker} 初始解析"


def test_personal_answer_update_is_normalized_and_invalid_update_is_atomic(pq):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(
        api,
        pq.marker,
        options=["A.甲", "B.乙", "C.丙", "D.丁"],
        answer="A",
        question_type="multiple",
    )
    invalid = api.put(f"{QUESTIONS}/{question_id}", json={"answer": "AZ"})
    assert invalid.status_code == 400
    assert _questions(api)["items"][0]["answer"] == "A"

    normalized = _ok(api.put(f"{QUESTIONS}/{question_id}", json={"answer": " b, a, B "}))
    assert normalized["answer"] == "AB"
    result = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": question_id, "my_answer": "BA", "mode": "personal"},
        )
    )
    assert result["correct"] is True


def test_personal_judge_gets_usable_options_and_canonical_answer(pq):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(
        api,
        pq.marker,
        options=None,
        answer="T",
        question_type="judge",
    )
    item = _questions(api)["items"][0]
    assert item["answer"] == "A"
    assert item["options"] == [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]
    practice = _ok(api.get(PRACTICE, params={"question_type": "judge"}))["items"][0]
    assert practice["id"] == question_id and len(practice["options"]) == 2
    result = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": question_id, "my_answer": "A", "mode": "personal"},
        )
    )
    assert result["correct"] is True


@pytest.mark.parametrize(
    "score_fields",
    [
        {"self_score": -1, "max_score": 10},
        {"self_score": 11, "max_score": 10},
        {"self_score": 1, "max_score": 0},
        {"self_score": 1, "max_score": -1},
        {"self_score": "NaN", "max_score": 10},
        {"self_score": "Infinity", "max_score": 10},
        {"self_score": 1, "max_score": "NaN"},
    ],
    ids=["negative", "above-max", "zero-max", "negative-max", "nan-score", "infinite-score", "nan-max"],
)
def test_invalid_subjective_score_is_rejected_without_answer_record(pq, score_fields):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(
        api,
        pq.marker,
        options=None,
        answer="主观参考答案",
        question_type="essay",
    )
    response = api.post(
        "/api/quiz/submit",
        json={"question_id": question_id, "my_answer": "我的答案", "mode": "personal", **score_fields},
    )
    assert response.status_code == 400, response.text
    assert (
        pq.db.execute(
            text("SELECT COUNT(*) FROM answer_records WHERE user_id = :uid AND question_id = :qid"),
            {"uid": UID_A, "qid": question_id},
        ).scalar()
        == 0
    )
    state = pq.db.get(QuizQuestionState, (UID_A, question_id))
    assert state is None


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"answer": None}, "缺少答案"),
        (
            {"options": [{"key": "A", "text": "甲"}, {"key": "A", "text": "乙"}]},
            "选项 key 重复",
        ),
        ({"question_type": "not-a-question-type"}, "题型非法"),
        ({"answer": ""}, "答案空串"),
        ({"answer": "C"}, "单选答案不在选项中"),
        ({"question_type": "multiple", "answer": "AZ"}, "多选答案含非法选项"),
        ({"question_type": "judge", "answer": "不知道", "options": None}, "判断答案非法"),
        (
            {
                "question_type": "judge",
                "answer": "A",
                "options": [{"key": "A", "text": "错误"}, {"key": "B", "text": "正确"}],
            },
            "判断题语义与选项 key 相反",
        ),
    ],
    ids=[
        "missing-answer",
        "duplicate-option-key",
        "invalid-question-type",
        "blank-answer",
        "single-answer-key",
        "multiple-answer-key",
        "judge-answer",
        "reversed-judge-semantics",
    ],
)
def test_invalid_self_created_question_is_rejected_without_creating_asset(pq, override, reason):
    pq.login(UID_A)
    payload = {
        "content": f"{pq.marker} 非法自建题",
        "options": ["A.甲", "B.乙"],
        "answer": "A",
        "question_type": "single",
    }
    payload.update(override)
    response = pq.api.post(QUESTIONS, json=payload)
    assert response.status_code in (400, 422), f"{reason}: {response.status_code} {response.text}"
    assert _questions(pq.api, q=pq.marker)["total"] == 0


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/api/ai/tutoring/explain", {"question_id": None, "angle": "solution"}),
        ("post", "/api/ai/tutoring/followup", {"question_id": None, "message": "继续讲解"}),
        ("post", "/api/ai/tutoring/stuck", {"question_id": None}),
        ("post", "/api/ai/tutoring/orchestrated", {"question_id": None}),
        ("post", "/api/quiz/grade-subjective", {"question_id": None, "my_answer": "我的答案"}),
        ("get", "/api/quiz/export", None),
    ],
    ids=["explain", "followup", "stuck", "orchestrated", "subjective-grader", "csv-export"],
)
def test_private_question_is_denied_at_ai_and_export_entrypoints(pq, method, path, payload):
    api = pq.api
    pq.login(UID_A)
    private_content = f"{pq.marker} AI与导出私有题"
    private_id = _create_question(
        api,
        pq.marker,
        content=private_content,
        question_type="essay",
        options=None,
        answer="私有参考答案",
    )
    request_payload = dict(payload) if payload is not None else None
    if request_payload is not None:
        request_payload["question_id"] = private_id

    pq.login(UID_B)
    kwargs = {"params": {"q": pq.marker}} if path.endswith("/export") else {"json": request_payload}
    response = getattr(api, method)(path, **kwargs)
    if path.endswith("/export"):
        assert response.status_code == 200, response.text
        assert private_content not in response.text and "私有参考答案" not in response.text
        assert f"{pq.marker} 公共数学题" in response.text
    else:
        assert response.status_code == 404, f"{path}: {response.status_code} {response.text}"
        assert private_content not in response.text and "私有参考答案" not in response.text


def test_low_confidence_answer_is_needs_review_without_wrong_book_or_mastery_change(pq):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(api, pq.marker, content=f"{pq.marker} 低置信客观题")
    _set_mastery(api, question_id, "mastered")
    pq.db.query(QuizQuestion).filter(QuizQuestion.id == question_id).update(
        {QuizQuestion.answer_confidence: 0.5}, synchronize_session=False
    )
    pq.db.commit()
    _mark_validation_pass(question_id)

    result = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": question_id, "my_answer": "B", "mode": "personal"},
        )
    )
    assert result["needs_review"] is True
    assert result["correct"] is None
    item = _questions(api)["items"][0]
    assert item["mastery_state"] == "mastered"
    assert item["attempts"] == 1 and item["last_result"] is None
    errors = pq.db.execute(
        text("SELECT COUNT(*) FROM error_records WHERE user_id = :uid AND question_id = :qid"),
        {"uid": UID_A, "qid": question_id},
    ).scalar()
    assert errors == 0


def test_public_question_picker_excludes_owned_questions(pq):
    api = pq.api
    pq.login(UID_A)
    private_id = _create_question(api, pq.marker, content=f"{pq.marker} 公共选择器私有题")

    all_items = _ok(api.get("/api/quiz/questions", params={"q": pq.marker, "page_size": 100}))
    assert private_id in _global_ids(all_items)

    public_items = _ok(
        api.get(
            "/api/quiz/questions",
            params={"q": pq.marker, "page_size": 100, "public_only": True},
        )
    )
    ids = _global_ids(public_items)
    assert private_id not in ids
    assert {pq.public_math_id, pq.public_english_id} <= ids


def test_needs_review_is_excluded_from_accuracy_denominators(pq):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(api, pq.marker, content=f"{pq.marker} 混合判分统计题")
    for answer in ("A", "B"):
        _ok(api.post("/api/quiz/submit", json={"question_id": question_id, "my_answer": answer}))
    pq.db.query(QuizQuestion).filter(QuizQuestion.id == question_id).update(
        {QuizQuestion.answer_confidence: 0.5}, synchronize_session=False
    )
    pq.db.commit()
    pending = _ok(api.post("/api/quiz/submit", json={"question_id": question_id, "my_answer": "B"}))
    assert pending["correct"] is None and pending["needs_review"] is True
    stored = (
        pq.db.execute(
            text("SELECT is_correct FROM answer_records WHERE user_id = :uid AND question_id = :qid ORDER BY id"),
            {"uid": UID_A, "qid": question_id},
        )
        .scalars()
        .all()
    )
    assert stored == [True, False, None], stored

    stats = _ok(api.get("/api/quiz/stats"))
    assert stats["total_attempts"] == 2
    assert stats["pending_attempts"] == 1
    assert stats["accuracy_rate"] == 50.0
    math_stats = next(item for item in stats["subject_accuracy"] if item["subject"] == "数学")
    assert math_stats["attempts"] == 2
    assert math_stats["pending"] == 1
    assert math_stats["correct"] == 1
    assert math_stats["accuracy"] == 50.0
    assert stats["answer_events_total"] == 3
    assert stats["graded_answer_events"] == 2
    assert stats["pending_answer_events"] == 1
    assert stats["event_accuracy_rate"] == 50.0

    overview = _ok(api.get("/api/stats/overview"))
    overview_math = next(item for item in overview["subjects"] if item["subject"] == "数学")
    assert overview_math == {
        "subject": "数学",
        "answered": 3,
        "correct": 1,
        "graded": 2,
        "pending": 1,
        "accuracy": 50.0,
    }
    today_math = overview["trend_7d"][local_today().isoformat()]
    assert today_math == {"answered": 3, "correct": 1, "graded": 2, "pending": 1}

    from services.learner_profile import build_profile

    before = build_profile(pq.db, days=7, user_id=UID_A)
    pending_row = AnswerRecord(
        user_id=UID_A,
        question_id=question_id,
        subject=pq.marker,
        is_correct=None,
    )
    pq.db.add(pending_row)
    pq.db.commit()
    after = build_profile(pq.db, days=7, user_id=UID_A)
    assert after["overview"]["total_answers"] == before["overview"]["total_answers"] + 1
    assert after["overview"]["graded_answers"] == before["overview"]["graded_answers"]
    assert after["overview"]["pending_answers"] == before["overview"]["pending_answers"] + 1
    profile_math = next(item for item in after["subjects"] if item["subject"] == pq.marker)
    assert profile_math["answered"] == 1
    assert profile_math["graded"] == 0
    assert profile_math["pending"] == 1
    assert profile_math["accuracy"] is None


def _synchronize_first_write(engine, table: str):
    barrier = threading.Barrier(2)

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lstrip().upper()
        if normalized.startswith("INSERT") and table in statement:
            barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    return before_cursor_execute


def test_concurrent_membership_insert_is_idempotent(pq):
    from services.personal_quiz import add_membership

    pq.login(UID_A)
    bank_id = _create_bank(pq.api, f"{pq.marker}-并发收藏库")
    listener = _synchronize_first_write(pq.db.get_bind(), "quiz_question_set_items")

    def add_once():
        db = SessionLocal()
        try:
            add_membership(db, bank_id, pq.public_math_id)
            db.commit()
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(add_once) for _ in range(2)]
            for future in futures:
                future.result(timeout=15)
    finally:
        event.remove(pq.db.get_bind(), "before_cursor_execute", listener)

    count = pq.db.execute(
        text("SELECT COUNT(*) FROM quiz_question_set_items WHERE set_id = :bank_id AND question_id = :question_id"),
        {"bank_id": bank_id, "question_id": pq.public_math_id},
    ).scalar()
    assert count == 1


def test_concurrent_answer_state_updates_keep_attempts(pq):
    from services.personal_quiz import record_answer_state

    pq.login(UID_A)
    bank_id = _create_bank(pq.api, f"{pq.marker}-并发作答库")
    _ok(pq.api.post(f"{SETS}/{bank_id}/items", json={"question_id": pq.public_math_id}))
    listener = _synchronize_first_write(pq.db.get_bind(), "quiz_question_states")

    def answer_once():
        db = SessionLocal()
        try:
            question = db.get(QuizQuestion, pq.public_math_id)
            record_answer_state(db, UID_A, question, True, False)
            db.commit()
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(answer_once) for _ in range(2)]
            for future in futures:
                future.result(timeout=15)
    finally:
        event.remove(pq.db.get_bind(), "before_cursor_execute", listener)

    pq.db.expire_all()
    state = pq.db.get(QuizQuestionState, (UID_A, pq.public_math_id))
    assert state is not None
    assert state.attempts == 2
    assert state.mastery_state == "mastered" and state.last_result is True


def test_ai_bank_answer_only_reads_public_or_owned_questions(pq):
    from services.qa_foundation import find_bank_answer

    api = pq.api
    pq.login(UID_A)
    private_content = f"{pq.marker} 跨账号AI私有题干。"
    private_answer = f"{pq.marker} 跨账号AI私有答案"
    private_id = _create_question(
        api,
        pq.marker,
        content=private_content,
        answer="A",
        analysis=private_answer,
    )
    pq.db.query(QuizQuestion).filter(QuizQuestion.id == private_id).update(
        {"answer_source": "user_confirmed", "answer_confidence": 1.0},
        synchronize_session=False,
    )
    pq.db.commit()
    query = f"请解答这道题：\n{private_content}\n谢谢"

    pq.login(UID_B)
    principal_b = pq.db.get(User, UID_B)
    assert find_bank_answer(pq.db, query, user=principal_b) is None
    assert find_bank_answer(pq.db, query, user=None) is None

    pq.login(UID_A)
    principal_a = pq.db.get(User, UID_A)
    hit = find_bank_answer(pq.db, query, user=principal_a)
    assert hit and hit["id"] == private_id and hit["analysis"] == private_answer
    for path in ("/api/ai/chat", "/api/ai/chat/router"):
        response = api.post(
            path,
            json={"messages": [{"role": "user", "content": query}], "use_rag": True},
        )
        body = _ok(response)
        if path == "/api/ai/chat":
            assert body["bank_hit"] is True
        else:
            assert body["engine_used"] == "bank"
        assert body["bank_answer"]["id"] == private_id
        assert private_answer in body["content"]


def test_conflict_review_requires_admin_for_read_and_write(pq):
    from services.confidence_service import register_conflict

    pq.login(UID_A)
    private_id = _create_question(api=pq.api, marker=pq.marker)
    assert register_conflict(pq.db, private_id, "甲", "乙", "bank", "source_extract")
    try:
        pq.login(UID_B)
        for method, path, kwargs in (
            ("get", "/api/conflicts", {}),
            ("get", "/api/conflicts/stats", {}),
            ("post", "/api/conflicts/seed", {"json": {"rows": []}}),
            ("post", "/api/conflicts/1/reject", {"json": {}}),
        ):
            response = getattr(pq.api, method)(path, **kwargs)
            assert response.status_code in (401, 403), (path, response.status_code, response.text)
            assert "甲" not in response.text and "乙" not in response.text
    finally:
        pq.db.execute(text("DELETE FROM conflict_review_queue WHERE question_id = :qid"), {"qid": private_id})
        pq.db.commit()


def test_knowledge_point_related_errors_are_user_scoped(pq):
    kp = KnowledgePoint(name=f"{pq.marker} 归属测试考点", subject="数学")
    pq.db.add(kp)
    pq.db.commit()
    try:
        errors = []
        for uid in (UID_A, UID_B):
            error = ErrorRecord(
                user_id=uid,
                content=f"{pq.marker} 用户{uid}错题内容",
                my_answer=f"{pq.marker} 用户{uid}我的答案",
                correct_answer=f"{pq.marker} 用户{uid}正确答案",
                subject="数学",
                status="active",
            )
            pq.db.add(error)
            pq.db.flush()
            pq.db.add(
                ErrorKnowledgeLink(
                    user_id=uid,
                    error_id=error.id,
                    knowledge_point_id=kp.id,
                    relevance=1.0,
                    source="manual",
                )
            )
            errors.append(error)
        pq.db.commit()

        pq.login(UID_A)
        body = _ok(pq.api.get(f"/api/taxonomy/knowledge-points/{kp.id}"))
        assert [item["id"] for item in body["related_errors"]] == [errors[0].id]
        assert f"用户{UID_B}" not in json.dumps(body, ensure_ascii=False)

        pq.login(UID_B)
        body = _ok(pq.api.get(f"/api/taxonomy/knowledge-points/{kp.id}"))
        assert [item["id"] for item in body["related_errors"]] == [errors[1].id]
        assert f"用户{UID_A}" not in json.dumps(body, ensure_ascii=False)
    finally:
        pq.db.delete(kp)
        pq.db.commit()


def test_low_confidence_subjective_self_score_remains_needs_review(pq):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 低置信主观题",
        options=None,
        answer="主观参考答案",
        question_type="essay",
    )
    _set_mastery(api, question_id, "mastered")
    pq.db.query(QuizQuestion).filter(QuizQuestion.id == question_id).update(
        {QuizQuestion.answer_confidence: 0.5}, synchronize_session=False
    )
    pq.db.commit()
    _mark_validation_pass(question_id)

    result = _ok(
        api.post(
            "/api/quiz/submit",
            json={
                "question_id": question_id,
                "my_answer": "我的主观作答",
                "self_score": 0,
                "max_score": 10,
                "mode": "personal",
            },
        )
    )
    assert result["correct"] is None and result["needs_review"] is True
    item = _questions(api)["items"][0]
    assert item["mastery_state"] == "mastered"
    assert item["attempts"] == 1 and item["last_result"] is None
    assert (
        pq.db.execute(
            text("SELECT COUNT(*) FROM error_records WHERE user_id = :uid AND question_id = :qid"),
            {"uid": UID_A, "qid": question_id},
        ).scalar()
        == 0
    )


def test_missing_objective_answer_is_needs_review_without_mastery_change(pq):
    api = pq.api
    pq.login(UID_A)
    pq.db.query(QuizQuestion).filter(QuizQuestion.id == pq.public_math_id).update(
        {QuizQuestion.answer: None, QuizQuestion.answer_confidence: 1.0}, synchronize_session=False
    )
    pq.db.commit()

    result = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": pq.public_math_id, "my_answer": "B", "mode": "personal"},
        )
    )
    assert result["correct"] is None and result["needs_review"] is True
    assert result["correct_answer"] is None
    assert (
        pq.db.execute(
            text("SELECT COUNT(*) FROM error_records WHERE user_id = :uid AND question_id = :qid"),
            {"uid": UID_A, "qid": pq.public_math_id},
        ).scalar()
        == 0
    )


def test_legacy_objective_draw_is_never_string_graded(pq):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} 旧数据作图题",
        options=None,
        answer="正确作图",
        question_type="draw",
    )
    pq.db.query(QuizQuestion).filter(QuizQuestion.id == question_id).update(
        {QuizQuestion.answer_type: "objective"}, synchronize_session=False
    )
    pq.db.commit()

    result = _ok(
        api.post(
            "/api/quiz/submit",
            json={"question_id": question_id, "my_answer": "错误作图", "mode": "personal"},
        )
    )
    assert result["correct"] is None and result["needs_review"] is True
    assert result["is_subjective"] is True
    assert (
        pq.db.execute(
            text("SELECT COUNT(*) FROM error_records WHERE user_id = :uid AND question_id = :qid"),
            {"uid": UID_A, "qid": question_id},
        ).scalar()
        == 0
    )


@pytest.mark.parametrize("question_type", ["fill", "calc", "draw"], ids=["填空", "计算", "作图"])
def test_all_frontend_question_types_are_supported_as_personal_subjective_assets(pq, question_type):
    api = pq.api
    pq.login(UID_A)
    question_id = _create_question(
        api,
        pq.marker,
        content=f"{pq.marker} {question_type} 自建题",
        question_type=question_type,
        options=None,
        answer="主观参考答案",
    )
    item = _questions(api)["items"][0]
    assert item["id"] == question_id and item["question_type"] == question_type
    assert item["answer_type"] == "subjective"
    practice = _ok(api.get(PRACTICE, params={"question_type": question_type}))
    assert [row["id"] for row in practice["items"]] == [question_id]
    assert "answer" not in practice["items"][0] and "analysis" not in practice["items"][0]


def test_exam_build_never_selects_another_users_private_question(pq):
    api = pq.api
    pq.login(UID_A)
    private_chapter = f"{pq.marker} 私有组卷章"
    private_content = f"{pq.marker} 私有组卷题"
    private_id = _create_question(
        api,
        pq.marker,
        content=private_content,
        chapter=private_chapter,
    )
    columns = {col["name"] for col in inspect(pq.db.get_bind()).get_columns("exam_blueprints")}
    type_column = "blueprint_question_type" if "blueprint_question_type" in columns else "question_type"
    paper = f"pqc-exam-{uuid.uuid4().hex[:12]}"
    pq.db.execute(
        text(
            f"INSERT INTO exam_blueprints "
            f'(subject, paper, section, "{type_column}", "count", score_per_question, '
            f"time_limit_minutes, sort_order, kp_filters, is_active) "
            f"VALUES (:subject, :paper, :section, :question_type, :count, :score, :minutes, :sort_order, :filters, TRUE)"
        ),
        {
            "subject": "数学",
            "paper": paper,
            "section": "隐私回归单选",
            "question_type": "single",
            "count": 1,
            "score": 5,
            "minutes": 30,
            "sort_order": 9999,
            "filters": json.dumps({"chapters": [private_chapter]}, ensure_ascii=False),
        },
    )
    pq.db.commit()
    payload = {"subject": "数学", "paper": paper, "count_override": 1}
    try:
        pq.login(UID_B)
        denied = api.post("/api/exam/build", json=payload)
        assert denied.status_code == 200, denied.text
        assert private_content not in denied.text and "私有组卷题" not in denied.text
        assert "error" in denied.json()
        snapshots = pq.db.execute(
            text(
                "SELECT COUNT(*) FROM exam_answers ea"
                " JOIN exam_sessions es ON es.id = ea.session_id"
                " WHERE es.user_id = :uid AND ea.question_id = :qid"
            ),
            {"uid": UID_B, "qid": private_id},
        ).scalar()
        assert snapshots == 0, "越权组卷不得冻结他人私有题快照"

        pq.login(UID_A)
        own = api.post("/api/exam/build", json=payload)
        body = _ok(own)
        assert private_content in own.text
        assert [q["question_id"] for section in body["sections"] for q in section["questions"]] == [private_id]
    finally:
        pq.db.execute(text("DELETE FROM exam_blueprints WHERE paper = :paper"), {"paper": paper})
        pq.db.commit()
