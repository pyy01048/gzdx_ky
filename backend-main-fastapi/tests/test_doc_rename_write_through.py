"""#27 文档显示名 —— 命名规则 + 写穿语义 + 入库接线回归。

规则实现只在 `services/doc_naming.py` 一处（上传 / 网盘 / 批量导入 / 知识库 /
目录监听 / 存量批量脚本都调它），本文件因此能直接测规则本身，而不是测脚本副本。

锁四件事：

1. **定名护栏**：宁可空也不要假名字。正文《》实测是引用，题干/选项/图注/分页标记/
   APP 残渣/解析失败占位串一律不得成为名字。
2. **只加不减**：原名有效部分当锚点保留，同章节去重；新名逐字来自正文。
3. **写穿语义**：改 `documents.file_name` 必须同事务写穿 `knowledge_chunks.doc_name`
   （答疑引用用 `c.doc_name`），且 `file_path` 一律不动 —— #26 的
   `/api/documents/{id}/raw|download` 靠它定位原文；FTS 镜像不含 doc_name，
   所以写完不需要重建索引。
4. **入库路径不回访网盘**：改名后 `file_name` 不再等于网盘原名，去重必须认 `file_path`。

只用 conftest 的临时库（红线：绝不碰 D:\\平台\\database\\kaoyan.db）。
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3

import pytest
from sqlalchemy import text

from services import doc_naming

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def _load_apply_script():
    spec = importlib.util.spec_from_file_location(
        "rename_docs_apply", os.path.join(SCRIPTS, "rename_docs_apply.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BODY = "第 1 章 逻辑代数基础\n本章介绍逻辑代数的基本运算。"


# --------------------------------------------------------------------------- #
# 1–2. 规则本身
# --------------------------------------------------------------------------- #
def test_propose_refuses_informative_and_book_bracket_names():
    assert doc_naming.propose("阎石《数字电子技术基础》第5版笔记.txt", BODY)["reason"] == "现名已含《书名》，不改"
    assert "已能看懂" in doc_naming.propose("2023年4月数电月考试卷.txt", BODY)["reason"]
    assert "已能看懂" in doc_naming.propose("Code Complete（中文版）.pdf", BODY)["reason"]


def test_propose_requires_empty_body_and_refuses_non_titles():
    assert "正文为空" in doc_naming.propose("微信图片_20260610234956_51_695.jpg", "")["reason"]

    # 题干 / 选项 / 图注 / 分页标记 / APP 残渣 / 解析失败占位串：都不许当标题
    for junk in ("A、尽量使管子参数对称 B、尽量使电路参数对称",
                 "六、说明放大电路输入电阻和输出电阻的物理意义以及它们的大小与电路性能的关系",
                 "图 9－1 双极型 555 定时器电路结构图",
                 "--- 第 2 页 ---",
                 "新建试卷新建手机课件",
                 "第9章-直流电源[兼容模式] - PowerPoint",
                 "页反向击穿与齐纳击穿的原理（简答",
                 "[pdf 文件，未能提取到文本内容] 文件名：01.pdf"):
        got = doc_naming.propose("01.pdf", f"{junk}\n本章介绍三态门与总线负载的计算方法。")
        assert got.get("reason"), f"垃圾行被当成了标题：{junk} → {got}"


def test_propose_adds_body_title_but_never_loses_the_old_anchor():
    got = doc_naming.propose("834考纲.txt", "贵州大学硕士研究生入学考试大纲\n一、考试性质")
    assert got["proposed"] == "834考纲 贵州大学硕士研究生入学考试大纲.txt", got
    assert got["verbatim"].startswith("yes")

    # 同章节锚点不重复；跨章节锚点必须留着（只加不减）
    same = doc_naming.propose("第1章.txt", "第 1 章 逻辑代数基础\n正文")
    assert same["proposed"] == "第 1 章 逻辑代数基础.txt", same
    cross = doc_naming.propose("第3讲.txt", "第 5 章 时序逻辑电路\n正文")
    assert "第3讲" in cross["proposed"], cross

    # Windows 非法字符必须被清掉，且清完仍算逐字来源
    slash = doc_naming.propose("第8章.txt", "第 8 章 数/模和模/数转换\n正文")
    assert "/" not in slash["proposed"], slash
    assert slash["proposed"] == "第 8 章 数 模和模 数转换.txt", slash


def test_low_info_detection_matches_measured_shapes():
    for bad in ("01.pdf", "001.PDF", "微信图片_20260610235058_83_695.jpg",
                "扫描件_2026.pdf", "834考纲.txt", "第1章.txt", "测试题1.txt", "1.png"):
        assert doc_naming.is_low_info(bad), bad
    # 年份/卷号本身就算信息，保守跳过，避免改名把「1986」「1998-2012年」弄丢
    for good in ("1986【 00】 .pdf", "1998-2012年.pdf",
                 "2023年4月数电第一次月考-华东师范大学901真题22.txt",
                 "10月数电第一次月考答案.txt", "阎石《数字电子技术基础》第5版笔记.txt",
                 "Code Complete中文版.pdf", "Google_Cpp_Style_guide_CN.pdf",
                 "简答题精选30题.txt"):
        assert not doc_naming.is_low_info(good), good


def test_chapter_num_normalises_digits_and_chinese():
    assert doc_naming.chapter_num("第1章") == doc_naming.chapter_num("第 1 章") == 1
    assert doc_naming.chapter_num("第一章") == 1
    assert doc_naming.chapter_num("第十二节") == 12
    assert doc_naming.chapter_num("第２章") == 2
    assert doc_naming.chapter_num("没有章节") is None


def test_anchor_drops_importer_junk_and_keeps_real_info():
    """锚点必须和 is_low_info 同一套剥除口径，否则垃圾前缀会留在新名字里。"""
    assert doc_naming.anchor_of("微信图片_20260610234957_52_695.jpg") == ""
    assert doc_naming.anchor_of("扫描件_2026.pdf") == ""
    assert doc_naming.anchor_of("834考纲.txt") == "834考纲"
    assert doc_naming.anchor_of("第3讲.txt") == "第3讲"

    got = doc_naming.propose("微信图片_20260610234957_52_695.jpg",
                             "第三节 若干常用的组合逻辑电路\n一、加法器")
    assert got["proposed"] == "第三节 若干常用的组合逻辑电路.jpg", got
    assert "微信图片" not in got["proposed"]


def test_auto_rename_is_idempotent_on_renamed_output():
    """改完一次的名字再过一次规则必须不再改，否则重跑入库会反复改名。"""
    once = doc_naming.auto_rename("第1章.txt", BODY)
    assert once == "第 1 章 逻辑代数基础.txt", once
    assert doc_naming.auto_rename(once, BODY) is None


# --------------------------------------------------------------------------- #
# 3. 入库路径：apply_display_name
# --------------------------------------------------------------------------- #
def _seed(db, file_name, subject="数字电子技术", chunks=0, path=None):
    from models import Document, KnowledgeChunk

    doc = Document(file_name=file_name, subject=subject, content="# 重命名夹具",
                   file_path=path or rf"D:\平台\knowledge_base\数电\{file_name}")
    db.add(doc)
    db.flush()
    for i in range(chunks):
        db.add(KnowledgeChunk(document_id=doc.id, doc_name=doc.file_name, chunk_id=i,
                              subject=subject, text=f"三态门总线的负载计算 {i}"))
    db.commit()
    return doc


def _db_path():
    import database

    return database.SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1)


def _sqlite():
    """打开与被测脚本同库的裸 DBAPI 连接（跨方言：PG 走项目 engine）。

    历史版本直接 sqlite3.connect(路径)，PG 迁移后 URL 不再是 sqlite 文件，
    connect 必然报 unable to open database file。改为按项目底座取原生连接。
    """
    import database

    if getattr(database, "IS_POSTGRES", False):
        return database.engine.raw_connection()
    import sqlite3

    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    return con


def _mirror_names(db, doc_id):
    from models import KnowledgeChunk

    return {c.doc_name for c in db.query(KnowledgeChunk).filter(
        KnowledgeChunk.document_id == doc_id).all()}


def _cleanup(db, *doc_ids):
    for d in doc_ids:
        db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": d})
        db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": d})
    db.commit()


def test_apply_display_name_renames_writes_through_and_keeps_path(db_schema):  # noqa: ARG001
    from database import SessionLocal

    db = SessionLocal()
    try:
        # 前置清理：历史运行残留的同名文档会触发撞名保护，让改名静默保持原名
        from models import Document

        db.query(Document).filter(
            Document.file_name == "第 1 章 逻辑代数基础.txt").delete(synchronize_session=False)
        db.commit()
        doc = _seed(db, "第1章.txt", chunks=2)
        path = doc.file_path
        out = doc_naming.apply_display_name(db, doc, BODY)
        db.commit()

        assert out == "第 1 章 逻辑代数基础.txt", out
        assert doc.file_name == out
        assert _mirror_names(db, doc.id) == {out}, "已有分块的 doc_name 必须同事务写穿"
        assert doc.file_path == path, "动 file_path 会打断 #26 的预览/下载"
        _cleanup(db, doc.id)
    finally:
        db.close()


def test_apply_display_name_keeps_original_on_collision(db_schema):  # noqa: ARG001
    """自动入库没有人可问：撞库内已有同名只能保持原名（批量脚本才交人判）。"""
    from database import SessionLocal

    db = SessionLocal()
    try:
        other = _seed(db, "第 1 章 逻辑代数基础.txt")
        doc = _seed(db, "第1章.txt")
        assert doc_naming.apply_display_name(db, doc, BODY) == "第1章.txt"
        db.commit()
        assert doc.file_name == "第1章.txt"
        assert other.file_name == "第 1 章 逻辑代数基础.txt"
        _cleanup(db, doc.id, other.id)
    finally:
        db.close()


def test_apply_display_name_leaves_good_and_placeholder_docs_alone(db_schema):  # noqa: ARG001
    from database import SessionLocal

    db = SessionLocal()
    try:
        good = _seed(db, "1998-2012年.pdf")
        assert doc_naming.apply_display_name(db, good, BODY) == "1998-2012年.pdf"

        low = _seed(db, "01.pdf")
        placeholder = "[pdf 文件，未能提取到文本内容] 文件名：01.pdf"
        assert doc_naming.apply_display_name(db, low, placeholder) == "01.pdf", \
            "解析失败的占位串不能反过来当标题来源"
        db.commit()
        assert low.file_name == "01.pdf"
        _cleanup(db, good.id, low.id)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 4. 存量批量脚本：stage_plan / apply_plan 守卫（对临时库跑，不碰生产库）
# --------------------------------------------------------------------------- #
def test_stage_plan_skips_drifted_and_missing_rows_then_writes_through(db_schema):  # noqa: ARG001
    mod = _load_apply_script()
    from database import SessionLocal

    db = SessionLocal()
    try:
        doc = _seed(db, "第1章.txt", chunks=2)
        gone_id = int(db.execute(
            text("SELECT COALESCE(MAX(id),0) FROM documents")).scalar()) + 999
    finally:
        db.close()

    plan = [
        {"id": str(doc.id), "current": "第1章.txt", "proposed": "第 1 章 逻辑代数基础.txt",
         "reason": ""},
        {"id": str(doc.id), "current": "别的名字.txt", "proposed": "X.txt", "reason": ""},
        {"id": str(gone_id), "current": "已删除.txt", "proposed": "Y.txt", "reason": ""},
    ]
    con = _sqlite()
    try:
        staged, stale = mod.stage_plan(con, plan)
        assert [s["id"] for s in staged] == [doc.id], staged
        assert len(stale) == 2 and stale[0][1].startswith("现名已变"), stale
        assert stale[1][1] == "文档已不存在", stale
        assert staged[0]["chunks"] == 2, "写穿行数要按库内实际算，不能信 CSV"

        applied, rows = mod.apply_plan(con, staged)
        assert (applied, rows) == (1, 2)

        db = SessionLocal()
        try:
            from models import Document

            got = db.query(Document).filter(Document.id == doc.id).first()
            assert got.file_name == "第 1 章 逻辑代数基础.txt"
            assert _mirror_names(db, doc.id) == {got.file_name}
            assert got.file_path == doc.file_path, "回写阶段同样不许动 file_path"

            # 再跑一次：库已变成目标名 → stage_plan 必须报「无需写」，绝不重复改
            again, stale2 = mod.stage_plan(con, plan[:1])
            assert again == [] and stale2[0][1] == "已是目标名，无需写", (again, stale2)
        finally:
            db.close()
    finally:
        con.close()
        db = SessionLocal()
        try:
            _cleanup(db, doc.id)
        finally:
            db.close()


def test_load_plan_drops_rejected_rows(tmp_path):
    """CSV 里 reason 非空（不改 / 撞车）的行绝不能进回写清单。"""
    mod = _load_apply_script()
    p = tmp_path / "plan.csv"
    p.write_text(
        "id,subject,current,proposed,anchor,basis,verbatim,chunks,on_disk,reason\n"
        '7,数电,第1章.txt,第 1 章 逻辑代数基础.txt,第1章,第 1 章,yes,33,yes,\n'
        '8,数电,01.pdf,第 2 章 逻辑代数.txt,01,第 2 章,yes,4,yes,collision：库内已有同名，交人判定后再动\n'
        '9,数电,真题.pdf,,,,,0,yes,现名已能看懂（中文/英文/年份标识足够），不改\n',
        encoding="utf-8-sig")
    plan = mod.load_plan(str(p))
    assert [r["id"] for r in plan] == ["7"], plan


# --------------------------------------------------------------------------- #
# 4b. 知识库入库幂等：改名后仍要认得同一份文件
# --------------------------------------------------------------------------- #
def _kb_doc(db, file_name, file_path, kp=1):
    from models import Document

    d = Document(file_name=file_name, file_path=file_path, subject="数字电子技术",
                 index_status="indexed", knowledge_point_count=kp, content="正文")
    db.add(d)
    db.commit()
    return d


def test_kb_dedup_survives_rename_and_ignores_truncated_copy(db_schema):  # noqa: ARG001
    """`_find_existing_doc` 的兜底若按 file_name 认，改名后就会重复入库。"""
    from database import SessionLocal
    from services.smart_ingest import _find_existing_doc, _trunc_copy_dir
    from models import Document

    db = SessionLocal()
    made = []
    try:
        real = _kb_doc(db, "第 1 章 逻辑代数基础.pptx",            # 已被 #27 改名
                       "knowledge_base/数电/第1章.pptx")          # 老批次：相对路径
        made.append(real)
        target = os.path.abspath(r"D:\平台\knowledge_base\数电\第1章.pptx")
        got = _find_existing_doc(db, Document, target)
        assert got is not None and got.id == real.id, \
            "按 file_name 兜底会被改名打断 → 同一份文件长出两份 Document"

        # 截断副本（正文只有 5000 字）不能当合并目标，也不能挡住真行：
        # 副本 id 更小、尾段相同，旧写法「只认 first」就会并进副本、丢一整份正文。
        trunc = _kb_doc(db, "副本.pdf", os.path.join(_trunc_copy_dir(), "讲义.pdf"))
        truth = _kb_doc(db, "讲义.pdf", "knowledge_base/数电/讲义.pdf")
        made += [trunc, truth]
        kb_abs = os.path.abspath(os.path.join(r"D:\平台", "knowledge_base", "数电", "讲义.pdf"))
        assert _find_existing_doc(db, Document, kb_abs).id == truth.id, \
            "相对路径行要按路径尾段认回，且必须跳过截断副本"

        # 文件名里的 LIKE 通配符必须转义：`100%.pdf` 不许匹配上 `100X.pdf`
        made.append(_kb_doc(db, "100X.pdf", "knowledge_base/数电/100X.pdf"))
        assert _find_existing_doc(db, Document,
                                  os.path.abspath("knowledge_base/数电/100%.pdf")) is None
    finally:
        for d in made:
            db.execute(text("DELETE FROM documents WHERE id=:i"), {"i": d.id})
        db.commit()
        db.close()


# --------------------------------------------------------------------------- #
# 5. 改名后的去重回归：网盘入口必须认 file_path
# --------------------------------------------------------------------------- #
def test_netdisk_dedup_survives_rename(db_schema, tmp_path, monkeypatch):  # noqa: ARG001
    """#27 之后 file_name 不等于网盘原名，只按名字去重会把同一文件再下一遍。"""
    import asyncio

    import routers.netdisk as nd
    from database import SessionLocal
    from models import Document, NetdiskFile

    monkeypatch.setattr(nd, "UPLOAD_DIR", str(tmp_path))

    calls = []

    class Boom:
        def __init__(self, db):
            pass

        async def download_to_file(self, fs_id, save_path, max_bytes=None):
            calls.append(fs_id)
            raise AssertionError("已入库的文件不该再次下载")

    monkeypatch.setattr(nd, "NetdiskService", Boom)

    db = SessionLocal()
    try:
        source = Document(file_name="微信图片_20260101.pptx", subject="数字电子技术",
                          file_path=str(tmp_path / "微信图片_20260101.pptx"),
                          index_status="indexed", content="第 1 章 逻辑代数基础")
        db.add(source)
        db.commit()
        # 模拟入库改名后的状态：显示名已换、file_path 仍是网盘落盘名
        renamed = Document(file_name="第 1 章 逻辑代数基础.pptx", subject="数字电子技术",
                           file_path=str(tmp_path / "第1章.pptx"),
                           index_status="indexed", content="第 1 章 逻辑代数基础")
        db.add(renamed)
        db.commit()

        f = NetdiskFile(file_name="第1章.pptx", path="/数电", file_type="pptx",
                        size=1, fs_id="12345")
        db.add(f)
        db.commit()

        out = asyncio.run(nd._ingest_netdisk_file(db, f))
        assert out["skipped"] is True and out["document_id"] == renamed.id, out
        assert calls == [], "命中去重后仍然下载了 → 会产出重复文档和重复分块"
        assert db.query(Document).filter(Document.file_name == "第1章.pptx").count() == 0

        db.execute(text("DELETE FROM documents WHERE id=:i"), {"i": source.id})
        db.execute(text("DELETE FROM documents WHERE id=:i"), {"i": renamed.id})
        db.execute(text("DELETE FROM netdisk_files WHERE fs_id='12345'"))
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 6. 写穿语义（生产库口径，SQL 级）
# --------------------------------------------------------------------------- #
def _seed_fts_doc(db, file_path):
    from models import Document, KnowledgeChunk

    doc = Document(file_name="第1章.txt", subject="数字电子技术", file_path=file_path)
    db.add(doc)
    db.flush()
    ids = []
    for i in range(2):
        c = KnowledgeChunk(document_id=doc.id, doc_name=doc.file_name, chunk_id=i,
                           subject="数字电子技术", text=f"三态门总线的负载计算 {i}")
        db.add(c)
        db.flush()
        ids.append(c.id)
        db.execute(text("INSERT INTO knowledge_chunks_fts (chunk_id, document_id, subject, content)"
                        " VALUES (:cid, :did, :s, :c)"),
                   {"cid": c.id, "did": doc.id, "s": "数字电子技术", "c": c.text})
    db.commit()
    return doc.id, ids


