"""入库闸门收口（A + B）。

背景（本轮审计实测）：库里之所以"依旧导入了很多有问题的东西"，根因之一是
**入库入口各写各的** —— 八个写 `Document.content` 的地方只有 smart_ingest 走了
校验，其余直接写库并标 indexed。所以这里用 AST 把两件事钉死：

1. 任何给 `X.content` 赋值的函数，必须同时调用 `gate_for_write`（或
   `validate_for_ingest`）—— 漏接一个新入口就红。
2. 调用点必须真的能解析到名字（上一轮踩过"写了调用没写 import，被外层
   except 吞成一行日志"的 BLOCKER）。

B 部分测块级谓词：短块/乱码块不写 knowledge_chunks，因此也不可能进 FTS 镜像。

红线：只用 conftest 的临时库，绝不碰 D:\\平台\\database\\kaoyan.db。
"""
from __future__ import annotations

import ast
import os

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE_CALLS = {"gate_for_write", "validate_for_ingest"}


# --------------------------------------------------------------------------- #
# 1. 静态守卫：写正文的地方必须接闸
# --------------------------------------------------------------------------- #
def _py_files(*dirs):
    for d in dirs:
        base = os.path.join(BACKEND, d)
        for root, _dirs, files in os.walk(base):
            if any(part in root for part in (os.sep + "tests", "__pycache__", "static")):
                continue
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)


def _call_names(fn: ast.AST) -> set:
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                out.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                out.add(node.func.attr)
    return out


def _content_writers():
    """返回 [(文件, 行号, 函数名)]：给 `X.content` 赋值、却没接闸的函数。"""
    bad = []
    for path in _py_files("routers", "services", "scripts"):
        with open(path, encoding="utf-8-sig") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            writes = [n for n in ast.walk(fn)
                      if isinstance(n, (ast.Assign, ast.AugAssign))
                      and any(isinstance(t, ast.Attribute) and t.attr == "content"
                              for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))
                      ]
            # Document(content=...) 构造参数也算写入
            writes += [n for n in ast.walk(fn)
                       if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name) and n.func.id == "Document"
                       and any(kw.arg == "content" for kw in n.keywords)]
            if not writes:
                continue
            if not (GATE_CALLS & _call_names(fn)):
                bad.append((os.path.relpath(path, BACKEND).replace(os.sep, '/'),
                            writes[0].lineno, fn.name))
    return bad


#: 已核对过、**不需要**接闸的写正文处，逐条给理由。
#: 加了新的一处必须写理由，否则测试红 —— 这正是本文件要的强制性。
#: 注意 scripts/diagnostics/batch_process.py 以前就在这张表里（它是唯一没接闸的
#: 入库入口，而且用的列名和状态值在真实表里全都不存在）；现在它接了闸、状态
#: 改成「有可检索分块才算 indexed」，所以这张表必须是空的：
#: 任何新入口漏接闸门，本测试直接红。
CONTENT_WRITE_EXEMPT = {
    # 跨来源去重自测脚本：全程在自己的**临时库**里造 Document 当夹具，
    # 不是入库入口（正文是手写的 STEM 常量，本来就短，接闸只会被长度规则拦掉，
    # 反而测不到它要测的去重逻辑）。
    ('scripts/test_cross_source_dedupe.py', 'main'),
}


def test_content_write_sites_are_gated():
    offenders = [o for o in _content_writers() if (o[0], o[2]) not in CONTENT_WRITE_EXEMPT]
    assert not offenders, (
        "以下位置写 Document.content 但没过入库闸门 "
        f"{sorted(GATE_CALLS)}（脏数据就是从这种入口进来的）："
        + "; ".join(f"{p}:{ln} in {fn}" for p, ln, fn in offenders))


