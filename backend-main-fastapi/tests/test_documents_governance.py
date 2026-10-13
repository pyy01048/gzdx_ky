# -*- coding: utf-8 -*-
"""学习文库 / 文档知识库治理：导出 · 归档 · 扫描归档（含断链跳过）。

本文件重点覆盖本任务最硬的一块：``scan_root_and_archive`` 的**断链跳过**分支。

背景（实测）：真库 2172 篇 file_path 里 315 篇文件已不在盘上。若"按科目归档"
的实现遇到找不到文件就整体抛异常，则存量断链记录会把整批归档一起带崩。
因此这里断言：断链只计入 ``broken``、**不抛异常**、不影响其它文件正常归档。

隔离：全部落在 conftest 的临时测试库 + tmp 目录里，绝不碰真库 / 真 knowledge_base。
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture()
def kb_tmp(tmp_path):
    """独立的知识库根目录（挂到环境变量，保证 resolve_kb_root 也指向它）。"""
    root = tmp_path / "knowledge_base"
    root.mkdir()
    return str(root)


def _mk_doc(db, *, file_name, file_path, content="", subject=None):
    from models import Document

    doc = Document(
        file_name=file_name, file_path=file_path, file_type="txt",
        size=10, subject=subject, index_status="indexed", content=content,
        parse_progress=1.0,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def test_scan_root_moves_file_and_syncs_path(db_schema, kb_tmp, monkeypatch):
    """根目录文件 → 按科目归档：文件真的被移动，DB file_path 同步更新。"""
    monkeypatch.setenv("KAOYAN_KB_ROOT", kb_tmp)
    from database import SessionLocal
    from services.kb_service import scan_root_and_archive

    src = os.path.join(kb_tmp, "数电真题2020.txt")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("数字电子技术真题正文")

    db = SessionLocal()
    try:
        doc = _mk_doc(db, file_name="数电真题2020.txt", file_path=src)
        report = scan_root_and_archive(db, kb_root=kb_tmp)

        assert report["moved"] == 1, report
        assert not os.path.exists(src), "源文件应已被移动到科目目录"
        db.refresh(doc)
        assert os.path.isfile(doc.file_path), "DB file_path 应指向移动后的真实文件"
        assert doc.file_path != src
        # 新路径应落在 knowledge_base/{科目}/ 下
        assert os.path.dirname(doc.file_path) != kb_tmp
    finally:
        db.close()


def test_scan_root_broken_link_is_counted_not_raised(db_schema, kb_tmp, monkeypatch):
    """**核心分支**：file_path 指向已不存在的文件（断链）→ 计入 broken、不抛异常。"""
    monkeypatch.setenv("KAOYAN_KB_ROOT", kb_tmp)
    from database import SessionLocal
    from services.kb_service import scan_root_and_archive

    missing = os.path.join(kb_tmp, "已删除的数电讲义.txt")  # 故意不创建文件

    db = SessionLocal()
    try:
        doc = _mk_doc(db, file_name="已删除的数电讲义.txt", file_path=missing)
        # 关键：这一行不得抛异常（存量 315 篇断链的真实场景）
        report = scan_root_and_archive(db, kb_root=kb_tmp)

        assert report["broken"] >= 1, report
        ids = {it["doc_id"] for it in report["broken_items"]}
        assert doc.id in ids
        # 断链文档的 file_path 不被改动
        db.refresh(doc)
        assert doc.file_path == missing
    finally:
        db.close()


def test_scan_root_broken_does_not_block_healthy_files(db_schema, kb_tmp, monkeypatch):
    """断链与正常文件混在一起：断链计入 broken，正常文件照样归档成功。"""
    monkeypatch.setenv("KAOYAN_KB_ROOT", kb_tmp)
    from database import SessionLocal
    from services.kb_service import scan_root_and_archive

    good = os.path.join(kb_tmp, "模电放大器笔记.txt")
    with open(good, "w", encoding="utf-8") as fh:
        fh.write("模拟电子技术 共射极放大电路")
    broken = os.path.join(kb_tmp, "早就没了.txt")

    db = SessionLocal()
    try:
        _mk_doc(db, file_name="模电放大器笔记.txt", file_path=good)
        _mk_doc(db, file_name="早就没了.txt", file_path=broken)
        report = scan_root_and_archive(db, kb_root=kb_tmp)

        assert report["moved"] == 1, report
        assert report["broken"] >= 1, report
        assert report["errors"] == 0, report
    finally:
        db.close()


def test_scan_root_dry_run_does_not_touch_disk(db_schema, kb_tmp, monkeypatch):
    """dry_run 只预览：文件不动、DB file_path 不变。"""
    monkeypatch.setenv("KAOYAN_KB_ROOT", kb_tmp)
    from database import SessionLocal
    from services.kb_service import scan_root_and_archive

    src = os.path.join(kb_tmp, "电路分析基础.txt")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write("电路的戴维南等效")

    db = SessionLocal()
    try:
        doc = _mk_doc(db, file_name="电路分析基础.txt", file_path=src)
        report = scan_root_and_archive(db, kb_root=kb_tmp, dry_run=True)
        assert report["moved"] == 1, report
        assert os.path.isfile(src), "dry_run 不应移动文件"
        db.refresh(doc)
        assert doc.file_path == src
    finally:
        db.close()


def test_export_md_and_txt(db_schema, kb_tmp, monkeypatch):
    """导出统一快照：md 带 front-matter；txt 是纯正文；两者都做水印预清洗。"""
    from services.kb_service import export_document
    from models import Document

    doc = Document(
        id=999001, file_name="数电真题.txt", file_type="txt", subject="数字电子技术",
        content="8位DAC转换器，设转换系数k=0.05\n东坡哥微信:haidongpo8\n正文续行",
    )

    md = export_document(doc, "md")
    assert md["filename"].endswith(".md")
    text = md["data"].decode("utf-8-sig")
    assert text.startswith("---"), "md 应带 YAML front-matter"
    assert "doc_id: 999001" in text
    assert "haidongpo" not in text, "导出时应已预清洗水印"

    txt = export_document(doc, "txt")
    assert txt["filename"].endswith(".txt")
    t = txt["data"].decode("utf-8-sig")
    assert not t.startswith("---")
    assert "8位DAC转换器" in t
    assert "haidongpo" not in t


def test_preclean_watermarks_shared_rule():
    """预清洗与存量脚本共用同一份规则（services.extraction_noise）。"""
    from services.kb_service import preclean_watermarks
    from services.extraction_noise import clean_document_text

    text = "微信公众号:电子与通信工程考研\n正常题目正文"
    cleaned, _d, _m = preclean_watermarks(text)
    assert "微信公众号" not in cleaned
    assert "正常题目正文" in cleaned
    # 与底层规则完全一致（同源，不是两套）
    assert cleaned == clean_document_text(text)[0]


# --------------------------------------------------------------------------- #
# M0-5 断链可追溯性：broken-links（只读）+ repair-file-paths（默认 dry_run）
# --------------------------------------------------------------------------- #

def _isolate_kb_index(tmp_path, monkeypatch):
    """把文件索引根与本地可读白名单都换成临时目录，绝不扫真 knowledge_base。"""
    import routers.documents as docs_router
    from services import kb_pipeline

    kb = tmp_path / "kb"
    kb.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(kb_pipeline, "_find_storage_roots", lambda: [str(kb)])
    # abspath 与白名单用同一口径（abspath），避免 Windows 短路径/符号链接导致误判
    monkeypatch.setattr(docs_router, "LOCAL_FILE_ROOTS", [os.path.abspath(str(tmp_path))])
    return kb


def test_broken_links_marks_recoverable_and_not_found(db_schema, tmp_path, monkeypatch):
    """断链报告：一条按文件名能找回（含 .pdf 回退）、一条找不回；只读不写库。"""
    import asyncio

    import routers.documents as docs_router

    kb = _isolate_kb_index(tmp_path, monkeypatch)
    real = kb / "数字电子技术" / "数电真题2020.pdf"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("真题正文", encoding="utf-8")

    from database import SessionLocal

    db = SessionLocal()
    try:
        # 可找回：登记路径已失效，但同名文件在 knowledge_base 里
        recov = _mk_doc(db, file_name="数电真题2020.pdf",
                        file_path=str(tmp_path / "旧位置" / "数电真题2020.pdf"))
        # 找不回：登记路径失效，盘上也没有同名文件
        lost = _mk_doc(db, file_name="彻底没了-孤本.pdf",
                       file_path=str(tmp_path / "旧位置" / "彻底没了-孤本.pdf"))
        recov_id, lost_id = recov.id, lost.id

        report = asyncio.run(docs_router.list_broken_links(db))

        by_id = {it["doc_id"]: it for it in report["items"]}
        assert recov_id in by_id, report
        assert lost_id in by_id, report
        assert by_id[recov_id]["candidates"], "同名文件在库，应给出候选路径"
        assert os.path.isfile(by_id[recov_id]["candidates"][0])
        assert by_id[lost_id]["candidates"] == []
        assert report["recoverable"] >= 1
        assert report["not_found"] >= 1
        # 只读：登记路径分毫未动
        db.refresh(recov)
        db.refresh(lost)
        assert recov.file_path.endswith("数电真题2020.pdf")
        assert recov.file_path.startswith(str(tmp_path))
    finally:
        db.close()


def test_repair_file_paths_dry_run_does_not_write(db_schema, tmp_path, monkeypatch):
    """默认 dry_run：给出 old→new 计划，但**不写库**（真实 file_path 不变）。"""
    import asyncio

    import routers.documents as docs_router

    kb = _isolate_kb_index(tmp_path, monkeypatch)
    real = kb / "模拟电子技术" / "模电笔记.txt"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("共射极放大电路", encoding="utf-8")

    from database import SessionLocal

    db = SessionLocal()
    try:
        doc = _mk_doc(db, file_name="模电笔记.txt",
                      file_path=str(tmp_path / "旧位置" / "模电笔记.txt"))
        old_path = doc.file_path

        report = asyncio.run(
            docs_router.repair_document_file_paths(dry_run=True, db=db)
        )

        assert report["dry_run"] is True
        assert report["recoverable"] >= 1
        assert report["not_found"] >= 1
        planned = {p["doc_id"]: p for p in report["plan"]}
        assert doc.id in planned, report
        assert planned[doc.id]["new"] == str(real)
        assert planned[doc.id]["old"] == old_path
        # 关键：dry_run 不得落库
        db.refresh(doc)
        assert doc.file_path == old_path, "dry_run 不得修改 file_path"
    finally:
        db.close()
