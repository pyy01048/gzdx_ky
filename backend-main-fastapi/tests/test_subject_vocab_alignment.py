"""学科词表只读对齐（docx/16 §1.5-D/E）。

背景（实测 2026-10-13）：``documents.subject`` 有 25 个写法，
``knowledge_chunks.subject`` 只有 18 个，其中 7 个写法（306 篇文档）在分块侧
没有同名值。按学科名等值关联的入口会把它们算成「0 块」：
选「数学」看不到 31 篇「公共课-数学」，选「数字电子技术」看不到 186 篇「数模电」。

本文件钉住四件事：
1. **折叠是加法**：规范名查询能拿到别名文档；别名查询**不**反过来吞掉规范名。
2. **口径不许虚报**：未登记的写法报 ``unknown_mapping`` 让人判，不许自动洗成合法学科；
   ``subject_config`` 侧的 ``merged_document_count`` 只在互斥原值间求和，不重复计数。
3. **这一层只读**：AST 扫 ``subject_vocab``，出现任何写库调用就红。
4. **择校覆盖不许接折叠**：公共课折叠进择校口径就是把覆盖率刷成假数（#29 红线）。

红线：只用 conftest 的临时库，绝不碰 D:\\平台\\database\\kaoyan.db。
"""
from __future__ import annotations

import ast
import os

import pytest
from sqlalchemy import text


@pytest.fixture()
def vocab_docs(db_schema):  # noqa: ARG001 - 只需要建好表
    """三种写法各一篇：规范名 / 别名 / 合并口径，外加一个未登记写法。"""
    from database import SessionLocal
    from models import Document

    db = SessionLocal()
    specs = {
        "std": ("QA-词表-数学.txt", "数学"),
        "alias": ("QA-词表-公共课数学.txt", "公共课-数学"),
        "combined": ("QA-词表-数模电.txt", "数模电"),
        "unknown": ("QA-词表-未登记.txt", "QA-未登记写法"),
    }
    ids = {}
    for key, (fname, subject) in specs.items():
        # doc_type 是 ENUM('raw','note','index')，写 'txt' 在 PG 下直接
        # InvalidTextRepresentation（conftest.py:374 已记过这个坑）。
        # file_type 才是扩展名，两者不要混。
        d = Document(file_name=fname, file_path=fname, file_type="txt", size=10,
                     subject=subject, doc_type="raw", index_status="pending",
                     content="考研复习讲义正文")
        db.add(d)
        db.flush()
        ids[key] = d.id
    db.commit()
    db.close()
    yield ids
    db = SessionLocal()
    try:
        for i in ids.values():
            db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:i"), {"i": i})
            db.execute(text("DELETE FROM documents WHERE id=:i"), {"i": i})
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 1. 映射表本身
# --------------------------------------------------------------------------- #
def test_group_expands_canonical_but_not_the_reverse():
    from services.subject_vocab import doc_subject_group

    group = set(doc_subject_group("数学"))
    assert group == {"数学", "公共课-数学"}, "选规范名要连别名一起命中"
    assert set(doc_subject_group("公共课-数学")) == {"公共课-数学"}, \
        "选别名只查那批别名文档，不能反过来吞掉规范名"


def test_combined_label_expands_to_both_sides():
    from services.subject_vocab import canonical_targets, doc_subject_group

    assert set(canonical_targets("数模电")) == {"数字电子技术", "模拟电子技术"}
    assert set(doc_subject_group("数字电子技术")) == {"数字电子技术", "数模电"}


def test_unknown_label_maps_to_itself_only():
    """没登记的写法不许猜目标：猜错就是把语料折进别的学科刷覆盖数。"""
    from services.subject_vocab import canonical_targets, doc_subject_group

    assert canonical_targets("QA-未登记写法") == ("QA-未登记写法",)
    assert doc_subject_group("QA-未登记写法") == ("QA-未登记写法",)


def test_not_aliased_labels_have_measured_reasons():
    from services import subject_vocab as sv

    for label in sv.NOT_ALIASED:
        assert sv.canonical_targets(label) == (), f"{label} 被折叠就说明红线松了"
        assert len(sv.NOT_ALIASED[label]) > 10, "不归一必须写明实测理由"


# --------------------------------------------------------------------------- #
# 2. 接口层：折叠是加法
# --------------------------------------------------------------------------- #
def test_documents_filter_returns_alias_docs(client, vocab_docs):
    r = client.get("/api/documents", params={"subject": "数学"})
    assert r.status_code == 200
    ids = {d["id"] for d in r.json()}
    assert vocab_docs["std"] in ids and vocab_docs["alias"] in ids, \
        "选「数学」必须同时给出标着「公共课-数学」的那篇"
    assert vocab_docs["combined"] not in ids and vocab_docs["unknown"] not in ids


def test_documents_filter_on_alias_is_narrow(client, vocab_docs):
    r = client.get("/api/documents", params={"subject": "公共课-数学"})
    ids = {d["id"] for d in r.json()}
    assert vocab_docs["alias"] in ids
    assert vocab_docs["std"] not in ids, "别名查询反向吞掉规范名就是重复计数"


