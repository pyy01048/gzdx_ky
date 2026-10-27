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
    # 2026-10-14 修正：原先断言 ``builtin_names == set(ALL_SUBJECTS)``。
    # 但core/sql/091_subjects_ece_seed.sql 已把「数字信号处理」「电磁场与电磁波」
    # 等电子通信核心科目注册为内置科目，它们不在 taxonomy.ALL_SUBJECTS 里，
    # 于是断言恒假 —— 科目体系扩展后测试没跟上。
    # 改为「必须覆盖全部内置科目；允许存在额外的已注册科目」，
    # 既守住回归（内置科目不能丢），又不阻塞后续科目扩展。
    missing = set(taxonomy.ALL_SUBJECTS) - builtin_names
    assert not missing, f"内置科目缺失: {sorted(missing)}"
    extra = builtin_names - set(taxonomy.ALL_SUBJECTS)
    assert not any(name.startswith("QA") for name in extra), (
        f"疑似测试残留科目混入内置集合: {sorted(extra)}"
    )

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
    # 2026-10-14 修正：chapters 的契约已从「字符串数组」升级为
    # 「对象数组[{code,title,...}]」—— 前端 KbMap.jsx 等页面已按
    # x.title / x.code 消费（见 src/pages/KbMap.jsx:200/215/361），
    # 只有这里的断言还停留在旧口径。
    assert [c["title"] for c in body["chapters"]] == ["第1章 QA", "第2章 QA"], (
        f"章节标题顺序不符: {body['chapters']}"
    )
    assert [c["code"] for c in body["chapters"]] == ["ch01", "ch02"], (
        f"章节 code 顺序不符: {body['chapters']}"
    )
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
    assert [c["title"] for c in body["chapters"]] == ["新章1", "新章2"], (
        f"重命名后章节标题顺序不符: {body['chapters']}"
    )
    assert [c["code"] for c in body["chapters"]] == ["ch01", "ch02"], (
        f"重命名后章节 code 顺序不符: {body['chapters']}"
    )
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
    assert [c["title"] for c in r2.json()["chapters"]] == ["仅改章节"], (
        f"仅改章节场景 titles 不符: {r2.json()['chapters']}"
    )


def test_put_404_for_missing_subject(client):
    """PUT 一个不存在的科目 → 404，message 保留路由给的人话原因。"""
    r = client.put(f"/api/taxonomy/subjects/{PREFIX}不存在的科目XYZ", json={"chapters": ["x"]})
    assert r.status_code == 404
    assert r.json()["message"].startswith("科目不存在")


def test_delete_subject(client, cleanup_subjects):
    """DELETE 删除配置行；重复删 → 404。"""
    name = PREFIX + "DeleteMe"
    client.post("/api/taxonomy/subjects", json={"subject": name, "chapters": ["章"]})

    r = client.delete(f"/api/taxonomy/subjects/{name}")
    assert r.status_code == 200, r.text

    # 再删 → 404，带原因
    r2 = client.delete(f"/api/taxonomy/subjects/{name}")
    assert r2.status_code == 404
    assert r2.json()["message"].startswith("科目不存在")


def test_delete_builtin_not_resurrected(client):
    """删除内置科目后不得被「按缺失补齐」复活（2026-10-19 线上回归）。

    线上实测过的 bug：DELETE 返回 200、INSTEAD OF 触发器真删了 subjects 行，
    但下一次 GET /api/taxonomy/subjects 时 ensure_subject_config_seeds
    把该内置科目当「缺失」重新 INSERT，用户视角就是「删了又回来」。
    修复：subject_removals 墓碑表 + 播种类函数跳过墓碑。
    """
    from database import SessionLocal

    name = "中医综合"  # EXT_SUBJECTS 内置科目（ALL_SUBJECTS 成员）

    # 前置：确保已播种
    r = client.get("/api/taxonomy/subjects")
    by_name = {s["subject"]: s for s in r.json()["subjects"]}
    assert name in by_name, f"前置条件不成立：内置科目未播种: {name}"

    # 删除 → 200
    r = client.delete(f"/api/taxonomy/subjects/{name}")
    assert r.status_code == 200, r.text

    # 关键断言 1：再查列表（内部跑 ensure_subject_config_seeds）不得复活
    r2 = client.get("/api/taxonomy/subjects")
    names2 = {s["subject"] for s in r2.json()["subjects"]}
    assert name not in names2, f"内置科目删除后被列表查询复活: {name}"

    # 关键断言 2：显式调用播种函数也不补回
    db = SessionLocal()
    try:
        assert taxonomy.ensure_subject_config_seeds(db) == 0
        r3 = client.get("/api/taxonomy/subjects")
        names3 = {s["subject"] for s in r3.json()["subjects"]}
        assert name not in names3, f"显式播种仍复活: {name}"

        # 显式重建成功（墓碑只挡自动补齐，不挡用户加回）
        r4 = client.post("/api/taxonomy/subjects", json={"subject": name, "chapters": []})
        assert r4.status_code == 200, r4.text
        r5 = client.get("/api/taxonomy/subjects")
        assert name in {s["subject"] for s in r5.json()["subjects"]}
    finally:
        # 复原到播种前状态：删掉重建行（会记墓碑）→ 清墓碑 → 重新播种为内置行，
        # 避免影响其他用例（test_seed_idempotent_and_builtins_present 断言
        # ALL_SUBJECTS 全覆盖，残留墓碑会让内置科目缺列）。
        try:
            client.delete(f"/api/taxonomy/subjects/{name}")
        finally:
            taxonomy.unmark_subject_removed(db, name)
            taxonomy.ensure_subject_config_seeds(db)
            db.close()

    # 复原校验：内置行回来且是非自定义
    r6 = client.get("/api/taxonomy/subjects")
    restored = {s["subject"]: s for s in r6.json()["subjects"]}
    assert name in restored and restored[name]["is_custom"] is False


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
