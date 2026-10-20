# -*- coding: utf-8 -*-
"""URL 规范化与内容指纹——采集栈的"同一性"判定基座。

三件套
------
``canonicalize_url``
    把"同一个页面的不同链接形态"折成一条：去 tracking 参数、参数排序、
    小写 host、去尾斜杠。用于唯一键 ``(school_id, canonical_url)``。
``content_hash``
    正文空白归一后的 SHA-256。用于"内容完全一致"的判重。
``simhash64`` / ``hamming_distance``
    近似判重：同模板不同年份的公告（SimHash 距离 ≤ 3 视为同一篇）。

SimHash 说明
------------
中文按 **2-gram** 切词（"复试分数线" → "复试/试分/分数/线"），
英文与数字按整词切分；每个词用 blake2b 取 64 位指纹，按位加权累加，
取符号位得到 64 位 simhash，输出 16 位小写 hex。
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "canonicalize_url",
    "content_hash",
    "simhash64",
    "hamming_distance",
    "is_near_duplicate",
    "TRACKING_PARAM_EXACT",
    "TRACKING_PARAM_PREFIX",
]

#: 精确命中的 tracking 参数（全部小写比较）
TRACKING_PARAM_EXACT = frozenset({"from", "spm", "_t", "timestamp"})

#: 前缀命中的 tracking 参数
TRACKING_PARAM_PREFIX = ("utm_",)

_WS_RE = re.compile(r"\s+")

#: 中英混合切词：先切中文连续段，再切英文/数字整词
_TOKEN_RE = re.compile(r"[一-鿿]+|[a-z0-9]+")

#: 中文按 2-gram；单字成词时保留单字
_CJK_RANGE = ("一", "鿿")


def _is_tracking(key: str) -> bool:
    low = key.lower()
    if low in TRACKING_PARAM_EXACT:
        return True
    return any(low.startswith(p) for p in TRACKING_PARAM_PREFIX)


def canonicalize_url(url: str) -> str:
    """把 URL 归一为可比较的规范形态。

    规则（顺序固定，便于复算）：

    1. 协议相对 ``//host/path`` 补 ``https:``；
    2. scheme / host 小写，去掉默认端口（http:80 / https:443）；
    3. 去掉 fragment；
    4. query 去掉 tracking 参数（``utm_*`` / ``from`` / ``spm`` / ``_t`` / ``timestamp``），
       其余参数按 (key, value) 排序后重新编码——等价 URL 因此落到同一形态；
    5. path 去掉尾部斜杠，根路径保留为 ``/``。

    >>> canonicalize_url("https://Example.edu.cn/News/?utm_source=wx&id=3&b=2")
    'https://example.edu.cn/News?b=2&id=3'
    """
    if not url:
        return ""
    raw = str(url).strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw

    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()

    # --- host / port -------------------------------------------------------
    netloc = parts.netloc
    userinfo = ""
    if "@" in netloc:
        userinfo, netloc = netloc.rsplit("@", 1)
        userinfo += "@"

    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:  # 非法端口，按无端口处理
        port = None
    if ":" in host:  # IPv6
        host = f"[{host}]"
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    netloc = userinfo + host

    # --- path --------------------------------------------------------------
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    # --- query -------------------------------------------------------------
    query = ""
    if parts.query:
        pairs = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _is_tracking(k)
        ]
        if pairs:
            pairs.sort(key=lambda kv: (kv[0], kv[1]))
            query = urlencode(pairs)

    if not scheme and not netloc:
        # 相对地址：没有 host 就没有可比较的绝对形态，只做 path/query 归一
        return urlunsplit(("", "", path, query, ""))

    return urlunsplit((scheme, netloc, path, query, ""))


def content_hash(text: str) -> str:
    """正文内容哈希（空白归一后的 SHA-256 hex）。

    归一规则：所有连续空白折成单个空格、首尾去空白。用于"同一份正文"的精确判重。
    """
    if not text:
        text = ""
    normalized = _WS_RE.sub(" ", str(text)).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _tokenize(text: str) -> list[str]:
    """中文 2-gram + 英文/数字整词。"""
    tokens: list[str] = []
    for chunk in _TOKEN_RE.findall(text or ""):
        if chunk[0] >= _CJK_RANGE[0] and chunk[0] <= _CJK_RANGE[1]:
            if len(chunk) == 1:
                tokens.append(chunk)
            else:
                tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
        else:
            tokens.append(chunk)
    return tokens


def simhash64(text: str) -> str:
    """文本的 64 位 SimHash（16 位小写 hex）。

    >>> len(simhash64("2025年硕士研究生招生复试分数线"))
    16
    """
    tokens = _tokenize(text or "")
    if not tokens:
        return "0" * 16

    weights = [0.0] * 64
    for token, weight in _token_weights(tokens).items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "big")
        for bit in range(64):
            if (h >> bit) & 1:
                weights[bit] += weight
            else:
                weights[bit] -= weight

    value = 0
    for bit in range(64):
        if weights[bit] > 0:
            value |= 1 << bit
    return f"{value:016x}"


def _token_weights(tokens: list[str]) -> dict[str, float]:
    """词频权重（上限 5，防止长文里单个高频词主导）。"""
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return {token: min(count, 5) for token, count in counts.items()}


def hamming_distance(a: str, b: str) -> int:
    """两个 simhash（16 位 hex）之间的汉明距离。

    非法输入按"最不像"处理，返回 64。
    """
    try:
        va = int(str(a), 16)
        vb = int(str(b), 16)
    except (TypeError, ValueError):
        return 64
    return (va ^ vb).bit_count()


def is_near_duplicate(a: str, b: str, threshold: int = 3) -> bool:
    """SimHash 距离 ≤ ``threshold`` 视为同一篇公告。"""
    return hamming_distance(a, b) <= threshold
