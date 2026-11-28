# -*- coding: utf-8 -*-
"""访客只读白名单回归（2026-10-19 访客模式，2026-10-21 收口）。

utils/access_policy.enforce_access 的约定：
1. 共享参考数据（/api/kaoyan /api/taxonomy /api/textbooks /api/papers）
   对未登录 GET/HEAD 开放 —— 访客能浏览院校库/通知/知识树/真题索引；
2. 个人数据（任务/单词/卡片…）与一切写操作仍然默认拒绝（401）；
3. 管理工具前缀（crawl-targets/collection/spider）不给访客；
4. /api/quiz、/api/notices、/api/papers/attempts 不在白名单内 —— 内部
   全是按登录用户读写，声明开放只会得到一批「白名单 401」的死配置；
   精确路径例外只有 /api/quiz/papers-index 与 /api/quiz/years（纯元数据）。

本模块临时弹出 conftest 的鉴权旁路，让真实策略跑；结束恢复，不影响其他模块。
"""

from __future__ import annotations

import pytest
from main import app
from tests.asgi_client import ASGIClient
from utils.access_policy import enforce_access
from utils.security import current_user

client = ASGIClient(app)


@pytest.fixture(scope="module", autouse=True)
def _real_auth():
    saved = {}
    for dep in (enforce_access, current_user):
        saved[dep] = app.dependency_overrides.pop(dep, None)
    yield
    for dep, val in saved.items():
        if val is not None:
            app.dependency_overrides[dep] = val


def test_guest_can_read_shared_data():
    assert client.get("/api/kaoyan/analysis/hot").status_code == 200
    assert client.get("/api/taxonomy/subjects").status_code == 200
    assert client.get("/api/textbooks").status_code == 200
    assert client.get("/api/papers").status_code == 200


def test_guest_personal_data_rejected():
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/words").status_code == 401
    assert client.get("/api/favorites").status_code == 401


def test_guest_writes_rejected():
    # 访客只读：任何写方法都不在白名单内
    assert client.post("/api/tasks", json={"title": "访客写入应被拒"}).status_code == 401


def test_guest_admin_tool_reads_rejected():
    # 采集源配置属管理工具读取，不给访客（GUEST_READ_DENY_PREFIXES）
    assert client.get("/api/kaoyan/crawl-targets").status_code == 401


def test_guest_personal_quiz_and_notice_state_rejected():
    # 以前它们在 GUEST_READ_PREFIXES 里，但路由内部全要登录 —— 白名单与实现矛盾。
    assert client.get("/api/quiz/questions").status_code == 401
    assert client.get("/api/quiz/subjects").status_code == 401
    assert client.get("/api/notices/list").status_code == 401


def test_guest_can_read_exam_metadata():
    # /exam 真题索引页的纯元数据：不依赖 current_user，也不含个人作答/错题状态
    assert client.get("/api/quiz/papers-index", params={"source_kind": "exam"}).status_code == 200
    assert client.get("/api/quiz/years", params={"source_kind": "exam"}).status_code == 200


def test_guest_paper_attempts_rejected():
    # 卷索引可公开；作答历史/报告是个人数据
    assert client.get("/api/papers/attempts/history").status_code == 401
    assert client.get("/api/papers/attempts/1/report").status_code == 401


# ---------------------------------------------------------------------------
# 2026-11-20 访客扩容：学习文库 / 复试代码题库 / 考研规划（只读）
# ---------------------------------------------------------------------------


def test_guest_can_read_library_documents():
    # 学习文库只依赖这三个共享读口（语料无 user_id，不含个人数据）
    assert client.get("/api/documents").status_code == 200
    assert client.get("/api/documents/subjects").status_code == 200


def test_guest_document_content_readable_but_raw_denied():
    from database import SessionLocal

    from models import Document

    s = SessionLocal()
    doc = Document(file_name="guest-preview-test.txt", content="访客可见的共享资料正文", subject="政治")
    s.add(doc)
    s.commit()
    doc_id = doc.id
    s.close()
    try:
        r = client.get(f"/api/documents/{doc_id}/content")
        assert r.status_code == 200 and "访客可见" in r.json()["content"]
        # 原文字节流/下载不在访客白名单：只看不下载
        assert client.get(f"/api/documents/{doc_id}/raw").status_code == 401
        assert client.get(f"/api/documents/{doc_id}/download").status_code == 401
    finally:
        s = SessionLocal()
        d = s.get(Document, doc_id)
        if d:
            s.delete(d)
            s.commit()
        s.close()


def test_guest_documents_writes_rejected():
    assert client.delete("/api/documents/1").status_code == 401


def test_guest_codebank_readonly():
    for p in (
        "/api/codebank/subjects",
        "/api/codebank/questions",
        "/api/codebank/panorama",
        "/api/codebank/exam-strategy",
    ):
        assert client.get(p).status_code == 200, p
    # 添加科目是管理写操作：访客 401（登录用户非管理员则 403，另有策略测试覆盖）
    assert client.post("/api/codebank/subjects", json={"name": "访客写入应被拒"}).status_code == 401


def test_guest_plan_calendar_without_goal_leak():
    """访客可看公共招生日历与阶段规划，但 goal 必须为空。

    先种一个真实用户的 Goal 作探针：scoped(Goal, None) 恒真，
    若 plan.py 未对 user=None 显式短路，这里会读出探针用户的私人目标。
    """
    from database import SessionLocal

    from models import Goal, User

    s = SessionLocal()
    u = User(username="guest_leak_probe", password_hash="x", role="user")
    s.add(u)
    s.flush()
    g = Goal(user_id=u.id, university="泄露探针大学", total_score_target=400)
    s.add(g)
    s.commit()
    uid, gid = u.id, g.id
    s.close()
    # conftest 的 auth_bypass 会把 optional_user 也 bypass 成登录态；
    # 本用例测真匿名口径，显式还原为 None（teardown 恢复原 override）。
    from main import app
    from utils.security import optional_user

    prev = app.dependency_overrides.get(optional_user)
    app.dependency_overrides[optional_user] = lambda: None
    try:
        r = client.get("/api/plan/roadmap")
        assert r.status_code == 200
        body = r.json()
        assert body["goal"] == {}, "访客 roadmap 泄露了他人 Goal"
        assert body.get("stages") and body.get("milestones")
        assert client.get("/api/plan/milestones").status_code == 200
    finally:
        if prev is None:
            app.dependency_overrides.pop(optional_user, None)
        else:
            app.dependency_overrides[optional_user] = prev
        s = SessionLocal()
        s.query(Goal).filter(Goal.id == gid).delete()
        s.query(User).filter(User.id == uid).delete()
        s.commit()
        s.close()


def test_guest_plan_generate_rejected():
    # 生成节点是写操作，仍要登录
    assert client.post("/api/plan/generate").status_code == 401
