# -*- coding: utf-8 -*-
"""L2 相似告警层单测（``detect_stem_similarity_alert`` + 开关）。

team-lead 指定的 4 类用例：
  (a) 相似但不相同 → **不拒收**，只告警
  (b) 完全不同 → 不告警
  (c) L2 开关关闭 → 完全静默
  (d) 短题干 → 跳过

另附：精确同题干归 L1 不在 L2 告警、空答案不告警、``admit()`` 在 L2 开启时
仍返回 admitted（L2 绝不拒收，这是它与 L1 的根本区别）。

用法::
    python -m pytest tests/test_quiz_content_gate_l2.py -v
    python tests/test_quiz_content_gate_l2.py
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.quiz_content_gate import (  # noqa: E402
    MIN_CONFLICT_STEM_LEN,
    admit,
    build_stem_text_list,
    detect_stem_similarity_alert,
    gate_stats_snapshot,
    gate_reset_stats,
    normalize_dedup,
    stem_similarity_alert_enabled,
)

# 两条高度相似但不完全相同的题干（OCR 异体 + 措辞差异）
STEM_A = "负反馈对放大电路的性能有哪些影响？列举2种常见的负反馈类型。"
STEM_B = "负反馈对放⼤电路的性能有哪些影响？列举2种常⻅的负反馈类型！"
# 完全不同
STEM_C = "简述直流稳压电源的组成与工作原理，并说明各部分的作用。"


def _stems(*items: str) -> list[str]:
    return build_stem_text_list([(s, "x") for s in items])


# --------------------------------------------------------------------------- #
# (a) 相似但不相同 → 不拒收，只告警
# --------------------------------------------------------------------------- #
def test_similar_but_not_identical_alerts_but_never_rejects():
    alerted, detail = detect_stem_similarity_alert(STEM_A, "答案甲", _stems(STEM_B))
    assert alerted, "相似题干应产生告警"
    assert "相似题干告警" in detail
    assert "不拒收" in detail


def test_similar_case_admit_returns_admitted():
    """关键：L2 命中时 admit() 仍必须放行 —— 硬拒收就是批量误杀。"""
    stems = _stems(STEM_B)
    ok, reason = admit(STEM_A, answer="答案甲", section_type="简答", stem_text_list=stems)
    assert ok, reason
    assert reason == "admitted"


def test_similar_with_gate_on_counts_alert_stat():
    os.environ["QUIZ_STEM_SIMILARITY_ALERT"] = "1"
    try:
        gate_reset_stats()
        admit(STEM_A, answer="答案甲", section_type="简答",
              stem_text_list=_stems(STEM_B))
        assert gate_stats_snapshot().get("alert:stem_similarity", 0) >= 1
    finally:
        os.environ.pop("QUIZ_STEM_SIMILARITY_ALERT", None)


# --------------------------------------------------------------------------- #
# (b) 完全不同 → 不告警
# --------------------------------------------------------------------------- #
def test_completely_different_no_alert():
    alerted, detail = detect_stem_similarity_alert(STEM_A, "答案甲", _stems(STEM_C))
    assert not alerted, detail
    assert detail == ""


def test_no_stem_list_no_alert():
    alerted, _ = detect_stem_similarity_alert(STEM_A, "答案甲", None)
    assert not alerted
    alerted2, _ = detect_stem_similarity_alert(STEM_A, "答案甲", [])
    assert not alerted2


# --------------------------------------------------------------------------- #
# (c) 开关关闭 → 完全静默
# --------------------------------------------------------------------------- #
def test_l2_disabled_by_default():
    os.environ.pop("QUIZ_STEM_SIMILARITY_ALERT", None)
    assert stem_similarity_alert_enabled() is False


def test_l2_disabled_is_silent():
    os.environ["QUIZ_STEM_SIMILARITY_ALERT"] = "0"
    try:
        assert stem_similarity_alert_enabled() is False
        gate_reset_stats()
        ok, _ = admit(STEM_A, answer="答案甲", section_type="简答",
                      stem_text_list=_stems(STEM_B))
        assert ok
        # 开关关闭时不得产生任何 L2 计数
        assert "alert:stem_similarity" not in gate_stats_snapshot()
    finally:
        os.environ.pop("QUIZ_STEM_SIMILARITY_ALERT", None)


def test_l2_enabled_by_env():
    os.environ["QUIZ_STEM_SIMILARITY_ALERT"] = "1"
    try:
        assert stem_similarity_alert_enabled() is True
    finally:
        os.environ.pop("QUIZ_STEM_SIMILARITY_ALERT", None)


# --------------------------------------------------------------------------- #
# (d) 短题干 → 跳过
# --------------------------------------------------------------------------- #
def test_short_stem_skipped():
    short = "为什么？"
    assert len(normalize_dedup(short)) < MIN_CONFLICT_STEM_LEN
    alerted, detail = detect_stem_similarity_alert(short, "甲", _stems(short, short))
    assert not alerted
    assert detail == ""


def test_short_stem_not_in_list():
    short = "为什么？"
    assert _stems(short, short) == []


# --------------------------------------------------------------------------- #
# 边界
# --------------------------------------------------------------------------- #
def test_identical_stem_not_alerted_by_l2():
    """精确同题干归 L1（硬拒收），L2 不重复告警。"""
    alerted, _ = detect_stem_similarity_alert(STEM_A, "答案乙", _stems(STEM_A))
    assert not alerted


def test_empty_answer_no_alert():
    alerted, _ = detect_stem_similarity_alert(STEM_A, None, _stems(STEM_B))
    assert not alerted
    alerted2, _ = detect_stem_similarity_alert(STEM_A, "  ", _stems(STEM_B))
    assert not alerted2


def test_reuses_similarity_ratio_threshold():
    """阈值可调：调到 0.99 后原本命中的这对应不再告警。"""
    stems = _stems(STEM_B)
    assert detect_stem_similarity_alert(STEM_A, "甲", stems, threshold=0.86)[0]
    assert not detect_stem_similarity_alert(STEM_A, "甲", stems, threshold=0.999)[0]


def test_build_stem_text_list_keeps_non_dup():
    """L2 列表不应按题干去重（目的正是找相似而非相同）。"""
    out = build_stem_text_list([(STEM_A, "a"), (STEM_A, "b"), (STEM_B, "c")])
    assert len(out) == 3


def _run_all() -> int:
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append(name)
            print(f"  FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed.append(name)
            print(f"  ERROR {name}: {e!r}")
    print(f"\n{len(fns) - len(failed)}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    sys.exit(_run_all())