def test_rename_writes_through_doc_name_without_touching_path_or_fts(db_schema):  # noqa: ARG001
    from database import SessionLocal

    db = SessionLocal()
    try:
        # PG 迁移说明：FTS5 虚表是 SQLite 专有；PG 生产路径走
        # knowledge_chunks.search_vector 原生列，服务侧不建镜像表。
        # 本测试锁的契约是「改名不触碰检索镜像」，用普通表承载镜像即可。
        db.execute(text(
            "CREATE TABLE IF NOT EXISTS knowledge_chunks_fts ("
            "chunk_id INTEGER, document_id INTEGER, subject VARCHAR, content TEXT)"))
        db.commit()
        path = r"D:\平台\knowledge_base\数字电子技术\第1章.txt"
        doc_id, chunk_ids = _seed_fts_doc(db, path)

        new_name = "第 1 章 逻辑代数基础.txt"
        with db.begin():                       # apply 脚本同款单事务
            db.execute(text("UPDATE documents SET file_name=:n WHERE id=:d"),
                       {"n": new_name, "d": doc_id})
            db.execute(text("UPDATE knowledge_chunks SET doc_name=:n WHERE document_id=:d"),
                       {"n": new_name, "d": doc_id})

        names = {r[0] for r in db.execute(text(
            "SELECT doc_name FROM knowledge_chunks WHERE document_id=:d"), {"d": doc_id})}
        assert names == {new_name}, "doc_name 必须整篇写穿，不能一半新一半旧"
        got_path = db.execute(text("SELECT file_path FROM documents WHERE id=:d"),
                              {"d": doc_id}).scalar()
        assert got_path == path, "file_path 动了就会打断 #26 的预览/下载"

        hits = db.execute(text(
            "SELECT chunk_id FROM knowledge_chunks_fts"
            " WHERE document_id=:d ORDER BY chunk_id"),
            {"d": doc_id}).fetchall()
        assert [h[0] for h in hits] == chunk_ids, "镜像行不随改名丢失（FTS 不含 doc_name）"
        _cleanup(db, doc_id)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 5b. 同名不同目录不许认成本份文件（复核发现的 MAJOR）
