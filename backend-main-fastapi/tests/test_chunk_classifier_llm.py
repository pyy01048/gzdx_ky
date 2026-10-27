"""路3（LLM 兜底打标）回归测试。

背景（实测教训）：`L3_TYPES` 的赋值曾被并进上一行的 ``#:`` 注释里，于是
``llm_classify()`` 在**每次成功拿到模型回复后**抛 NameError，整轮回填死在
``classify_document`` 的 commit 之前。全库 61091 块里 ``classify_source='llm'``
恒为 0，直到本次实测才暴露。所以这里的用例重点不是"模型准不准"，而是
"路3 会不会静默失效"：符号在不在、异常会不会外泄、上限按不按发起次数封顶。

隔离：全部走 conftest 的临时库，且 monkeypatch 掉 ``_chat_local``，不发真实网络请求。
"""
from __future__ import annotations

import pytest

from services import chunk_classifier as cc


# --------------------------------------------------------------------------- #
# 1. 候选集符号
# --------------------------------------------------------------------------- #
def test_l3_types_defined_and_covers_rule_labels():
    """L3_TYPES 必须是真实存在的常量，且覆盖规则速判能产出的全部标签。"""
    assert isinstance(cc.L3_TYPES, tuple) and cc.L3_TYPES
    rule_labels = {label for label, _ in cc._L3_RULES} | {"其他"}
    assert rule_labels <= set(cc.L3_TYPES), f"规则标签未被候选集覆盖: {rule_labels - set(cc.L3_TYPES)}"
    # 提示词里的候选串必须与常量一致，否则模型只会输出被丢弃的值
    for label in cc.L3_TYPES:
        assert label in cc._LLM_PROMPT


# --------------------------------------------------------------------------- #
# 2. 输出解析
# --------------------------------------------------------------------------- #
def test_parse_llm_output_strict_json():
    raw = '{"l1_subject": "数学", "l2_chapter": "极限", "l3_content_type": "定义", "confidence": 0.8, "reason": "ok"}'
    out = cc._parse_llm_output(raw)
    assert out["l1_subject"] == "数学"
    assert out["l3_content_type"] == "定义"
    assert float(out["confidence"]) == 0.8


def test_parse_llm_output_recovers_from_unescaped_quote_in_reason():
    """实测丢弃样本：reason 里带裸引号 → json.loads 失败，结构化字段仍要救回来。"""
    raw = (
        '{\r\n  "l1_subject": "生理学",\r\n  "l2_chapter": "",\r\n'
        '  "l3_content_type": "例题",\r\n  "confidence": 0,\r\n'
        '  "reason": "文本属于"生理学"范畴'
    )
    out = cc._parse_llm_output(raw)
    assert out is not None, "宽松解析未生效，实测 20% 的路3 产出会被白扔"
    assert out["l1_subject"] == "生理学"
    assert out["l3_content_type"] == "例题"


@pytest.mark.parametrize("raw", ["", "   ", "我不知道", "l1_subject:生理学|病理解析"])
def test_parse_llm_output_returns_none_on_unparsable(raw):
    assert cc._parse_llm_output(raw) is None


def test_llm_classify_never_raises(monkeypatch):
    """契约：任何异常/垃圾输出 → None，绝不把整篇回填带崩。"""
    def _boom(messages, **kw):  # noqa: ARG001
        raise RuntimeError("model runner has unexpectedly stopped")

    monkeypatch.setattr(cc, "_chat_local", _boom)
    assert cc.llm_classify("a.pdf", "洛必达法则的定义：……") is None

    monkeypatch.setattr(cc, "_chat_local", lambda messages, **kw: "不是 JSON")
    assert cc.llm_classify("a.pdf", "洛必达法则的定义：……") is None

    # 空文本连调用都不该发生
    calls = []
    monkeypatch.setattr(cc, "_chat_local", lambda messages, **kw: calls.append(1) or "{}")
    assert cc.llm_classify("a.pdf", "   ") is None
    assert calls == []


def test_llm_classify_drops_subject_outside_candidates(monkeypatch):
    """非法学科（候选集外）→ 空串，绝不落库；合法值原样保留并裁剪越界 L3。"""
    raw = ('{"l1_subject": "中医学", "l2_chapter": "藏象", '
           '"l3_content_type": "不存在的类型", "confidence": 1.7, "reason": "x"}')
    monkeypatch.setattr(cc, "_chat_local", lambda messages, **kw: raw)
    out = cc.llm_classify("a.pdf", "肺属金……")
    assert out is not None
    assert out["l1_subject"] == ""            # 候选集外科目一律归零
    assert out["l3_content_type"] == ""       # 非枚举 L3 丢弃
    assert out["confidence"] == 1.0           # 越界裁剪


# --------------------------------------------------------------------------- #
# 3. 成本闸门：按发起次数封顶
# --------------------------------------------------------------------------- #
def test_llm_cap_counts_attempts_not_success(db_schema, monkeypatch):  # noqa: ARG001
    """模型全失败时也必须停在 LLM_MAX_PER_DOC，否则每篇低置信文档无限重试。"""
    from models import Document, KnowledgeChunk
    from database import SessionLocal

    db = SessionLocal()
    try:
        doc = Document(file_name="qa-l3-cap.pdf", file_path="qa-l3-cap.pdf",
                       file_type="pdf", size=1, subject="",
                       index_status="indexed", parse_progress=1.0)
        db.add(doc)
        db.commit()
        for i in range(cc.LLM_MAX_PER_DOC + 15):
            db.add(KnowledgeChunk(document_id=doc.id, doc_name=doc.file_name,
                                  chunk_id=i, text=f"第{i}段 完全没有关键词线索 也没有质心相似度 zzqq{i}"))
        db.commit()

        # 关掉路1/路2，保证每个块都是低置信 → 全部想进路3
        monkeypatch.setattr(cc, "load_prototypes", lambda _db: {})
        monkeypatch.setattr(cc, "encode_texts", lambda texts: None)
        monkeypatch.setattr(cc, "keyword_scores", lambda fn, t: ("", 0.0))

        attempts = []
        monkeypatch.setattr(cc, "llm_classify",
                            lambda fn, t, n=0: attempts.append(n) or None)

        r = cc.classify_document(db, doc.id, use_llm=True, only_unlabeled=False)
        assert r["ok"] is True
        assert len(attempts) == cc.LLM_MAX_PER_DOC, \
            f"路3 未按发起次数封顶：实际 {len(attempts)} 次"
        assert r["llm_calls"] == 0
        assert r["llm_failed"] == cc.LLM_MAX_PER_DOC

        labeled = (db.query(KnowledgeChunk)
                   .filter(KnowledgeChunk.document_id == doc.id)
                   .filter(KnowledgeChunk.l3_content_type.isnot(None))
                   .count())
        assert labeled == cc.LLM_MAX_PER_DOC + 15, "失败降级后仍应完成两路打标并落库"
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).delete()
        db.delete(doc)
        db.commit()
    finally:
        db.close()
