"""检索镜像学科同步（#31）回归测试。

存在的意义：回填/弃权只写 `knowledge_chunks.subject`，而检索的学科过滤打在
fts / vec **镜像列**上。全库实测漂移 15.90%、1235 块弃权后镜像仍挂具体学科 ——
即分类结果压根没进召回。这组测试锁住"标签 → 镜像"这条链路，并锁住镜像表缺失时
不得影响已提交标签的容错契约。

只用 conftest 的临时库（红线：绝不碰 D:\\平台\\database\\kaoyan.db）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


def _make_mirrors(db):
    """建 fts / vec 镜像表（PG 兼容普通表）。

    PG 生产路径走 knowledge_chunks.search_vector 原生列，服务侧刻意不建镜像表；
    本组测试锁的是 sync_mirror_subjects 的镜像同步契约，故自建普通表承载契约。
    """
    from sqlalchemy import text as _text
    db.execute(_text("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks_fts (
            chunk_id INTEGER, document_id INTEGER,
            subject VARCHAR, content TEXT
        )"""))
    db.execute(_text("""
        CREATE TABLE IF NOT EXISTS knowledge_chunks_vec (
            chunk_id INTEGER, document_id INTEGER,
            subject VARCHAR, embedding BYTEA, dim INTEGER
        )"""))
    db.commit()


def _drop_mirrors(db):
    for t in ("knowledge_chunks_fts", "knowledge_chunks_vec"):
        db.execute(text(f"DROP TABLE IF EXISTS {t}"))
    db.commit()


def _seed(db, subjects, stale):
    """建一篇文档 + N 个块，镜像 subject 故意写成旧值 stale。返回 chunk id 列表。"""
    from models import Document, KnowledgeChunk

    doc = Document(file_name="mirror_sync_fixture.pdf", subject="数字电子技术",
                   content="# 镜像同步夹具")
    db.add(doc)
    db.flush()
    from services.dbapi_compat import wrap_conn
    conn = wrap_conn(db.connection().connection)
    ids = []
    for i, subj in enumerate(subjects):
        c = KnowledgeChunk(document_id=doc.id, doc_name=doc.file_name, chunk_id=i,
                           subject=subj, text=f"三态门与总线负载 计算题 {i}")
        db.add(c)
        db.flush()
        ids.append(c.id)
        conn.execute(
            "INSERT INTO knowledge_chunks_fts (chunk_id, document_id, subject, content)"
            " VALUES (?,?,?,?)", (c.id, doc.id, stale, c.text))
        conn.execute(
            "INSERT INTO knowledge_chunks_vec (chunk_id, document_id, subject, embedding, dim)"
            " VALUES (?,?,?,?,?)", (c.id, doc.id, stale, b"\x00\x01", 2))
    db.commit()
    return doc.id, ids


def _mirror_map(db):
    out = {}
    for tbl, key in (("knowledge_chunks_fts", "chunk_id"), ("knowledge_chunks_vec", "chunk_id")):
        out[tbl] = {int(i): (s or "") for i, s in
                    db.execute(text(f"SELECT {key}, subject FROM {tbl}")).fetchall()}
    return out


def _cleanup(db, doc_id):
    """按 FK 顺序清理夹具数据（vec/fts 引用 knowledge_chunks，chunks 引用 documents）。"""
    db.execute(text("DELETE FROM knowledge_chunks_vec WHERE document_id=:d"), {"d": doc_id})
    db.execute(text("DELETE FROM knowledge_chunks_fts WHERE document_id=:d"), {"d": doc_id})
    db.execute(text("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": doc_id})
    db.execute(text("DELETE FROM documents WHERE id=:d"), {"d": doc_id})
    db.commit()


def test_sync_updates_both_mirrors(db_schema):  # noqa: ARG001
    from database import SessionLocal
    from services.chunk_classifier import sync_mirror_subjects

    db = SessionLocal()
    try:
        _drop_mirrors(db)
        _make_mirrors(db)
        doc_id, ids = _seed(db, ["数学", "英语", "政治"], stale="电路")
        m = _mirror_map(db)
        assert m["knowledge_chunks_fts"][ids[0]] == "电路", "夹具应先处于漂移态"

        synced = sync_mirror_subjects(db, ids)
        assert synced["knowledge_chunks_fts"] >= 0 and synced["knowledge_chunks_vec"] >= 0
        m = _mirror_map(db)
        for cid, want in zip(ids, ["数学", "英语", "政治"]):
            assert m["knowledge_chunks_fts"][cid] == want
            assert m["knowledge_chunks_vec"][cid] == want
        _cleanup(db, doc_id)
    finally:
        db.close()