# --------------------------------------------------------------------------- #
def test_kb_dedup_refuses_same_basename_in_a_different_folder(db_schema):  # noqa: ARG001
    """`…/数学/第一章.pdf` 和 `…/英语/第一章.pdf` 都满足 LIKE '%第一章.pdf'。

    只按文件名尾段认，就会把另一科的文档当成本份：覆盖它的 content、删光它的分块，
    而 file_path 还指着原文件 —— 结果是「预览看到 A、检索命中 B」。
    """
    from database import SessionLocal
    from models import Document
    from services.smart_ingest import _find_existing_doc

    db = SessionLocal()
    made = []
    try:
        other = _kb_doc(db, "第 3 章 数列", "knowledge_base/数学/第一章.pdf")
        made.append(other)
        target = os.path.abspath(r"D:\平台\knowledge_base\英语\第一章.pdf")
        assert _find_existing_doc(db, Document, target) is None, \
            "跨目录同名被认错：会把别的学科文档覆盖掉"

        same = os.path.abspath(r"D:\平台\knowledge_base\数学\第一章.pdf")
        assert _find_existing_doc(db, Document, same).id == other.id
    finally:
        for d in made:
            db.execute(text("DELETE FROM documents WHERE id=:i"), {"i": d.id})
        db.commit()
        db.close()


