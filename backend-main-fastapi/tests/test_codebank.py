# -*- coding: utf-8 -*-
"""V15 复试代码题库回归：导入/列表过滤/详情/全景/考频/科目管理。"""
from __future__ import annotations

import pytest
from tests.asgi_client import ASGIClient
from main import app

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _seed():
    r = client.post("/api/codebank/import", json={"seed_builtin": True, "dry_run": False})
    assert r.json()["imported"] == 12


def test_list_filters():
    r = client.get("/api/codebank/questions", params={"min_frequency": 5})
    d = r.json()
    assert d["total"] >= 2 and all(i["frequency"] >= 5 for i in d["items"])
    r = client.get("/api/codebank/questions", params={"tag": "栈"})
    assert r.json()["total"] >= 2
    r = client.get("/api/codebank/questions", params={"q": "链表"})
    assert r.json()["total"] >= 1


def test_detail_and_404():
    r = client.get("/api/codebank/questions/1")
    d = r.json()
    assert d["title"] and d["languages"] and d["examples"]
    assert client.get("/api/codebank/questions/99999").status_code == 404


def test_panorama_and_strategy():
    p = client.get("/api/codebank/panorama").json()
    assert len(p["items"]) >= 20 and p["items"][0]["avg_frequency"] >= 1
    e = client.get("/api/codebank/exam-strategy").json()
    assert len(e["top_questions"]) == 10 and len(e["by_direction"]) >= 5


def test_subjects_add_and_dup():
    r = client.post("/api/codebank/subjects", json={"name": "微波技术", "direction": "复试·电子"})
    assert r.json()["added"] is True
    r = client.post("/api/codebank/subjects", json={"name": "微波技术"})
    assert r.json()["added"] is False
    names = [s["name"] for s in client.get("/api/codebank/subjects").json()]
    assert "微波技术" in names and "数学" in names
