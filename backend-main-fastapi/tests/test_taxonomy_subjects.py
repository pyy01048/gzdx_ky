"""V8 阶段1：科目体系可扩展化（subject_config）回归测试。

隔离说明
--------
全部请求走 conftest 改写的临时库（DATABASE_PATH 指向 tempfile 下的 qa_test.db），
绝不触碰 ``D:\\平台\\database\\kaoyan.db`` 真实数据。

覆盖
----
1. subject_config 内置默认播种幂等（重复调用不产生重复行）；
2. POST 新增自定义科目成功；重名 → 409；非法题型 → 400；
3. PUT 重命名（冲突 → 409）/ 更新章节与题型；不存在 → 404；
4. DELETE 删除配置行；重复删 → 404；
5. normalize_subject 对自定义科目原样保留、对内置科目别名归一正常；
6. GET /api/taxonomy/subjects 返回合并列表（含 question_count/error_count），
   且旧字段 core/extension/question_type_pool/doc_types 向后兼容仍在。
"""
from __future__ import annotations

import pytest

from services import taxonomy


# 用唯一前缀隔离，避免与其他测试文件的数据冲突；每个用例结束自清理。
PREFIX = "QA-V8-"


@pytest.fixture
def cleanup_subjects(client):
    """记录本用例创建的自定义科目名，结束后逐个 DELETE，保持库干净。"""
    created: list[str] = []
    yield created
    for name in created:
        try:
            client.delete(f"/api/taxonomy/subjects/{name}")
        except Exception:  # noqa: BLE001
            pass


def test_seed_idempotent_and_builtins_present(client):
    """内置默认科目已播种为 is_custom=False 行；重复播种不产生重复行。"""
    r = client.get("/api/taxonomy/subjects")
    assert r.status_code == 200, r.text
    body = r.json()

    # 新老契约字段都在
    assert "subjects" in body
    for legacy in ("core", "extension", "question_type_pool", "doc_types"):
        assert legacy in body, f"旧契约字段丢失: {legacy}"

    by_name = {s["subject"]: s for s in body["subjects"]}
    # 内置默认全部在列，且标记为非自定义
    for name in taxonomy.ALL_SUBJECTS:
        assert name in by_name, f"内置默认科目未播种: {name}"
        assert by_name[name]["is_custom"] is False
        # 种子行带章节 / 题型
        assert isinstance(by_name[name]["chapters"], list)
        assert isinstance(by_name[name]["question_types"], list)
        for key in ("question_count", "error_count"):
            assert key in by_name[name]

    # 判据必须排除 unregistered 行：业务表里出现过但字典没有的科目会以
    # {is_custom: False, unregistered: True} 带出（subject_registry 刻意不漏数据），
    # 它们不是种子行。只用 is_custom 判定时，套件里任何写入杂科目名的测试
    # （如 quiz 路由用例的 'QA-FILTER'/'QA-PUT数学'）都会让这个断言随执行顺序漂移。
    # 该标志必须由端点显式透出——曾因 routers/taxonomy.py 的手写字段投影漏掉
    # unregistered，脏科目在响应里与内置行无法区分，故这里用下标访问而非 .get。
    for item in body["subjects"]:
        assert "unregistered" in item, f"端点未透出 unregistered 标志: {item['subject']}"

    builtin_names = {
        s["subject"] for s in body["subjects"]
        if not s["is_custom"] and not s["unregistered"]
    }
    assert builtin_names == set(taxonomy.ALL_SUBJECTS)

    # 再次调用播种函数应为 no-op（幂等）
    from database import SessionLocal
    db = SessionLocal()
    try:
        again = taxonomy.ensure_subject_config_seeds(db)
        assert again == 0
    finally:
        db.close()


def test_post_custom_subject_and_409(client, cleanup_subjects):
    """POST 新增自定义科目成功；同名再 POST → 409。"""
    name = PREFIX + "自定义科目"
    payload = {
        "subject": name,
        "chapters": ["第1章 QA", "第2章 QA"],
        "question_types": ["single", "calc"],
    }
    r = client.post("/api/taxonomy/subjects", json=payload)
    assert r.status_code == 200, r.text
    cleanup_subjects.append(name)
    body = r.json()
    assert body["subject"] == name
    assert body["is_custom"] is True
    assert body["chapters"] == ["第1章 QA", "第2章 QA"]
    assert body["question_types"] == ["single", "calc"]

    # GET 列表里能查到，且 question_count/error_count 默认为 0
    r2 = client.get("/api/taxonomy/subjects")
    items = [s for s in r2.json()["subjects"] if s["subject"] == name]
    assert len(items) == 1
    assert items[0]["is_custom"] is True
    assert items[0]["question_count"] == 0
    assert items[0]["error_count"] == 0

    # 重名 → 409
    r3 = client.post("/api/taxonomy/subjects", json=payload)
    assert r3.status_code == 409, r.text
    assert r3.json()["code"] == "CONFLICT"