def test_sync_is_idempotent_and_full_table_mode_clears_everything(db_schema):  # noqa: ARG001
    from database import SessionLocal
    from services.chunk_classifier import sync_mirror_subjects

    db = SessionLocal()
    try:
        _drop_mirrors(db)
        _make_mirrors(db)
        doc_id, ids = _seed(db, ["数学", "英语"], stale="光学")
        assert sync_mirror_subjects(db)["knowledge_chunks_fts"] >= 0   # 不传 ids = 全库
        m = _mirror_map(db)
        assert all(m["knowledge_chunks_fts"][i] == s for i, s in zip(ids, ["数学", "英语"]))
        again = sync_mirror_subjects(db)                                # 再跑一次不应报错
        assert again["knowledge_chunks_fts"] >= 0
        _cleanup(db, doc_id)
    finally:
        db.close()


def test_sync_tolerates_missing_mirror_tables(db_schema):  # noqa: ARG001
    """镜像表尚未创建时：只告警、返回 -1，绝不抛，也不回滚已提交的标签。"""
    from database import SessionLocal
    from models import KnowledgeChunk
    from services.chunk_classifier import sync_mirror_subjects

    db = SessionLocal()
    try:
        _drop_mirrors(db)
        cid = db.query(KnowledgeChunk).filter(KnowledgeChunk.subject.isnot(None)).first()
        ids = [cid.id] if cid else [999999]
        res = sync_mirror_subjects(db, ids)
        assert res["knowledge_chunks_fts"] == -1
        assert res["knowledge_chunks_vec"] == -1
    finally:
        db.close()


def test_empty_id_list_writes_nothing(db_schema):  # noqa: ARG001
    from database import SessionLocal
    from services.chunk_classifier import sync_mirror_subjects

    db = SessionLocal()
    try:
        _make_mirrors(db)
        assert sync_mirror_subjects(db, []) == {
            "knowledge_chunks_fts": 0, "knowledge_chunks_vec": 0}
    finally:
        db.close()


def test_missing_mirror_rows_are_announced(db_schema, caplog):  # noqa: ARG001
    """块在镜像里**根本没有行**时，UPDATE 一行都不动 = 打标对检索无效。

    这是 code review 抓到的"静默失败"：不吼一声的话，59 块未进 fts / 42925 块未进
    vec 会永远藏在"同步成功"的返回值后面。
    """
    import logging

    from database import SessionLocal
    from services.chunk_classifier import sync_mirror_subjects

    db = SessionLocal()
    try:
        _make_mirrors(db)
        doc_id, ids = _seed(db, ["数字电子技术", "模拟电子技术"], "旧学科")
        # 把第二个块的镜像行删掉，模拟"块有、镜像无"
        db.execute(text("DELETE FROM knowledge_chunks_fts WHERE chunk_id=:c"), {"c": ids[1]})
        db.execute(text("DELETE FROM knowledge_chunks_vec WHERE chunk_id=:c"), {"c": ids[1]})
        db.commit()

        with caplog.at_level(logging.WARNING):
            res = sync_mirror_subjects(db, ids)
        assert res["knowledge_chunks_fts"] == 1          # 只有存在的那行被更新
        assert res["knowledge_chunks_vec"] == 1
        warns = " | ".join(r.message for r in caplog.records if r.levelno >= logging.WARNING)
        assert "缺 1/2 个块" in warns, f"未报告缺行：{warns}"
        _cleanup(db, doc_id)
    finally:
        db.close()


def test_full_table_sync_leaves_orphan_mirror_rows_alone(db_schema):  # noqa: ARG001
    """孤儿镜像行（chunk 已不在）不得被关联子查询刷成 NULL —— 否则体检会把
    "孤儿行"误报成"学科漂移"。孤儿只由 `--prune-orphans` 显式处理。
    """
    from database import SessionLocal
    from services.chunk_classifier import sync_mirror_subjects

    db = SessionLocal()
    try:
        _make_mirrors(db)
        doc_id, ids = _seed(db, ["数字电子技术"], "旧学科")
        from services.dbapi_compat import wrap_conn as _wc
        conn = _wc(db.connection().connection)
        conn.execute("INSERT INTO knowledge_chunks_fts (chunk_id, document_id, subject, content)"
                     " VALUES (?,?,?,?)", (999991, 999990, "孤儿学科", "孤儿内容"))
        db.commit()

        sync_mirror_subjects(db)                    # 全表模式
        m = _mirror_map(db)
        assert m["knowledge_chunks_fts"].get(ids[0]) == "数字电子技术"
        assert m["knowledge_chunks_fts"].get(999991) == "孤儿学科", "孤儿行被改写了"

        db.execute(text("DELETE FROM knowledge_chunks_fts WHERE chunk_id=999991"))
        db.commit()
        _cleanup(db, doc_id)
    finally:
        db.close()


