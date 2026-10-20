# -*- coding: utf-8 -*-
"""``services/crawl/urls.py`` 单测：URL 规范化 / 内容哈希 / SimHash。"""
from __future__ import annotations

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.crawl.urls import (  # noqa: E402
    canonicalize_url,
    content_hash,
    hamming_distance,
    is_near_duplicate,
    simhash64,
)


# --------------------------------------------------------------------------- #
# canonicalize_url
# --------------------------------------------------------------------------- #
def test_same_page_with_different_utm_shares_canonical():
    base = "https://yz.example.edu.cn/2025/sszs/jzsh.html"
    a = canonicalize_url(base + "?utm_source=wechat&utm_campaign=gzh&id=12")
    b = canonicalize_url(base + "?id=12")
    c = canonicalize_url(base + "?id=12&utm_source=other")
    assert a == b == c
    assert "utm_" not in a


def test_tracking_params_are_stripped():
    url = "https://yz.example.edu.cn/news/1.html?from=groupmessage&spm=a1z10.5&_t=1735&timestamp=1735&id=7"
    canonical = canonicalize_url(url)
    assert "from=" not in canonical
    assert "spm=" not in canonical
    assert "_t=" not in canonical
    assert "timestamp=" not in canonical
    assert "id=7" in canonical


def test_query_params_are_sorted():
    a = canonicalize_url("https://example.edu.cn/x?b=2&a=1&c=3")
    b = canonicalize_url("https://example.edu.cn/x?c=3&a=1&b=2")
    assert a == b == "https://example.edu.cn/x?a=1&b=2&c=3"


def test_host_lowercased_and_trailing_slash_removed():
    assert canonicalize_url("https://YZ.Example.EDU.CN/News/") == "https://yz.example.edu.cn/News"
    assert canonicalize_url("https://example.edu.cn/") == "https://example.edu.cn/"
    assert canonicalize_url("https://example.edu.cn") == "https://example.edu.cn/"


def test_protocol_relative_url_becomes_https():
    assert canonicalize_url("//example.edu.cn/a/b") == "https://example.edu.cn/a/b"


def test_fragment_dropped_and_default_port_removed():
    assert canonicalize_url("https://example.edu.cn:443/a#part") == "https://example.edu.cn/a"
    assert canonicalize_url("http://example.edu.cn:80/a") == "http://example.edu.cn/a"


def test_empty_url_returns_empty_string():
    assert canonicalize_url("") == ""
    assert canonicalize_url(None) == ""


# --------------------------------------------------------------------------- #
# content_hash
# --------------------------------------------------------------------------- #
def test_content_hash_ignores_whitespace_differences():
    a = content_hash("2025年  复试分数线\n\n公布")
    b = content_hash("2025年 复试分数线 公布")
    assert a == b
    assert len(a) == 64


def test_content_hash_differs_for_different_text():
    assert content_hash("招生简章") != content_hash("复试细则")


# --------------------------------------------------------------------------- #
# simhash
# --------------------------------------------------------------------------- #
def test_simhash_is_16_hex_and_stable():
    h = simhash64("2025年硕士研究生招生复试分数线")
    assert len(h) == 16
    int(h, 16)
    assert h == simhash64("2025年硕士研究生招生复试分数线")


def test_identical_text_has_zero_distance():
    a = simhash64("2025年硕士研究生招生复试分数线")
    b = simhash64("2025年硕士研究生招生复试分数线")
    assert hamming_distance(a, b) == 0
    assert is_near_duplicate(a, b)


def test_unrelated_notices_are_far_apart():
    a = simhash64("清华大学2025年硕士研究生招生复试分数线通知")
    b = simhash64("关于开展学生公寓空调维修的通知")
    distance = hamming_distance(a, b)
    assert distance > 10, f"不相关公告的 simhash 距离应显著大于阈值，实际 {distance}"


def test_same_template_different_year_is_closer_than_unrelated():
    """同模板不同年份：距离明显小于无关公告（实测 5 vs 28）。

    判重阈值 3 比这个更严——同模板不同年份默认**不**判重，
    只有正文几乎一致（换年份动了几十字）时才会落到 ≤3。
    """
    a = simhash64("XX大学2025年硕士研究生招生简章：报考条件与录取办法说明")
    b = simhash64("XX大学2026年硕士研究生招生简章：报考条件与录取办法说明")
    c = simhash64("关于开展学生公寓空调维修的通知")
    assert hamming_distance(a, b) <= 8
    assert hamming_distance(a, b) < hamming_distance(a, c)


def test_hamming_distance_handles_invalid_input():
    assert hamming_distance("zzz", "0000000000000000") == 64
