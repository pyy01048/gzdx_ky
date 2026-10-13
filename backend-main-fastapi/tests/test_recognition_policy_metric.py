"""检索口径一致性测试：precision 分母必须与 recall 的放行条件同源。

背景（实测）：`recognition_policy_eval.py` 的历史 P2「第二志愿放行」臂只放宽了
recall 判定，precision 仍按 top-1 组池，于是报表显示零精度代价（0.883→0.883）。
生产检索过滤是 `subject = S OR alt_subject = S`，alt 命中的块同样进池 —— 按这个
口径实测 precision 0.862→0.667、F1 −10.6pt。本测试锁死修正后的口径，防止旧数字
被重新用来立项。纯函数测试，不连库、不跑 bge。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.recognition_policy_eval import SCOPES, score  # noqa: E402

A, B = SCOPES[0], SCOPES[1]


def feat(gold, sub, alt=""):
    return {"gold": gold, "sub": sub, "alt": alt, "conf": 0.8, "junk": "",
            "pua_share": 0.0, "top_sim": 0.5}


def test_baseline_top1_only():
    fs = [feat(A, A), feat(A, B)]          # 一块判对、一块判错，都在 A 池
    r = score(fs, {})
    assert r["exposures"] == 2
    assert r["prec"] == pytest.approx(0.5)
    assert r["rec"] == pytest.approx(0.5)


def test_alt_relaxation_moves_precision_too():
    """alt 放行时：recall 升，precision 必须同步降 —— 两侧口径同源。

    alt 带来的额外曝光大多是错的（真实数据里 42 次新增曝光只有 4 次判对），
    所以 precision 必然下降；旧口径把这部分曝光从分母里抹掉了。
    """
    fs = [
        feat(A, A),                          # A 池判对
        feat(A, B, alt=A),                   # top1 判错，alt 才对 → 新增一次正确曝光
        feat(B, B, alt=A),                   # top1 判对，alt 让它在 A 池变成污染
        feat("其他", A, alt=B),               # 域外块，两个池都被污染
    ]
    strict = score(fs, {})
    relaxed = score(fs, {"use_alt": True})
    assert relaxed["rec"] > strict["rec"]
    assert relaxed["prec"] < strict["prec"], "放宽放行却没放宽分母 = 旧 bug 复现"
    assert relaxed["exposures"] > strict["exposures"]
    assert relaxed["pollute"] >= strict["pollute"]


def test_double_pool_counts_two_exposures():
    """一块同时进两个学科池 = 两次曝光，不能只算一次。"""
    fs = [feat(A, A, alt=B)]
    r = score(fs, {"use_alt": True})
    assert r["exposures"] == 2
    assert r["prec"] == pytest.approx(0.5)      # 另一池里它是污染


def test_alt_equal_to_top1_does_not_duplicate():
    fs = [feat(A, A, alt=A)]
    assert score(fs, {"use_alt": True})["exposures"] == 1


def test_out_of_domain_gold_never_counts_correct():
    fs = [feat("其他", "其他")]
    r = score(fs, {})
    assert r["exposures"] == 0 and r["prec"] == 0.0
    assert r["rec"] == 0.0 and r["pollute"] == 0.0


def test_abstention_removes_exposure():
    """弃权块被 stamp 成「其他」后既不进池也不该被 alt 捞回来。"""
    def junk_all(f):
        return True

    fs = [feat(A, A, alt=B)]
    r = score(fs, {"junk": junk_all, "use_alt": True})
    assert r["exposures"] == 0
