"""quiz 题库编辑接口回归测试：PUT /api/quiz/questions/{id} 局部更新 + question_type 筛选。

隔离说明
--------
全部请求走 conftest 改写的临时库（DATABASE_PATH 指向 tempfile 下的 qa_test.db），
绝不触碰 ``D:\\平台\\database\\kaoyan.db`` 真实数据。
本文件自造数据（POST 新建 → 断言 → DELETE 清理），不复用 sample_data 的共享题目，
避免污染会话级其他用例。

覆盖
----
1. PUT 只覆盖请求体中显式传入的字段（exclude_unset 语义），未传字段保持原值；
2. PUT 不存在的 id 返回 404；
3. GET /api/quiz/questions?question_type=xxx 只返回对应题型。
"""
from __future__ import annotations

import pytest


@pytest.fixture
def fresh_single_question(client):
    """新建一道 single 题，返回其 id；测试结束后删除，保持库干净。"""
    payload = {
        "content": "QA-PUT 测试题：2+2=?",
        "options": ["3", "4", "5", "6"],
        "answer": "B",
        "analysis": "原始解析",
        "subject": "QA-PUT数学",
        "chapter": "QA-PUT章节",
        "knowledge_point": "QA-PUT知识点",
        "difficulty": 2,
        "source": "自建",
        "question_type": "single",
    }
    r = client.post("/api/quiz/questions", json=payload)
    assert r.status_code == 200, r.text
    qid = r.json()["id"]
    try:
        yield qid
    finally:
        client.delete(f"/api/quiz/questions/{qid}")


def test_put_updates_only_sent_fields(client, fresh_single_question):
    """PUT 传 analysis+difficulty：新值生效，未传字段（content/answer/subject/options）保持不变。"""
    qid = fresh_single_question

    r = client.put(
        f"/api/quiz/questions/{qid}",
        json={"analysis": "新解析-已更新", "difficulty": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # 已传字段：新值生效
    assert body["analysis"] == "新解析-已更新"
    assert body["difficulty"] == 5
    # 未传字段：保持原值，未被 None 清空
    assert body["content"] == "QA-PUT 测试题：2+2=?"
    assert body["answer"] == "B"
    assert body["subject"] == "QA-PUT数学"
    assert body["question_type"] == "single"
    # 选项正典格式为 [{key,text}]（DB 约束 is_canonical_options 与前端一致）；
    # 入口统一经 services.content_sanitizer 规整，字符串数组会被转成该格式。
    assert [o["text"] for o in body["options"]] == ["3", "4", "5", "6"]
    assert [o["key"] for o in body["options"]] == ["A", "B", "C", "D"]

    # GET 列表里也能读到新值
    r2 = client.get("/api/quiz/questions", params={"subject": "QA-PUT数学"})
    assert r2.status_code == 200, r2.text
    items = [q for q in r2.json()["questions"] if q["id"] == qid]
    assert len(items) == 1
    assert items[0]["analysis"] == "新解析-已更新"
    assert items[0]["difficulty"] == 5
    assert items[0]["answer"] == "B"


def test_put_404_for_missing_question(client):
    """PUT 不存在的题目 id 返回 404，并把原因带给前端。

    历史上 main.py 的全局 404 处理器（SPA fallback）会把 /api 路径下所有
    HTTPException(404) 的 detail 统一压成 {"detail": "Not Found"}，前端只能看到
    "404"三个字、分不清"记录不存在"和"接口没注册"。#26 修掉了这个改写：
    现在保留路由原文案。#19 又把 404 也并进统一错误壳，人话原因搬到 ``message``，
    ``path`` 收进 ``detail`` 里。
    """
    r = client.put("/api/quiz/questions/999999", json={"analysis": "x"})
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "RESOURCE_NOT_FOUND"
    assert body["message"] == "题目 999999 不存在"
    assert body["detail"]["path"] == "/api/quiz/questions/999999"


def test_get_filter_by_question_type(client):
    """GET /questions?question_type=judge 只含 judge；?question_type=single 不含自造的 judge 题。"""
    r = client.post(
        "/api/quiz/questions",
        json={
            "content": "QA-FILTER 判断题：地球是圆的。",
            "answer": "对",
            "analysis": "QA",
            "subject": "QA-FILTER",
            "difficulty": 1,
            "source": "自建",
            "question_type": "judge",
        },
    )
    assert r.status_code == 200, r.text
    judge_id = r.json()["id"]
    try:
        # single 过滤：不应包含这道 judge 题
        r_single = client.get(
            "/api/quiz/questions", params={"question_type": "single", "page_size": 200}
        )
        assert r_single.status_code == 200, r_single.text
        single_items = r_single.json()["questions"]
        assert judge_id not in [q["id"] for q in single_items]
        assert all(q["question_type"] == "single" for q in single_items)

        # judge 过滤：应包含这道 judge 题，且全部为 judge
        r_judge = client.get("/api/quiz/questions", params={"question_type": "judge"})
        assert r_judge.status_code == 200, r_judge.text
        judge_items = r_judge.json()["questions"]
        assert any(q["id"] == judge_id for q in judge_items)
        assert all(q["question_type"] == "judge" for q in judge_items)
    finally:
        client.delete(f"/api/quiz/questions/{judge_id}")
