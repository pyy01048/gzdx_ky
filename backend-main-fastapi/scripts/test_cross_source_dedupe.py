# -*- coding: utf-8 -*-
"""跨来源去重自测（proof-of-work）。

全部在**独立的临时 SQLite 库**里跑，不碰生产库。跑的是真实写入路径的同一段代码：
构造候选 → :func:`services.quiz_dedupe.decide_insert` 判定 → 按判定真的 INSERT →
回查断言。

用例
----
0. **对照**：复现旧的去重逻辑（``source LIKE '%当前文档名%'``），证明它对
   跨来源同题**完全失效**；再用新逻辑处理同样的输入，证明能拦住。这是根因的
   可执行证据。
1. **正样本**：同一道题分别从 source_a / source_b / source_c 入库
   → 断言最终只有 1 条，且source_ids 含三个来源。
   变体：副本刻意带不同的 OCR 乱码 / 全角标点 / 空格差异（模拟真实跨来源）。
2. **负样本**：题干高度相似但确实不同的题（lim vs sin）→ 断言两条都保留。
3. **保护**：过短/空题干不参与判重（避免碎片题互相误并）。
4. **溯源补齐**：重复命中时用新副本补齐已有条缺失的答案/解析。
5. **开关**：``QUIZ_DEDUPE_CROSS_SOURCE=off`` 时退回旧行为（不去重，全插入）。

执行：
    cd backend-main-fastapi
    python scripts/test_cross_source_dedupe.py
退出码 0 = 全通过。
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from services.delete_guard import require_physical_delete_enabled  # noqa: E402

_PASS = 0
_FAIL = 0
#: 临时库路径登记（Windows 上必须先 dispose engine 才能删文件）
_TMP_PATHS: list[str] = []
_ENGINES: list = []


def check(label: str, cond: bool, extra: str = "") -> None:
    """记录一条断言结果并打印。"""
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [PASS] {label}" + (f"| {extra}" if extra else ""))
    else:
        _FAIL += 1
        print(f"  [FAIL] {label}" + (f"| {extra}" if extra else ""))


# --------------------------------------------------------------------------- #
# 用例数据
# --------------------------------------------------------------------------- #
#: 同一道题在干净来源下的题干。
STEM = "当 x→0 时，lim(1+x)^(1/x) 的值等于下列哪个选项？"

#: 同一道题，副本 B：全角标点 + 多余空格/换行（不同来源 OCR 的典型差异）。
STEM_VARIANT_B = "　当 x→0 时， lim(1+x) ^(1/x) 的值等于下列哪个选项？  "

#: 同一道题，副本 C：夹带 U+FFFD 乱码（最常见的跨来源差异）。
STEM_VARIANT_C = "当�x�→0 时，lim(1+x)^(1/x) 的值等于下列哪个选项？"

#: 负样本：与STEM 主题相邻、仅分式分子分母互换，但**确实不同**的两道题。
STEM_LIM = "计算 lim(x→0) (sin 3x) / (sin 2x) 的值。"
STEM_SIN = "计算 lim(x→0) (sin 2x) / (sin 3x) 的值。"


def _fresh_session():
    """建临时库 + 返回 (session, QuizQuestion, Document, db_path)。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from models import Document, QuizQuestion
    global _ENGINES

    fd, path = tempfile.mkstemp(suffix=".db", prefix="dedupe_selftest_")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}")
    _TMP_PATHS.append(path)
    _ENGINES.append(engine)
    # 只建测试需要的表，避免依赖生产库的迁移状态
    QuizQuestion.__table__.create(engine)
    Document.__table__.create(engine)
    return sessionmaker(bind=engine)(), QuizQuestion, Document, path


