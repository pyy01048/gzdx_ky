# -*- coding: utf-8 -*-
"""结构化文档解析：把扁平的文档正文切成「章节 → 小节 → 题型」。

背景：存量 knowledge_chunks 只有 subject 一个维度，AI 检索时无法限定
"只在这一章里找"，也无法回答"这一章考过哪些题型"。本模块负责：

1. `parse_structure(text, subject)` → 识别章节树
2. `assign_structure(chunks, structure)` → 给每个分块打上 chapter 标记
3. `extract_knowledge_points(structure)` → 三级结构的中间层

设计原则：**启发式 + 可解释**。不依赖 AI（省 token、离线可用），
识别不出章节时优雅降级为 subject 级扁平结构，绝不报错中断解析。
"""

from __future__ import annotations

import re
from typing import Any

from services import taxonomy


# 一行的最大长度：超过此长度不可能是标题
_MAX_HEADING_LEN = 60


def _clean(line: str) -> str:
    line = line.strip()
    line = re.sub(r"[ \t\u3000]+", " ", line)
    return line


def _is_chapter(line: str) -> bool:
    if not line or len(line) > _MAX_HEADING_LEN:
        return False
    for pat in taxonomy.CHAPTER_PATTERNS:
        if re.match(pat, line):
            return True
    return False


def _is_section(line: str) -> bool:
    if not line or len(line) > _MAX_HEADING_LEN:
        return False
    for pat in taxonomy.SECTION_PATTERNS:
        if re.match(pat, line):
            return True
    return False


def _normalize_chapter(raw: str, subject: str) -> str:
    """把识别到的章标题对齐到大纲里的标准章名。

    例如正文写 "第 4 章 组合逻辑电路"，大纲写 "第4章 组合逻辑电路"，
    则归一到大纲写法，保证统计口径一致。
    """
    outline = taxonomy.chapters_of(subject)
    if not outline:
        return raw

    # 提取章号
    m = re.search(r"第\s*([0-9一二三四五六七八九十]+)\s*章", raw)
    if m:
        num = m.group(1)
        for std in outline:
            if re.search(r"第\s*" + re.escape(num) + r"\s*章", std):
                return std

    # 无章号：按关键片段包含匹配
    key = re.sub(r"^[\s0-9.、]*", "", raw)[:12]
    if key:
        for std in outline:
            body = re.sub(r"^第\s*[0-9一二三四五六七八九十]+\s*章\s*", "", std)
            if body and (body[:6] in raw or key[:6] in body):
                return std
    return raw


def parse_structure(text: str, subject: str | None = None) -> dict[str, Any]:
    """从正文中识别「章节 → 小节」结构。

    返回：
        {
          "subject": 归一化科目,
          "level": "structured" | "flat",
          "chapters": [
             {"title": 章名, "sections": [{"title": 节名, "start": 行号, "end": 行号}],
              "start": 行号, "end": 行号}
          ],
          "chapter_titles": [章名...],
        }
    """
    std = taxonomy.normalize_subject(subject)
    lines = (text or "").splitlines()

    chapters: list[dict[str, Any]] = []
    cur_ch: dict[str, Any] | None = None
    cur_sec: dict[str, Any] | None = None

    for idx, raw in enumerate(lines):
        line = _clean(raw)
        if not line:
            continue

        if _is_chapter(line):
            title = _normalize_chapter(line, std)
            # 同名章重复出现（页眉页脚）则忽略
            if cur_ch is not None and cur_ch["title"] == title:
                continue
            if cur_ch is not None:
                cur_ch["end"] = idx - 1
                if cur_sec is not None:
                    cur_sec["end"] = idx - 1
            cur_ch = {"title": title, "sections": [], "start": idx, "end": idx}
            chapters.append(cur_ch)
            cur_sec = None
            continue

        if cur_ch is not None and _is_section(line):
            if cur_sec is not None:
                cur_sec["end"] = idx - 1
            cur_sec = {"title": line, "start": idx, "end": idx}
            cur_ch["sections"].append(cur_sec)

    if cur_ch is not None:
        cur_ch["end"] = len(lines) - 1
        if cur_sec is not None:
            cur_sec["end"] = len(lines) - 1

    # 过滤掉只有标题没有内容的伪章节
    chapters = [c for c in chapters if c["end"] - c["start"] >= 2]

    level = "structured" if chapters else "flat"
    return {
        "subject": std,
        "level": level,
        "chapters": chapters,
        "chapter_titles": [c["title"] for c in chapters],
    }


