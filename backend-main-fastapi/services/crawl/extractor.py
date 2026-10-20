# -*- coding: utf-8 -*-
"""公告正文抽取：trafilatura 主 → readability 兜底 → 内置简易抽取兜底。

三级降级链
----------
1. ``trafilatura``：精度优先（``favor_precision=True``），附带元数据（标题/日期）；
2. ``readability-lxml``：trafilatura 抽不出或抽得太短时接管；
3. 内置抽取：去 ``script/style/nav/footer/header/aside/form`` 后按 ``<p>`` 密度
   找正文容器，保证**任何情况下都不抛 ImportError**。

附件
----
从原 HTML 的 ``<a href>`` 里筛 ``.pdf/.doc/.docx/.xls/.xlsx/.zip``，
相对地址用 :func:`urllib.parse.urljoin` 拼成绝对地址。

日期
----
优先 meta（``article:published_time`` / ``publishdate`` / ``pubdate`` / ``DC.date`` /
``og:published_time`` / ``itemprop=datePublished``），其次正文里的
``2025-03-12`` / ``2025年3月12日`` 形态。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import urljoin, urlsplit

__all__ = ["Extracted", "extract", "available_engines"]

try:
    import lxml.html as lhtml

    HAVE_LXML = True
except Exception:  # pragma: no cover
    lhtml = None  # type: ignore
    HAVE_LXML = False

try:
    import trafilatura

    HAVE_TRAFILATURA = True
except Exception:  # pragma: no cover
    trafilatura = None  # type: ignore
    HAVE_TRAFILATURA = False

try:
    from readability import Document as _ReadabilityDocument

    HAVE_READABILITY = True
except Exception:  # pragma: no cover
    _ReadabilityDocument = None  # type: ignore
    HAVE_READABILITY = False


_ATTACHMENT_EXT_RE = re.compile(r"\.(pdf|docx?|xlsx?|zip)$", re.I)

_DATE_PATTERNS = (
    re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})"),
    re.compile(r"(20\d{2})[-/年.](\d{1,2})月?$"),
)

_META_DATE_KEYS = (
    "article:published_time",
    "article:published",
    "og:published_time",
    "publishdate",
    "pubdate",
    "publish_time",
    "publishtime",
    "date",
    "dc.date",
    "sailthru.date",
    "weibo:article:create_at",
)

_WS_RE = re.compile(r"[ \t　]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


@dataclass
class Extracted:
    """一次正文抽取的产物。"""

    title: str
    text: str
    publish_date: Optional[date] = None
    attachments: List[dict] = field(default_factory=list)
    engine: str = "none"

    @property
    def char_count(self) -> int:
        return len(self.text or "")


def available_engines() -> List[str]:
    """当前环境里可用的抽取引擎（便于诊断）。"""
    engines = []
    if HAVE_TRAFILATURA:
        engines.append("trafilatura")
    if HAVE_READABILITY:
        engines.append("readability")
    engines.append("builtin")
    return engines


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def _parse_date(value) -> Optional[date]:
    """把各种日期写法解析成 :class:`datetime.date`。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        groups = m.groups()
        try:
            year = int(groups[0])
            month = int(groups[1])
            day = int(groups[2]) if len(groups) > 2 and groups[2] else 1
            return date(year, month, day)
        except (TypeError, ValueError):
            continue
    return None


def _meta_publish_date(doc) -> Optional[date]:
    """从 ``<meta>`` 里取发布日期。"""
    if doc is None:
        return None
    for xpath in (
        "//meta[@property='article:published_time']/@content",
        "//meta[@property='og:published_time']/@content",
        "//meta[@itemprop='datePublished']/@content",
        "//meta[@name='publishdate']/@content",
        "//meta[@name='pubdate']/@content",
        "//meta[@name='PubDate']/@content",
        "//meta[@name='publish_time']/@content",
        "//meta[@name='publishtime']/@content",
        "//meta[@name='date']/@content",
        "//meta[@name='DC.date']/@content",
        "//meta[@name='sailthru.date']/@content",
        "//meta[@name='weibo:article:create_at']/@content",
    ):
        try:
            values = doc.xpath(xpath)
        except Exception:  # pragma: no cover
            continue
        for raw in values:
            parsed = _parse_date(raw)
            if parsed:
                return parsed
    return None


def _text_publish_date(text: str) -> Optional[date]:
    """正文里的日期（``2025-03-12`` / ``2025年3月12日``）。"""
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            parsed = _parse_date(m.group(0))
            if parsed:
                return parsed
    return None