def _ingest(db, QuizQuestion, content: str, source: str, index, stats,
            *, answer=None, analysis=None, options=None):
    """模拟一条真实入库路径：判重 → 合并或插入。返回 (decision, row_or_None)。

    与 ``routers/documents.py::confirm_questions`` /
    ``services/document_analyzer.py::extract_questions`` 里接入的去重调用同一形状。
    """
    from services import quiz_dedupe as dd

    decision = dd.decide_insert(
        db, content, source, index,
        answer=answer, analysis=analysis, options=options, stats=stats,
    )
    if decision.is_insert:
        row = QuizQuestion(
            content=content,
            options=options,
            answer=answer,
            analysis=analysis,
            source=source,
            source_ids=[source],
        )
        db.add(row)
        db.flush()
        if stats is not None:
            stats.inserted += 1
        if index is not None:
            index.add(decision.fingerprint, row.id, source,
                      text=dd.canonical_text(content))
        return decision, row
    return decision, decision.existing


def main() -> int:
    from services import quiz_dedupe as dd

    print("=" * 74)
    print("跨来源去重自测")
    print("=" * 74)
    print(f"开关 {dd.ENV_SWITCH} 默认值 -> dedupe_enabled()={dd.dedupe_enabled()}")

    # -------- 用例 0：对照 —— 旧逻辑失效 vs 新逻辑生效（根因的可执行证据） -------- #
    print("\n【用例 0｜对照】旧「来源内去重」对跨来源同题失效，新逻辑能拦住")
    db, QuizQuestion, Document, path = _fresh_session()
    doc_a = Document(file_name="source_a.pdf", content=STEM)
    doc_b = Document(file_name="source_b.pdf", content=STEM_VARIANT_B)
    db.add_all([doc_a, doc_b])
    db.commit()

    # --- 旧逻辑：来源内去重（复刻 documents.py:822-826 的写法） ---
    def _legacy_is_dup(content: str, file_name: str) -> bool:
        """旧行为：只与 source 含**当前文档名**的行比前100 字。"""
        existing = {
            (q.content or "")[:100]
            for q in db.query(QuizQuestion)
            .filter(QuizQuestion.source.like(f"%{file_name}%"))
            .all()
        }
        return content[:100] in existing

    # 先按旧逻辑把两篇文档各插一条
    for doc, stem in ((doc_a, STEM), (doc_b, STEM_VARIANT_B)):
        if not _legacy_is_dup(stem, doc.file_name):
            db.add(QuizQuestion(content=stem, source=f"文档提取：{doc.file_name}",
                                source_ids=[f"文档提取：{doc.file_name}"]))
    db.commit()
    legacy_count = db.query(QuizQuestion).count()
    print(f"  旧逻辑入库两篇文档后 → 同题共 {legacy_count} 条（重复入库了）")
    check("旧「来源内去重」拦不住跨来源同题（根因复现）", legacy_count == 2,
          f"实际 {legacy_count} 条")

    # --- 新逻辑：从干净库开始，验证能拦住 ---
    # 物理删除闸门：这里 db.query(QuizQuestion).delete() 会清空整张题库表。
    # 即便是测试脚本，也绝不能在无防护状态下持有这条路径。
    require_physical_delete_enabled("quiz_questions")
    db.query(QuizQuestion).delete()
    db.commit()
    index = dd.build_index_from_db(db)
    stats = dd.DedupeStats()
    r1 = _ingest(db, QuizQuestion, STEM, "知识库:source_a.pdf", index, stats)
    r2 = _ingest(db, QuizQuestion, STEM_VARIANT_B, "知识库:source_b.pdf", index, stats)
    r3 = _ingest(db, QuizQuestion, STEM_VARIANT_C, "知识库:source_c.pdf", index, stats)
    db.commit()
    new_count = db.query(QuizQuestion).count()
    print(f"  新逻辑同样三份副本 -> action=({r1[0].action}, {r2[0].action}, {r3[0].action})")
    print(f"  新逻辑入库后 → 同题共 {new_count} 条")
    check("新「跨来源去重」把 3 份副本收敛成 1 条", new_count == 1,
          f"实际 {new_count} 条")
    db.close()

    # ---------------- 用例 1：正样本（跨来源同题 → 1 条 + 溯源含多来源） ---------------- #
    print("\n【用例 1｜正样本】同一道题分别从 source_a / source_b / source_c 入库")
    db, QuizQuestion, _Document, path = _fresh_session()
    index = dd.FingerprintIndex()
    stats = dd.DedupeStats()

    d1, r1 = _ingest(db, QuizQuestion, STEM, "知识库:source_a.pdf",
                     index, stats, answer="A", analysis="原解析")
    print(f"  入库1 source_a(干净)-> action={d1.action:5s} reason={d1.reason}")
    d2, _ = _ingest(db, QuizQuestion, STEM_VARIANT_B, "知识库:source_b.pdf",
                    index, stats, answer="A")
    print(f"  入库2 source_b(排版差异) -> action={d2.action:5s} reason={d2.reason}")
    d3, _ = _ingest(db, QuizQuestion, STEM_VARIANT_C, "知识库:source_c.pdf",
                    index, stats, answer="A")
    print(f"  入库3 source_c(OCR乱码)  -> action={d3.action:5s} reason={d3.reason}")

    db.commit()
    rows = db.query(QuizQuestion).all()
    print(f"  → 库中条数 = {len(rows)}")
    check("三份同题（干净+排版差异+OCR乱码）入库后只剩 1 条",
          len(rows) == 1, f"实际 {len(rows)} 条")
    if rows:
        raw = rows[0].source_ids
        # source_ids 是 JSON 列：SQLAlchemy 在测试表（无 JSON 类型转换）下
        # 可能返回字符串，这里用生产同款解析（quiz_dedupe._load_source_ids）读取，
        # 避免"断言的是 JSON 文本的字符"这种假失败。
        srcs = dd._load_source_ids(rows[0])
        print(f"  → 溯源 source_ids(原始) = {raw!r}")
        print(f"  → 溯源 source_ids(解析) = {srcs}")
        print(f"  → source 字段     = {rows[0].source}")
        expected = [
            "知识库:source_a.pdf",
            "知识库:source_b.pdf",
            "知识库:source_c.pdf",
        ]
        check("溯源恰好含三个来源且无多余项",
              sorted(srcs) == sorted(expected), f"实际={srcs}")
        check("溯源含全部三个来源（溯源不丢）",
              len(srcs) == 3, f"source_ids={srcs}")
        check("source 字段可读拼接了多来源",
              bool(rows[0].source) and "|" in rows[0].source, f"source={rows[0].source}")
    print(f"  → 计数上报 {stats.as_dict()}")
    check("merged=2 且 inserted=1（不静默丢弃，有上报）",
          stats.merged == 2 and stats.inserted == 1, str(stats.as_dict()))
    db.close()

    # ---------------- 用例 2：负样本（相似但不同的题 → 两条都保留） ---------------- #
    print("\n【用例 2｜负样本】题干相似但确实不同的题，两条都要保留")
    db, QuizQuestion, _Document, path = _fresh_session()
    index = dd.FingerprintIndex()
    stats = dd.DedupeStats()
    a, ra = _ingest(db, QuizQuestion, STEM_LIM, "知识库:数学一.pdf", index, stats)
    b, rb = _ingest(db, QuizQuestion, STEM_SIN, "知识库:数学二.pdf", index, stats)
    db.commit()
    rows = db.query(QuizQuestion).all()
    print(f"  入库A action={a.action} / 入库B action={b.action}")
    print(f"  题干A: {STEM_LIM}")
    print(f"  题干B: {STEM_SIN}")
    print(f"  → 库中条数 = {len(rows)}")
    check("两条相似但不同的题都入库", len(rows) == 2, f"实际 {len(rows)} 条")
    check("均判为 insert（未误判为重复）", a.is_insert and b.is_insert)
    check("merged 计数为 0（无误并）", stats.merged == 0, str(stats.as_dict()))
    db.close()

    # ---------------- 用例 3：过短碎片题不参与判重 ---------------- #
    print("\n【用例 3｜保护】过短/空题干不做判重（避免碎片题互相误并）")
    db, QuizQuestion, _Document, path = _fresh_session()
    index = dd.FingerprintIndex()
    stats = dd.DedupeStats()
    _ingest(db, QuizQuestion, "A", "知识库:x.pdf", index, stats)
    _ingest(db, QuizQuestion, "A", "知识库:y.pdf", index, stats)
    db.commit()
    rows = db.query(QuizQuestion).all()
    print(f"  → 两条 'A' 入库后共 {len(rows)} 条（too_short={stats.too_short}）")
    check("过短题干不判重（宁可留重复也绝不误并）",
          len(rows) == 2 and stats.too_short == 2, f"条数={len(rows)} too_short={stats.too_short}")
    db.close()

    # ---------------- 用例 4：溯源合并时补齐缺失字段 ---------------- #
    print("\n【用例 4｜溯源】重复命中时用新副本补齐已有条缺失的答案/解析")
    db, QuizQuestion, _Document, path = _fresh_session()
    index = dd.FingerprintIndex()
    stats = dd.DedupeStats()
    _ingest(db, QuizQuestion, STEM, "知识库:source_a.pdf", index, stats)  # 无答案
    _ingest(db, QuizQuestion, STEM_VARIANT_B, "知识库:source_b.pdf", index, stats,
            answer="A", analysis="来自B的解析")
    db.commit()
    rows = db.query(QuizQuestion).all()
    if rows:
        print(f"  → 合并后 answer={rows[0].answer!r} analysis={rows[0].analysis!r}")
        check("缺失的 answer 被补上", rows[0].answer == "A")
        check("缺失的 analysis 被补上", rows[0].analysis == "来自B的解析")
        check("补齐计数被上报", stats.enriched.get("answer") == 1, str(stats.enriched))
    db.close()

    # ---------------- 用例 5：开关可一键回滚 ---------------- #
    print("\n【用例 5｜开关】QUIZ_DEDUPE_CROSS_SOURCE=off 时退回旧行为")
    old = os.environ.get(dd.ENV_SWITCH)
    os.environ[dd.ENV_SWITCH] = "off"
    try:
        check("开关置off 后 dedupe_enabled()=False", dd.dedupe_enabled() is False)
        db, QuizQuestion, _Document, path = _fresh_session()
        index = dd.FingerprintIndex()
        stats = dd.DedupeStats()
        o1, _ = _ingest(db, QuizQuestion, STEM, "知识库:source_a.pdf", index, stats)
        o2, _ = _ingest(db, QuizQuestion, STEM_VARIANT_B, "知识库:source_b.pdf",
                        index, stats)
        db.commit()
        rows = db.query(QuizQuestion).all()
        print(f"  → 关闭去重后两条同题都插入，共 {len(rows)} 条（旧行为）")
        check("关闭开关后同题不去重（旧行为回归）",
              len(rows) == 2 and o1.is_insert and o2.is_insert, f"实际 {len(rows)} 条")
        db.close()
    finally:
        if old is None:
            os.environ.pop(dd.ENV_SWITCH, None)
        else:
            os.environ[dd.ENV_SWITCH] = old

    check("开关恢复默认后重新生效", dd.dedupe_enabled() is True)

    # 清理临时库：先 dispose 所有 engine 释放文件句柄（Windows 必需）
    for _e in _ENGINES:
        _e.dispose()
    for _p in _TMP_PATHS:
        for _suffix in ("", "-wal", "-shm"):
            try:
                os.remove(_p + _suffix)
            except OSError:
                pass

    print("\n" + "=" * 74)
    print(f"自测结束： PASS={_PASS}  FAIL={_FAIL}")
    print("=" * 74)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())