def chapter_of_offset(structure: dict[str, Any], offset: int) -> str | None:
    """给定字符偏移，返回所属章节名。"""
    for ch in structure.get("chapters", []):
        if ch["start"] <= offset <= ch["end"]:
            return ch["title"]
    return None


def assign_structure(text: str, structure: dict[str, Any], chunks: list[str]) -> list[str | None]:
    """给每个分块判定所属章节。

    做法：在原文中逐块定位（顺序推进，避免重复文本错配），
    取分块起始位置所处的章。
    """
    chapters = structure.get("chapters", [])
    if not chapters or not chunks:
        return [None] * len(chunks)

    # 行号 → 字符偏移 的换算表
    lines = text.splitlines(keepends=True)
    line_start: list[int] = []
    pos = 0
    for ln in lines:
        line_start.append(pos)
        pos += len(ln)
    total = pos

    def offset_to_line(off: int) -> int:
        # 二分查找
        lo, hi = 0, len(line_start) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_start[mid] <= off:
                lo = mid
            else:
                hi = mid - 1
        return lo

    cursor = 0
    result: list[str | None] = []
    for ch in chunks:
        probe = (ch or "").strip()[:60]
        if not probe:
            result.append(None)
            continue
        found = text.find(probe, cursor)
        if found < 0:
            found = text.find(probe)          # 回退全量搜索
        if found < 0:
            result.append(None)
            continue
        cursor = found + 1
        line_no = offset_to_line(min(found, max(total - 1, 0)))
        result.append(chapter_of_offset(structure, line_no))
    return result


def extract_knowledge_points(
    structure: dict[str, Any],
    *,
    max_per_chapter: int = 12,
    subject: str | None = None,
) -> list[dict[str, Any]]:
    """从章节树推导知识点（章节下的二级条目）。

    优先用小节名作知识点（最可靠）；无小节时从正文无法可靠推断，
    返回空列表，由调用方决定是否走 AI 抽取。
    """
    std = taxonomy.normalize_subject(subject or structure.get("subject"))
    kps: list[dict[str, Any]] = []
    for ch in structure.get("chapters", []):
        sections = ch.get("sections", [])[:max_per_chapter]
        for sec in sections:
            title = sec["title"]
            # 去掉编号前缀
            name = re.sub(r"^\s*(第\s*[0-9一二三四五六七八九十]+\s*节|[0-9]{1,2}\.[0-9]{1,2}|[一二三四五六七八九十]+[、.])\s*", "", title).strip()
            if not name or len(name) < 2:
                continue
            kps.append({
                "name": name,
                "chapter": ch["title"],
                "subject": std,
                "question_types": _types_for(name, std),
            })
    return kps


def _types_for(name: str, subject: str) -> list[str]:
    """小节名 → 可能题型（启发式）。"""
    types: list[str] = []
    hinted = taxonomy.guess_question_type(name, subject)
    if hinted:
        types.append(hinted)
    # 章节语境补充：先默认带常见题型，后续由答题/错题数据收敛
    for t in taxonomy.question_types_of(subject):
        if t not in types:
            types.append(t)
        if len(types) >= 4:
            break
    return types


def summarize(structure: dict[str, Any]) -> dict[str, Any]:
    """给接口返回用的精简结构。"""
    return {
        "subject": structure.get("subject"),
        "level": structure.get("level"),
        "chapter_count": len(structure.get("chapters", [])),
        "chapters": [
            {
                "title": ch["title"],
                "section_count": len(ch.get("sections", [])),
                "sections": [s["title"] for s in ch.get("sections", [])][:20],
            }
            for ch in structure.get("chapters", [])
        ],
    }
