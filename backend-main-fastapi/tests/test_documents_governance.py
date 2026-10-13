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
