# -*- coding: utf-8 -*-
"""工科/理科复试大纲爬取骨架（V17）。

目标：各校研究生院官网「复试」栏目 → 复试科目/大纲页 → 结构化
{school, subject, syllabus_url, sections[]} → 供 codebank 灌知识点。

合规与形态沿用 spider_notices：robots 检查、2-5s 礼貌延迟、UA 声明。
当前为**骨架版**：标题规则匹配（含"复试"的列表链接）+ 章节标题抽取
（第X章/一、二、三…），正文结构化留待真机联调各校模板后迭代。

接口：`discover_syllabus_links(html, base_url)` 纯函数可测；
`crawl_syllabus(db, school_id, dry_run)` 编排入口（落 code_questions 的
statement 前缀占位 + tags=[复试大纲]，供全景视图先挂出来）。
"""
from __future__ import annotations

import re
from typing import Dict, List

# 匹配含"复试"的栏目/大纲链接（a 标签文本+href）
_LINK_RE = re.compile(
    r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>([^<]{0,60}?复试[^<]{0,30})</a>', re.I)
# 章节标题：第X章 / 一、二、（中文序号）
_SECTION_RE = re.compile(r"(第[一二三四五六七八九十\d]+章[^<\n]{0,40}|[一二三四五六七八九十]+、[^<\n]{0,40})")
_TAG_RE = re.compile(r"<[^>]+>")


def discover_syllabus_links(html: str, base_url: str) -> List[Dict[str, str]]:
    """从栏目页 HTML 抽出含「复试」的链接（绝对化 + 去重）。"""
    out, seen = [], set()
    for href, text in _LINK_RE.findall(html or ""):
        title = _TAG_RE.sub("", text).strip()
        if not title:
            continue
        url = href if href.startswith("http") else base_url.rstrip("/") + "/" + href.lstrip("./")
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": title, "url": url})
    return out[:30]


def extract_sections(page_html: str) -> List[str]:
    """从大纲正文抽章节标题（第X章 / 一、…），去 HTML 标签后匹配。"""
    text = _TAG_RE.sub(" ", page_html or "")
    hits = []
    for m in _SECTION_RE.finditer(text):
        t = m.group(1).strip()
        if t not in hits:
            hits.append(t)
    return hits[:40]


def crawl_syllabus(db, school_id: int, dry_run: bool = True) -> Dict:
    """编排入口：读院校官网 URL → 抓栏目页 → 发现大纲链接 → 抽章节 → 入库。

    真机联调时接通 _fetch（复用 spider_notices._fetch + robots 检查）；
    云端/离线环境无网络时如实返回 skipped。
    """
    from services.kaoyan.spider_notices import _fetch, _robots_allows, _polite
    conn = db.connection().connection
    row = conn.execute(
        "SELECT name, official_url FROM kaoyan_schools WHERE id=?", (school_id,)).fetchone()
    if not row:
        return {"error": "school_not_found"}
    name, base = row  # 原生 sqlite3 fetchone 返回元组
    if not base or not _robots_allows(re.sub(r"^https?://([^/]+).*", r"\1", base)):
        return {"school": name, "skipped": "no_url_or_robots"}
    _polite()
    try:
        html = _fetch(base)
    except Exception as e:
        return {"school": name, "skipped": f"fetch_failed:{e}"[:120]}
    links = discover_syllabus_links(html, base)
    sections_map: Dict[str, List[str]] = {}
    for lk in links[:5]:
        _polite()
        try:
            sections_map[lk["title"]] = extract_sections(_fetch(lk["url"]))
        except Exception:
            sections_map[lk["title"]] = []
    if dry_run:
        return {"school": name, "links": links, "sections": sections_map,
                "dry_run": True}
    from services.codebank_service import upsert_question
    created = 0
    for title, secs in sections_map.items():
        if not secs:
            continue
        upsert_question(db, {
            "title": f"复试大纲 · {title}",
            "subject": "复试大纲",
            "difficulty": "easy",
            "tags": ["复试大纲", row["name"]],
            "languages": [],
            "statement": "；".join(secs),
            "source": "syllabus_spider",
            "frequency": 3,
        })
        created += 1
    return {"school": row["name"], "links": len(links), "created": created}