def _collect_attachments(doc, url: str) -> List[dict]:
    """挑出文档类附件链接。"""
    if doc is None:
        return []
    attachments: List[dict] = []
    seen = set()
    try:
        hrefs = doc.xpath("//a[@href]/@href")
    except Exception:  # pragma: no cover
        return []
    for href in hrefs:
        href = (href or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
            continue
        path = urlsplit(href).path
        if not _ATTACHMENT_EXT_RE.search(path):
            continue
        absolute = urljoin(url, href) if url else href
        if absolute in seen:
            continue
        seen.add(absolute)
        ext_m = _ATTACHMENT_EXT_RE.search(path)
        ext = (ext_m.group(1).lower() if ext_m else "").lower()
        filename = path.rsplit("/", 1)[-1] if path else ""
        attachments.append(
            {
                "url": absolute,
                "filename": filename or ext,
                "ext": ext,
            }
        )
    return attachments


def _trafilatura_extract(html: str, url: str):
    if not HAVE_TRAFILATURA:
        return None
    try:
        text = trafilatura.extract(
            html,
            url=url or None,
            include_comments=False,
            favor_precision=True,
            include_tables=True,
        )
    except Exception:
        return None
    if not text or len(text.strip()) < 40:
        return None
    title = ""
    publish_date = None
    try:
        meta = trafilatura.extract_metadata(html, default_url=url or None)
        title = (getattr(meta, "title", "") or "").strip()
        publish_date = _parse_date(getattr(meta, "date", None))
    except Exception:
        pass
    return {"text": text, "title": title, "publish_date": publish_date, "engine": "trafilatura"}


def _readability_extract(html: str, url: str):
    if not HAVE_READABILITY:
        return None
    try:
        doc = _ReadabilityDocument(html)
        summary_html = doc.summary(html_partial=True)
        title = (doc.short_title() or "").strip()
    except Exception:
        return None
    if not HAVE_LXML:
        text = re.sub(r"<[^>]+>", " ", summary_html or "")
    else:
        try:
            node = lhtml.fromstring(summary_html or "<div></div>")
            text = node.text_content()
        except Exception:
            text = re.sub(r"<[^>]+>", " ", summary_html or "")
    if not text or len(text.strip()) < 40:
        return None
    return {"text": text, "title": title, "publish_date": None, "engine": "readability"}


def _builtin_extract(html: str, url: str):
    """内置简易抽取：去噪声标签后按 ``<p>`` 文本密度挑正文容器。"""
    if not HAVE_LXML:
        text = re.sub(r"<[^>]+>", " ", html or "")
        return {
            "text": text,
            "title": "",
            "publish_date": None,
            "engine": "builtin",
        }
    try:
        doc = lhtml.fromstring(html or "<html><body></body></html>")
    except Exception:
        return {"text": "", "title": "", "publish_date": None, "engine": "builtin"}

    for bad in doc.xpath("//script|//style|//nav|//footer|//header|//aside|//form|//noscript"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)

    title = ""
    for xpath in ("//h1//text()", "//title//text()"):
        try:
            values = [t.strip() for t in doc.xpath(xpath) if isinstance(t, str) and t.strip()]
        except Exception:  # pragma: no cover
            values = []
        if values:
            title = values[0]
            break

    best_node = None
    best_score = 0
    try:
        candidates = doc.xpath("//article|//main|//div|//section")
    except Exception:  # pragma: no cover
        candidates = []
    for cand in candidates:
        try:
            paras = cand.xpath(".//p")
        except Exception:  # pragma: no cover
            continue
        score = 0
        for p in paras:
            score += len("".join(p.itertext()).strip())
        if score > best_score:
            best_node, best_score = cand, score

    if best_node is None:
        best_node = doc

    lines: List[str] = []
    try:
        blocks = best_node.xpath(".//p|.//li|.//h1|.//h2|.//h3|.//td")
    except Exception:  # pragma: no cover
        blocks = []
    for block in blocks:
        piece = "".join(block.itertext()).strip()
        if piece:
            lines.append(piece)
    text = "\n".join(lines)
    if not text.strip():
        text = "".join(best_node.itertext())
    return {"text": text, "title": title, "publish_date": None, "engine": "builtin"}


def extract(html: str, url: str = "") -> Extracted:
    """从 HTML 抽取正文、标题、发布日期、附件。

    任何一级引擎失败都会自动降级，全部不可用时返回空结果（不抛异常）。
    """
    html = html or ""
    doc = None
    if HAVE_LXML and html:
        try:
            doc = lhtml.fromstring(html)
        except Exception:
            doc = None

    payload = None
    for engine in (_trafilatura_extract, _readability_extract, _builtin_extract):
        payload = engine(html, url)
        if payload and payload.get("text"):
            break
    if not payload:
        payload = {"text": "", "title": "", "publish_date": None, "engine": "none"}

    text = _normalize_text(payload.get("text") or "")
    title = (payload.get("title") or "").strip()

    # 标题优先级：页面 h1 > trafilatura 元数据标题 > og:title > <title>。
    # 高校 CMS 页面里 <title> 常带站点后缀（"…-湖南大学研究生院"），
    # 而 h1 才是公告本身的标题，所以优先取 h1。
    h1_title = ""
    if doc is not None:
        try:
            candidates = [t.strip() for t in doc.xpath("//h1//text()")
                          if isinstance(t, str) and t.strip()]
        except Exception:  # pragma: no cover
            candidates = []
        for cand in candidates:
            if 4 <= len(cand) <= 120:
                h1_title = cand
                break
    if h1_title:
        title = h1_title
    elif not title and doc is not None:
        try:
            og = doc.xpath("//meta[@property='og:title']/@content")
            if og and og[0].strip():
                title = og[0].strip()
        except Exception:  # pragma: no cover
            pass

    # 日期优先级：meta 声明 > 正文里的日期 > trafilatura 的模糊日期。
    # trafilatura 只识别出年份时会给出 ``1 月 1 日`` 这种占位日期，
    # 直接采信会把 "2025年3月12日" 之类的真日期覆盖掉，所以放最后。
    publish_date = _meta_publish_date(doc)
    if not publish_date:
        publish_date = _text_publish_date(text)
    if not publish_date:
        publish_date = payload.get("publish_date")

    attachments = _collect_attachments(doc, url)

    return Extracted(
        title=title,
        text=text,
        publish_date=publish_date,
        attachments=attachments,
        engine=payload.get("engine") or "none",
    )