def test_manual_label_endpoint_writes_through_to_mirrors(db_schema, client):  # noqa: ARG001
    """人工修正接口必须同步镜像，否则「标签已改、检索照旧」——与 #31 同一类缺陷。

    review 实测该接口原先只 commit chunk 表，没调 `sync_mirror_subjects`。
    """
    from database import SessionLocal
    from services import search_service as ss

    db = SessionLocal()
    doc_id = None
    try:
        _make_mirrors(db)
        doc_id, ids = _seed(db, ["数字电子技术"], "旧学科")
        cid = ids[0]
        r = client.post(f"/api/documents/chunks/{cid}/label",
                        json={"subject": "模拟电子技术", "user": "qa"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subject"] == "模拟电子技术"
        assert body["mirror_synced"]["knowledge_chunks_fts"] == 1

        from services.dbapi_compat import wrap_conn as _wc
        conn = _wc(db.connection().connection)
        for tbl in ("knowledge_chunks_fts", "knowledge_chunks_vec"):
            got = conn.execute(f"SELECT subject FROM {tbl} WHERE chunk_id=?",
                               (cid,)).fetchone()[0]
            assert got == "模拟电子技术", f"{tbl} 镜像没跟着人工修正: {got}"
    finally:
        if doc_id is not None:
            _cleanup(db, doc_id)
        db.close()


def test_classify_document_propagates_abstention_to_mirror(db_schema, monkeypatch):  # noqa: ARG001
    """弃权块（subject→其他）必须同步进镜像，否则它仍会出现在原学科池里。"""
    from database import SessionLocal
    from models import Document, KnowledgeChunk
    from services import chunk_classifier as cc

    db = SessionLocal()
    try:
        _drop_mirrors(db)
        _make_mirrors(db)
        doc = Document(file_name="abstain_fixture.pdf", subject="数学", content="# 弃权夹具")
        db.add(doc)
        db.flush()
        good = KnowledgeChunk(document_id=doc.id, doc_name=doc.file_name, chunk_id=0,
                              subject="光学", text="拉普拉斯变换的收敛域与性质，求象函数")
        junky = KnowledgeChunk(document_id=doc.id, doc_name=doc.file_name, chunk_id=1,
                               subject="光学", text="\ue000\ue001 \ue002\ue003 pdf \ue004" * 3)
        db.add_all([good, junky])
        db.commit()
        # commit 会释放底层连接，raw sqlite3 句柄必须重新取，不能提前缓存
        from services.dbapi_compat import wrap_conn as _wc
        _wc(db.connection().connection).executemany(
            "INSERT INTO knowledge_chunks_fts (chunk_id, document_id, subject, content)"
            " VALUES (?,?,?,?)",
            [(c.id, doc.id, "光学", c.text) for c in (good, junky)])
        db.commit()

        # 没有质心时路1 整路跳过，不触发 bge 加载（测试必须保持毫秒级）
        monkeypatch.setattr(cc, "load_prototypes", lambda d: {})
        r = cc.classify_document(db, doc.id, use_llm=False)
        assert r["ok"] is True
        assert "mirror_synced" in r

        mir = {int(i): (s or "") for i, s in db.execute(
            text("SELECT chunk_id, subject FROM knowledge_chunks_fts"
                 " WHERE document_id=:d"), {"d": doc.id}).fetchall()}
        cur = {c.id: (c.subject or "") for c in
               db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id)}
        assert mir.keys() == cur.keys()
        for cid in cur:
            assert mir[cid] == cur[cid], "镜像必须逐块等于 chunk 表标签"
        abstained = [cid for cid, s in cur.items() if s == "其他"]
        if abstained:  # 弃权命中与否取决于 junk 规则，命中就必须已同步到镜像
            assert all(mir[cid] == "其他" for cid in abstained)

        _cleanup(db, doc.id)
    finally:
        db.close()