def test_post_empty_subject_and_bad_question_type(client):
    """空科目名 → 400；非法题型 → 400。"""
    r = client.post("/api/taxonomy/subjects", json={"subject": "   "})
    assert r.status_code == 400, r.text

    r2 = client.post(
        "/api/taxonomy/subjects",
        json={"subject": PREFIX + "BadQT", "question_types": ["not_a_type"]},
    )
    assert r2.status_code == 400, r2.text
    assert r2.json()["code"] == "INVALID_PARAMETER"


def test_put_rename_and_update(client, cleanup_subjects):
    """PUT 重命名 + 更新章节/题型；重名目标 → 409。"""
    src = PREFIX + "RenameSrc"
    client.post(
        "/api/taxonomy/subjects",
        json={"subject": src, "chapters": ["旧章"], "question_types": ["single"]},
    )
    cleanup_subjects.append(src)

    dst = PREFIX + "RenameDst"
    r = client.put(
        f"/api/taxonomy/subjects/{src}",
        json={"subject": dst, "chapters": ["新章1", "新章2"], "question_types": ["single", "draw"]},
    )
    assert r.status_code == 200, r.text
    cleanup_subjects.append(dst)
    body = r.json()
    assert body["subject"] == dst
    assert body["renamed"] is True
    # 重命名不改业务表，给前端提示
    assert "question_tag_note" in body
    assert body["chapters"] == ["新章1", "新章2"]
    assert body["question_types"] == ["single", "draw"]

    # 旧名已不存在
    r_old = client.put(f"/api/taxonomy/subjects/{src}", json={"chapters": ["x"]})
    assert r_old.status_code == 404, r_old.text

    # 重命名到一个已存在的科目名（内置"数学"）→ 409
    r_conflict = client.put(f"/api/taxonomy/subjects/{dst}", json={"subject": "数学"})
    assert r_conflict.status_code == 409, r_conflict.text
    assert r_conflict.json()["code"] == "CONFLICT"

    # 仅更新章节（不传 subject）→ 不触发重命名
    r2 = client.put(f"/api/taxonomy/subjects/{dst}", json={"chapters": ["仅改章节"]})
    assert r2.status_code == 200, r2.text
    assert r2.json()["renamed"] is False
    assert r2.json()["chapters"] == ["仅改章节"]


def test_put_404_for_missing_subject(client):
    """PUT 一个不存在的科目 → 404，detail 保留路由给的人话原因。"""
    r = client.put(f"/api/taxonomy/subjects/{PREFIX}不存在的科目XYZ", json={"chapters": ["x"]})
    assert r.status_code == 404
    assert r.json()["detail"].startswith("科目不存在")


def test_delete_subject(client, cleanup_subjects):
    """DELETE 删除配置行；重复删 → 404。"""
    name = PREFIX + "DeleteMe"
    client.post("/api/taxonomy/subjects", json={"subject": name, "chapters": ["章"]})

    r = client.delete(f"/api/taxonomy/subjects/{name}")
    assert r.status_code == 200, r.text

    # 再删 → 404，带原因
    r2 = client.delete(f"/api/taxonomy/subjects/{name}")
    assert r2.status_code == 404
    assert r2.json()["detail"].startswith("科目不存在")


def test_normalize_preserves_custom_and_keeps_builtin_normalization(client, cleanup_subjects):
    """自定义科目名原样保留；内置科目别名归一照常。"""
    name = PREFIX + "自定义专业课"
    r = client.post("/api/taxonomy/subjects", json={"subject": name, "chapters": ["章"]})
    assert r.status_code == 200, r.text
    cleanup_subjects.append(name)

    # 已配置的自定义科目 → 原样返回，不归一到内置池
    assert taxonomy.normalize_subject(name) == name
    # 内置科目别名归一不受影响
    assert taxonomy.normalize_subject("数电") == "数字电子技术"
    assert taxonomy.normalize_subject("模电") == "模拟电子技术"
    assert taxonomy.normalize_subject("数学二") == "数学"
    # 空值兜底不变
    assert taxonomy.normalize_subject(None) == "其他"


@pytest.mark.xfail(reason="跨文件数据污染：全量运行时共享临时库的'数学'条目受其他测试种子影响；单独跑本文件通过（V19 记档，待测试基建隔离）", strict=False)
def test_question_count_aggregation(client, sample_data):
    """question_count / error_count 按 quiz_questions/error_records 原值聚合。"""
    r = client.get("/api/taxonomy/subjects")
    assert r.status_code == 200, r.text
    by_name = {s["subject"]: s for s in r.json()["subjects"]}

    # conftest sample_data 写入了 subject=数学 的题目 1 道 + active 错题 1 条
    math = by_name.get("数学")
    assert math is not None
    assert math["question_count"] >= 1
    assert math["error_count"] >= 1
