# -*- coding: utf-8 -*-
"""``services.quiz_content_gate`` 第 7 层（同题干答案冲突检测）单测。

覆盖 team-lead 指定的 4 个用例：
  1. 同题干同答案 → 通过
  2. 同题干不同答案 → 拒绝
  3. 题干归一化后相同（OCR 乱码 / 填空位 / 全半角差异）→ 仍按同题干判定
  4. 短题干长度不足阈值 → 跳过检测（放行）

另附签名相关与边界用例。用法::

    python -m pytest tests/test_quiz_content_gate_conflict.py -v
    python tests/test_quiz_content_gate_conflict.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.quiz_content_gate import (  # noqa: E402
    MIN_CONFLICT_STEM_LEN,
    admit,
    build_stem_answer_index,
    detect_answer_conflict,
    normalize_dedup,
    question_signature,
)

# 一道合法的填空题题干（含"？"，能通过既有第 3 层"像不像题"判定，
# 且归一化后长度足够超过 MIN_CONFLICT_STEM_LEN）
STEM = "放大电路中，为了稳定静态工作点应引入哪种类型的反馈电路？"
STEM_WITH_BLANK = "放大电路中，为了稳定静态工作点应引入______负反馈电路？"


def _idx(*pairs):
    return build_stem_answer_index(pairs)


# --------------------------------------------------------------------------- #
# 用例 1：同题干同答案 → 通过
# --------------------------------------------------------------------------- #
def test_same_stem_same_answer_passes():
    idx = _idx((STEM, "电压"))
    ok, reason = admit(STEM, answer="电压", stem_answer_index=idx)
    assert ok, reason
    assert reason == "admitted"


def test_detect_same_stem_same_answer_no_conflict():
    idx = _idx((STEM, "电压"))
    conflict, detail = detect_answer_conflict(STEM, "电压", idx)
    assert not conflict
    assert detail == ""


# --------------------------------------------------------------------------- #
# 用例 2：同题干不同答案 → 拒绝
# --------------------------------------------------------------------------- #
def test_same_stem_different_answer_rejected():
    idx = _idx((STEM, "电压；电流"))
    ok, reason = admit(STEM, answer="电流，电压", stem_answer_index=idx)
    assert not ok
    assert reason == "reject:同题干答案冲突"


def test_detect_same_stem_different_answer_conflict():
    idx = _idx((STEM, "电压；电流"))
    conflict, detail = detect_answer_conflict(STEM, "电流，电压", idx)
    assert conflict
    assert "同题干已有答案" in detail


def test_conflict_absent_when_no_index():
    """未传索引时不启用本层（向后兼容）。"""
    ok, reason = admit(STEM, answer="完全不同的答案")
    assert ok, reason


def test_conflict_absent_when_index_empty():
    ok, reason = admit(STEM, answer="随便", stem_answer_index=_idx())
    assert ok, reason


def test_conflict_absent_when_new_answer_empty():
    """空答案不与任何答案冲突（存量大量无答案题）。"""
    idx = _idx((STEM, "电压"))
    conflict, _ = detect_answer_conflict(STEM, None, idx)
    assert not conflict
    conflict2, _ = detect_answer_conflict(STEM, "   ", idx)
    assert not conflict2


# --------------------------------------------------------------------------- #
# 用例 3：题干归一化后相同 → 仍按同题干判定
# --------------------------------------------------------------------------- #
def test_stem_normalization_detects_conflict_with_ocr_junk():
    """OCR 乱码 + 填空位差异，归一化后仍是同题干 → 应拒绝。"""
    dirty = STEM_WITH_BLANK.replace("______", "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd")
    assert dirty != STEM_WITH_BLANK
    idx = _idx((STEM_WITH_BLANK, "电压"))
    conflict, detail = detect_answer_conflict(dirty, "电流", idx)
    assert conflict, detail


def test_stem_normalization_detects_conflict_with_blank_variants():
    """`____` / `＿＿` / `（ ）` 填空位统一后应视为同题干。"""
    idx = _idx((STEM_WITH_BLANK, "电压"))
    for variant in ("放大电路中，为了稳定静态工作点应引入＿＿＿＿负反馈电路？",
                    "放大电路中，为了稳定静态工作点应引入______负反馈电路？",
                    "放大电路中，为了稳定静态工作点应引入﹏﹏负反馈电路？"):
        conflict, _ = detect_answer_conflict(variant, "电流", idx)
        assert conflict, variant


def test_stem_normalization_detects_conflict_case_insensitive():
    idx = _idx((STEM, "voltage"))
    conflict, _ = detect_answer_conflict(STEM, "VOLTAGE", idx)
    # 答案归一化后小写，视为同答案 → 不冲突
    assert not conflict


def test_normalize_dedup_strips_ocr_and_blank():
    a = normalize_dedup("题干 ______ 尾部\ufffd")
    b = normalize_dedup("题干＿＿尾部")
    assert a == b
    assert "\ufffd" not in a


# --------------------------------------------------------------------------- #
# 用例 4：短题干长度不足阈值 → 跳过检测
# --------------------------------------------------------------------------- #
def test_short_stem_skips_conflict_detection():
    short = "A与B？"  # 归一化后长度 < MIN_CONFLICT_STEM_LEN
    assert len(normalize_dedup(short)) < MIN_CONFLICT_STEM_LEN
    idx = _idx((short, "甲"))
    conflict, detail = detect_answer_conflict(short, "乙", idx)
    assert not conflict
    assert detail == ""


def test_short_stem_not_indexed():
    """短题干不会被收进索引（等于永远不参与冲突判定）。"""
    short = "A与B？"
    idx = _idx((short, "甲"))
    assert idx == {}


def test_empty_answer_rows_not_indexed():
    idx = _idx((STEM, None), (STEM, "  "))
    assert STEM.lower().replace(" ", "") not in idx or not idx.get(
        normalize_dedup(STEM)
    )
    conflict, _ = detect_answer_conflict(STEM, "任意", idx)
    assert not conflict


def test_oversized_stem_not_indexed():
    long_stem = "填" * (MIN_CONFLICT_STEM_LEN + 50)  # > MAX_INDEX_STEM_LEN(400)? 否
    # 构造超过 400 字的题干
    over = "测" * 500
    idx = _idx((over, "答案"))
    assert normalize_dedup(over) not in idx
    conflict, _ = detect_answer_conflict(over, "别的", idx)
    assert not conflict
    assert len(normalize_dedup(long_stem)) < 500


# --------------------------------------------------------------------------- #
# 签名相关：判重签名必须纳入 answer
# --------------------------------------------------------------------------- #
def test_signature_depends_on_answer():
    s1 = question_signature(STEM, "电压")
    s2 = question_signature(STEM, "电流")
    assert s1 != s2, "同题干不同答案必须得到不同签名"


def test_signature_same_for_same_answer():
    assert question_signature(STEM, "电压") == question_signature(STEM, "电压")


def test_signature_answer_none_vs_empty_same():
    assert question_signature(STEM, None) == question_signature(STEM, "")


def test_signature_answer_none_differs_from_value():
    assert question_signature(STEM, None) != question_signature(STEM, "x")


def test_signature_strips_ocr_from_content():
    assert question_signature("题干\ufffd", "a") == question_signature("题干", "a")


def test_signature_length_is_16():
    assert len(question_signature(STEM, "a")) == 16


# --------------------------------------------------------------------------- #
# 与既有 6 层联动：不是题的候选应先被前层拦下，不报冲突
# --------------------------------------------------------------------------- #
def test_non_question_rejected_before_conflict_check():
    idx = _idx((STEM, "电压"))
    ok, reason = admit("……", answer="电流", stem_answer_index=idx)
    assert not ok
    assert reason != "reject:同题干答案冲突"
    assert reason.startswith("reject:")


def test_gate_off_bypasses_conflict(monkeypatch=None):
    os.environ["QUIZ_CONTENT_GATE"] = "0"
    try:
        idx = _idx((STEM, "电压"))
        ok, _ = admit(STEM, answer="电流", stem_answer_index=idx)
        assert ok
    finally:
        os.environ.pop("QUIZ_CONTENT_GATE", None)


# --------------------------------------------------------------------------- #
# 极简 runner（无 pytest 时）
# --------------------------------------------------------------------------- #
def _run_all() -> int:
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append((name, repr(e)))
            print(f"  FAIL  {name}: {e!r}")
        except Exception as e:  # noqa: BLE001
            failed.append((name, repr(e)))
            print(f"  ERROR {name}: {e!r}")
    print(f"\n{len(fns) - len(failed)}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