# --------------------------------------------------------------------------- #
# 5c. 网盘去重只认路径：同名不同文件不能被误判「已入库」（复核发现的 MAJOR）
# --------------------------------------------------------------------------- #
def test_netdisk_dedup_does_not_skip_a_different_file(db_schema, tmp_path, monkeypatch):  # noqa: ARG001
    """按 file_name 认会误伤：库里任何一份同名但不同路径的文档都会被跳过，
    前端还拿到它的 id —— 网盘里真正那个文件永远进不了库。"""
    import asyncio

    import routers.netdisk as nd
    from database import SessionLocal
    from models import Document, NetdiskFile

    monkeypatch.setattr(nd, "UPLOAD_DIR", str(tmp_path))
    calls = []

    class Boom:
        def __init__(self, db):
            pass

        async def download_to_file(self, fs_id, save_path, max_bytes=None):
            calls.append(fs_id)
            raise RuntimeError("模拟下载中断（只用于证明去重没有误拦）")

    monkeypatch.setattr(nd, "NetdiskService", Boom)

    db = SessionLocal()
    try:
        stranger = Document(file_name="第1章.pptx", subject="数字电子技术",
                            file_path=str(tmp_path / "other" / "第1章.pptx"),
                            index_status="indexed", content="别处的同名文件")
        db.add(stranger)
        f = NetdiskFile(file_name="第1章.pptx", path="/数电", file_type="pptx",
                        size=1, fs_id="777")
        db.add(f)
        db.commit()

        asyncio.run(nd._ingest_netdisk_file(db, f))
        assert calls == ["777"], "同名不同路径就跳过 → 网盘这个文件永远入不了库"
        db.execute(text("DELETE FROM documents WHERE id=:i"), {"i": stranger.id})
        db.execute(text("DELETE FROM netdisk_files WHERE fs_id='777'"))
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 5d. 接线可解析性：调 apply_display_name 的模块必须真的能解析到这个名字
# --------------------------------------------------------------------------- #
def _unresolved_uses(root, target):
    """AST 级检查：某处 Load 了 `target`，但模块级和所在函数里都没有导入/赋值。"""
    import ast
    import pathlib

    out = []
    # 只扫真正可能接线的目录：services / routers / scripts + 根级模块。
    # 全库 rglob 会把 data/、temp/ 里的临时脚本（含非 UTF-8/不可解析的 .py）卷进来，
    # 那些和「入库路径接线」无关，只会让这条守卫假阳。
    roots = [pathlib.Path(root) / "services", pathlib.Path(root) / "routers",
             pathlib.Path(root) / "scripts"]
    roots += [p for p in sorted(pathlib.Path(root).glob("*.py"))]
    for path in [p for r in roots for p in sorted(r.rglob("*.py"))]:
        if "__pycache__" in path.parts:
            continue
        try:
            src = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if target not in src:
            continue
        tree = ast.parse(src)

        mod = set()
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                mod |= {a.asname or a.name.split(".")[0] for a in n.names}
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                mod.add(n.name)
            elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    if isinstance(t, ast.Name):
                        mod.add(t.id)

        inside = set()
        for fn in [f for f in ast.walk(tree)
                   if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            loc = {a.arg for a in list(fn.args.args) + list(fn.args.posonlyargs)
                   + list(fn.args.kwonlyargs)}
            for extra in (fn.args.vararg, fn.args.kwarg):
                if extra is not None:
                    loc.add(extra.arg)
            for sub in ast.walk(fn):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    loc |= {a.asname or a.name.split(".")[0] for a in sub.names}
                elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    loc.add(sub.name)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                    loc.add(sub.id)
            inside.update(id(x) for x in ast.walk(fn))
            for x in ast.walk(fn):
                if (isinstance(x, ast.Name) and x.id == target
                        and isinstance(x.ctx, ast.Load)
                        and target not in mod and target not in loc):
                    out.append((str(path), x.lineno, fn.name))

        for x in ast.walk(tree):
            if (isinstance(x, ast.Name) and x.id == target and isinstance(x.ctx, ast.Load)
                    and id(x) not in inside and target not in mod):
                out.append((str(path), x.lineno, "<module>"))
    return out


def test_apply_display_name_call_sites_resolve():
    """本轮实测踩过：`apply_display_name(...)` 写进了 smart_ingest / storage_watcher
    却没导入，NameError 被外层 `except Exception` 吞成一行日志，整条入库路径静默不干活。
    规则接线容易只 grep 调用点、不看导入，所以这里用 AST 把「调用即可解析」钉死。"""
    backend = os.path.dirname(os.path.dirname(os.path.abspath(doc_naming.__file__)))
    bad = _unresolved_uses(backend, "apply_display_name")
    assert not bad, "调用点无法解析名字，运行到就 NameError：" + "; ".join(
        f"{p}:{ln} in {fn}" for p, ln, fn in bad)