def test_subjects_endpoint_exposes_fold_fields(client, vocab_docs):  # noqa: ARG001
    r = client.get("/api/documents/subjects")
    assert r.status_code == 200
    rows = {s["name"]: s for s in r.json()["subjects"]}

    math_row = rows["数学"]
    assert math_row["aliases"] == ["公共课-数学"]
    assert math_row["alias_of"] is None
    # 旧字段口径没变，新字段是加法：合并数 = 原值数 + 别名数
    assert math_row["merged_document_count"] >= math_row["document_count"] + 1

    alias_row = rows["公共课-数学"]
    assert alias_row["alias_of"] == "数学"
    assert alias_row["aliases"] == []

    digital = rows["数字电子技术"]
    assert "数模电" in digital["aliases"], "合并口径要在两侧都可发现，否则人批时漏看"
    assert rows["模拟电子技术"]["aliases"]


def test_merged_count_does_not_double_count(client, vocab_docs):
    """组内原值互斥（一篇文档只有一个写法），所以求和=去重数；
    「数学 + 公共课-数学」的合并数必须等于两者原值数相加，不多算一次。"""
    r = client.get("/api/documents/subjects")
    rows = {s["name"]: s for s in r.json()["subjects"]}
    assert rows["数学"]["merged_document_count"] == \
        rows["数学"]["document_count"] + rows["公共课-数学"]["document_count"]


# --------------------------------------------------------------------------- #
# 3. 体检行：实测计数 + 分类不许粉饰
# --------------------------------------------------------------------------- #
def test_alignment_rows_classify_each_case(db_schema, vocab_docs):  # noqa: ARG001
    from database import SessionLocal
    from models import Document, KnowledgeChunk
    from services import subject_vocab as sv

    db = SessionLocal()
    try:
        aliased = (db.query(Document).filter(Document.id == vocab_docs["alias"]).first())
        aliased.index_status = "indexed"
        db.add(KnowledgeChunk(document_id=aliased.id, doc_name=aliased.file_name,
                              chunk_id=0, subject="数学", text="可检索的分块"))
        db.commit()

        rows = {r["subject"]: r for r in sv.alignment_rows(db)}
        for key, label, kind in [
            ("alias", "公共课-数学", "alias_folded"),
            ("combined", "数模电", "combined_expanded"),
            ("unknown", "QA-未登记写法", "unknown_mapping"),
        ]:
            row = rows[label]
            assert row["kind"] == kind, f"{label} 定性错了：{row}"
            assert row["documents"] >= 1
            assert set(row["targets"]) == set(sv.canonical_targets(label))

        un = rows["QA-未登记写法"]
        assert "人工判定" in un["reason"]
        # own_chunks 从文档侧算、documents_with_chunks 从块侧反查：
        # 零块文档会让后者为 0，前者跟着补块变 1 —— 两个口径不能混用一个数。
        sd = rows["数模电"]
        assert sd["documents_with_chunks"] == 0 and sd["own_chunks"] == 0
        assert rows["公共课-数学"]["documents_with_chunks"] == 1
        assert rows["公共课-数学"]["own_chunks"] == 1
    finally:
        db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:i"),
                   {"i": vocab_docs["alias"]})
        db.commit()
        db.close()


def test_summary_never_counts_unfoldable_as_foldable(db_schema, vocab_docs):  # noqa: ARG001
    from database import SessionLocal
    from services import subject_vocab as sv

    db = SessionLocal()
    try:
        s = sv.summary(db)
        kinds = {r["kind"] for r in s["rows"]}
        assert s["foldable_documents"] == sum(
            r["documents"] for r in s["rows"]
            if r["kind"] in ("alias_folded", "combined_expanded"))
        assert "unknown_mapping" in kinds
        assert s["unaligned_documents"] >= s["foldable_documents"]
        assert "documents.subject 未改动" in s["note"]
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 4. 只读性 + 红线
# --------------------------------------------------------------------------- #
_WRITE_METHODS = {"add", "add_all", "commit", "rollback", "flush", "delete",
                  "update", "execute", "bulk_save_objects", "bulk_insert_mappings"}


def test_subject_vocab_is_read_only():
    """这一层的全部价值就在于「不改库」：出现任何写调用，人批前提就没了。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "services", "subject_vocab.py")
    tree = ast.parse(open(path, encoding="utf-8-sig").read(), filename=path)
    bad = sorted({n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
                  and n.attr in _WRITE_METHODS})
    assert not bad, f"subject_vocab 出现写库调用：{bad}"


def test_major_coverage_does_not_use_folding():
    """择校可靠度（#29）：公共课折叠进覆盖判定等于给学校刷语料覆盖。"""
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(backend, "services", "major_coverage.py"),
               encoding="utf-8-sig").read()
    assert "subject_vocab" not in src


def test_subject_registry_is_not_touched_by_folding():
    """注册器被 4 个 /subjects 端点共用，折叠只加在 documents 路由的响应里。"""
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(backend, "services", "subject_registry.py"),
               encoding="utf-8-sig").read()
    assert "subject_vocab" not in src