def _bare_calls(node) -> set:
    '''函数名形态的调用（``gate_for_write(...)`` 这种裸名）。

    只看裸名是刻意的：本轮踩过的 BLOCKER 就是「写了调用却没写 import」，
    NameError 被入口外层的 except 吞成一行日志，看起来接了闸、实际一篇都没校验。
    '''
    return {n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


def _bound_names(tree) -> set:
    '''模块里可用的名字：任意层级的 import + 任意层级的 def（含函数内导入）。'''
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            bound |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            bound |= {a.asname or a.name.split('.')[0] for a in node.names}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
    return bound


def test_gate_call_sites_resolve_the_name():
    '''每个调用点所在文件必须真的能解析到那个名字（import 进来或本文件定义）。'''
    bad = []
    for path in _py_files('routers', 'services', 'scripts'):
        with open(path, encoding='utf-8-sig') as fh:
            tree = ast.parse(fh.read(), filename=path)
        used = GATE_CALLS & _bare_calls(tree)
        if not used:
            continue
        for name in sorted(used - _bound_names(tree)):
            bad.append(f'{os.path.relpath(path, BACKEND)}: 调用了 {name} 但名字无法解析')
    assert not bad, '; '.join(bad)


# --------------------------------------------------------------------------- #
# 2. 文档级闸门行为（临时库）
# --------------------------------------------------------------------------- #
GOOD = ("第 3 章 一元函数积分学\n" +
        "本节讨论不定积分的换元法与分部积分法，配套 2019 年数学一真题讲解，"
        "要求掌握三角代换、倒代换以及有理函数积分的部分分式分解。") * 6


def _body(tag: str) -> str:
    '''给每个用例一份独立正文。

    闸门本身带「正文全等去重」，同一库内重复用同一份正文会被判成重复导入 ——
    那是正确行为，但会让不同用例互相污染，所以每个用例自带标题。
    '''
    return tag + "\n" + GOOD



@pytest.fixture(autouse=True)
def _purge_created_docs():
    yield
    if not _CREATED_DOCS:
        return
    from database import SessionLocal
    from sqlalchemy import text as sql_text

    db = SessionLocal()
    try:
        for doc_id in _CREATED_DOCS:
            for tbl in ("knowledge_chunks_fts", "knowledge_chunks", "documents"):
                col = "document_id" if tbl != "documents" else "id"
                db.execute(sql_text(f"DELETE FROM {tbl} WHERE {col}=:i"), {"i": doc_id})
        db.commit()
    finally:
        db.close()
        _CREATED_DOCS.clear()

def _session():
    from database import SessionLocal

    return SessionLocal()


#: 本文件写进临时库的 Document id，teardown 一律清掉。
#: 临时库是 session 级的，不清就会留下「indexed 但零分块」的幽灵行，
#: 让别的用例的全库计数变成随机数（实测已经干扰过 ghost 指标用例）。
_CREATED_DOCS: list = []


def _insert_doc(db, content, file_name, file_path):
    from models import Document

    # PG 的 ck_documents_canonical 要求 canonical_content 非空（content 由触发器
    # 双向同步）；空正文夹具给一行占位，不影响闸门断言。
    d = Document(file_name=file_name, file_path=file_path, content=content or "# 占位正文",
                 index_status="indexed")
    db.add(d)
    db.commit()
    db.refresh(d)
    return d
    _CREATED_DOCS.append(d.id)


def test_placeholder_and_empty_are_rejected(db_schema):  # noqa: ARG001
    from services.smart_ingest import gate_for_write

    db = _session()
    try:
        for bad in ("", "   ", "[扫描版 PDF OCR 失败: No module named PIL]",
                    "[pdf 文件，未能提取到文本内容] 文件名：01.pdf"):
            v = gate_for_write(db, bad, path="knowledge_base/数学/a.pdf")
            assert not v["ok"], f"占位/空正文竟然放行：{bad[:40]!r}"
    finally:
        db.close()


def test_self_produced_files_are_rejected(db_schema):  # noqa: ARG001
    """目录扫描器把上一批自己写的 README/切块产物读回来 = 自我喂食。"""
    from services.smart_ingest import gate_for_write, is_self_produced

    db = _session()
    try:
        for p in ("D:/平台/knowledge_base/README.md",
                  "D:/平台/knowledge_base/数学/chunks/0001.md",
                  "D:/平台/knowledge_base/_trash/旧版.pdf"):
            assert is_self_produced(p), p
            v = gate_for_write(db, GOOD, path=p)
            assert not v["ok"], p
        assert not is_self_produced("D:/平台/knowledge_base/数学/第一章讲义.pdf")
    finally:
        db.close()


def test_identical_content_rejected_and_self_excluded(db_schema):  # noqa: ARG001
    """正文全等去重：同文不同路径不能各长出一份 Document + 一整套分块。

    现库实测这种重复有 95 组、多算 150 行。
    """
    from services.smart_ingest import gate_for_write

    db = _session()
    try:
        # 前置清理：历史运行残留的同正文文档会让 dedup 命中错误 id
        from sqlalchemy import text as _t

        stale = db.execute(_t("SELECT id FROM documents WHERE content = :c"),
                           {"c": GOOD}).fetchall()
        for (sid,) in stale:
            db.execute(_t("DELETE FROM knowledge_chunks WHERE document_id=:d"), {"d": sid})
            db.execute(_t("DELETE FROM documents WHERE id=:d"), {"d": sid})
        db.commit()
        d1 = _insert_doc(db, GOOD, "讲义A.pdf", "knowledge_base/数学/讲义A.pdf")
        v = gate_for_write(db, GOOD, path="knowledge_base/公共课/讲义A副本.pdf")
        assert not v["ok"] and v["dedup_hit"], v["reasons"]
        assert f"#{d1.id}" in " ".join(v["reasons"])

        # 重新解析同一篇：必须把自己排除，否则永远判重、再也无法重入库
        v2 = gate_for_write(db, GOOD, path=d1.file_path, doc_id=d1.id)
        assert v2["ok"] and not v2["dedup_hit"], v2["reasons"]

        # 短正文不做指纹（本来就短，不值得当重复）
        assert gate_for_write(db, "只有一行", path="x/其它.pdf")["ok"] is False  # 长度闸门拦
    finally:
        db.close()


def test_binary_residue_rejected_but_readable_text_kept(db_schema):  # noqa: ARG001
    """不可读字节成串 + 正文既没中文也没成型英文才判死；可读文档只复核不丢。"""
    from services.smart_ingest import gate_for_write

    db = _session()
    try:
        binary = ("2021 年真题\n" + "".join(
            chr(c) for c in (0x00, 0x01, 0x02, 0x03, 0x1A, 0x7F, 0x80, 0x90)) * 90)
        v = gate_for_write(db, binary, path="knowledge_base/数学/ole.pdf")
        assert not v["ok"], v["reasons"]

        # 真文档形态：中文正文里夹几个孤立控制字符 -> 放过（只打 need_review）
        noisy = _body("用例甲 零散控制符") + "".join(chr(c) for c in (0x00, 0x1A, 0x7F)) * 4
        v2 = gate_for_write(db, noisy, path="knowledge_base/数学/真题.pdf")
        assert v2["ok"], v2["reasons"]
        assert v2["review_flag"] == "need_review"

        # 排版空白（\t \v \f 0x1C-0x1E）不计入不可读字节
        ws = _body("用例乙 排版空白") + "".join(chr(c) for c in (0x09, 0x0B, 0x0C, 0x1C, 0x1D, 0x1E)) * 20
        v3 = gate_for_write(db, ws, path="knowledge_base/数学/讲义.pdf")
        assert v3["ok"] and v3["review_flag"] == "auto_pass", v3["reasons"]
    finally:
        db.close()


def test_mojibake_rejected(db_schema):  # noqa: ARG001
    from services.smart_ingest import gate_for_write

    db = _session()
    try:
        # 阈值 MAX_MOJIBAKE_RATIO=0.10 只数 U+FFFD，所以取样里替换符必须真的过线
        # （这里 120/600=20%）。只堆「锟斤拷」是测不到这条规则的 —— 它是 GBK 误
        # 解码出的合法汉字，字节层面完全可读，闸门按定义不该拦它。
        junk = '锟斤拷' * 160 + chr(0xFFFD) * 120
        v = gate_for_write(db, junk, path="knowledge_base/英语/坏编码.pdf")
        assert not v["ok"] and any("乱码" in r for r in v["reasons"]), v["reasons"]
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 3. 块级谓词（B）
# --------------------------------------------------------------------------- #
def test_chunk_gate_filters_bad_chunks_and_keeps_mirror_in_sync(db_schema):  # noqa: ARG001
    """短块/乱码块不写 knowledge_chunks；写了的块必须同时在 FTS 里。"""
    from sqlalchemy import text as sql_text

    from services.kb_service import chunk_is_retrievable, ingest_text

    db = _session()
    try:
        assert chunk_is_retrievable("正常的一块，" * 20)
        assert not chunk_is_retrievable("半行残句")
        assert not chunk_is_retrievable((chr(0xFFFD) + "乱") * 60)
        # 500 字里 1 个替换符的真块不能被删
        assert chunk_is_retrievable("逻辑代数的基本运算与公式。" * 40 + chr(0xFFFD))

        d = _insert_doc(db, "", "GATE-chunk.pdf", "knowledge_base/数电/GATE-chunk.pdf")
        body = ("第一章 逻辑代数\n" + "逻辑代数的基本公式与卡诺图化简方法举例。" * 12
                + "\n\n残句\n\n" + "第二章 组合电路分析\n" + "方法步骤与例题详解。" * 12)
        n = ingest_text(db, d.id, d.file_name, body, subject="数字电子技术", replace=True)
        assert n > 0
        cnt = int(db.execute(sql_text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=:d"), {"d": d.id}).scalar())
        fts = int(db.execute(sql_text(
            "SELECT COUNT(*) FROM knowledge_chunks_fts WHERE document_id=:d"), {"d": d.id}).scalar())
        assert cnt == n and fts == n, (cnt, fts, n)
        short = db.execute(sql_text(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE document_id=:d "
            "AND length(text) < 80"), {"d": d.id}).scalar()
        assert int(short) == 0, "短块仍然进了知识库"
    finally:
        db.close()
