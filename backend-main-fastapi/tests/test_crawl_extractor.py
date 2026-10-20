# -*- coding: utf-8 -*-
"""``services/crawl/extractor.py`` 单测：内嵌中文公告片段，不联网。"""
from __future__ import annotations

import os
import sys
from datetime import date

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.crawl import extractor as extractor_mod  # noqa: E402
from services.crawl.extractor import Extracted, available_engines, extract  # noqa: E402

NOTICE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>清华大学2025年硕士研究生招生复试分数线 - 研究生招生网</title>
  <meta property="article:published_time" content="2025-03-12 10:30:00">
</head>
<body>
  <nav>首页 | 学校概况 | 招生信息 | 联系我们</nav>
  <article>
    <h1>清华大学2025年硕士研究生招生复试分数线</h1>
    <p>根据教育部有关硕士研究生招生工作的要求，结合我校实际情况，现公布我校2025年硕士研究生招生复试分数线。</p>
    <p>第一部分为进入复试的基本分数线，第二部分为院系在基本线基础上确定的专业方向复试要求。</p>
    <p>考生可登录研究生招生网查询个人成绩，相关分数线说明详见附件。</p>
    <ul>
      <li><a href="/files/2025/fenshuxian.pdf">2025年复试分数线（PDF）</a></li>
      <li><a href="/files/2025/zhuanye.pdf">复试专业目录（PDF）</a></li>
      <li><a href="/files/2025/other.docx">复试说明（DOCX）</a></li>
      <li><a href="/files/2025/list.html">学院复试细则页面</a></li>
    </ul>
  </article>
  <footer>版权所有 清华大学研究生招生网</footer>
  <script>var _hmt = [];</script>
</body>
</html>
"""

PAGE_URL = "https://yz.example.edu.cn/2025/jzsh/fenshuxian.html"


def test_extract_title_date_text_and_attachments():
    result = extract(NOTICE_HTML, PAGE_URL)
    assert isinstance(result, Extracted)
    assert "复试分数线" in result.title
    assert result.publish_date == date(2025, 3, 12)
    assert len(result.text) > 80
    assert "教育部" in result.text
    assert "版权所有" not in result.text, "页脚噪声应被剔除"
    assert result.engine in available_engines()


def test_extract_attachments_are_absolute_and_filtered():
    result = extract(NOTICE_HTML, PAGE_URL)
    exts = sorted(a["ext"] for a in result.attachments)
    assert exts == ["docx", "pdf", "pdf"]
    for att in result.attachments:
        assert att["url"].startswith("https://yz.example.edu.cn/")
        assert att["filename"]
    names = {a["filename"] for a in result.attachments}
    assert "fenshuxian.pdf" in names
    assert "zhuanye.pdf" in names
    assert "other.docx" in names


def test_date_falls_back_to_body_when_no_meta():
    html = """
    <html><head><title>某校2025年硕士研究生招生简章</title></head>
    <body><div><p>我校2025年硕士研究生招生简章如下，发布时间 2025年3月12日。</p>
    <p>请各位考生按时完成网上报名。</p></div></body></html>
    """
    result = extract(html, "https://example.edu.cn/a.html")
    assert result.publish_date == date(2025, 3, 12)


def test_builtin_fallback_when_engines_missing(monkeypatch):
    monkeypatch.setattr(extractor_mod, "HAVE_TRAFILATURA", False)
    monkeypatch.setattr(extractor_mod, "HAVE_READABILITY", False)
    result = extract(NOTICE_HTML, PAGE_URL)
    assert result.engine == "builtin"
    assert "教育部" in result.text
    assert len(result.attachments) == 3


def test_extract_never_raises_on_garbage():
    result = extract("<html><body><p>只有一句话</p>", "")
    assert isinstance(result, Extracted)
    assert result.text is not None


def test_extract_empty_html():
    result = extract("", "")
    assert result.text == ""
    assert result.attachments == []
