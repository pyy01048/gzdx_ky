# -*- coding: utf-8 -*-
"""考点生成：从权威来源构建「章节 → 知识点 → 题型」。

### 数据源（按可信度排序）

1. **834 考纲正文**（`documents` 里的「834考纲」）—— 最权威，
   直接列出"掌握/了解/理解"的考试要求，逐条转成知识点。
2. **真实真题**（贵州大学 16-21 真题、各套考试卷）—— 有答案的题目
   反推考点，附带真实题型分布。
3. **章节化教材/题库**（文件名形如「第3章 门电路.pdf」）—— 章名即知识点。

存量那 898 条自动抽取的 knowledge_points 不在数据源里：实测它们是
幻灯片标题拼接、OCR 断句残片（`services/kp_cleaner` 判定 631/898 为垃圾），
拿来做三级结构只会让进度统计失真。
"""

from __future__ import annotations

import re
from typing import Any

from services import taxonomy, kp_cleaner


# --------------------------------------------------------------------------- #
# 一、834 考纲 → 知识点
# --------------------------------------------------------------------------- #
_OUTLINE_MODULE_RE = re.compile(r"^\s*(模拟电路部分|数字电路部分|数字部分|模拟部分)\s*[:：]?\s*$")

# 考纲一行常写成 "了解A、B；掌握C。了解D。"
# 所以按动词切分，动词可出现在行首，也可出现在句中。
# 注意：**不含"能"** —— "性能/功能/能力/储能"里的"能"会被误当动词
# （实测把"主要性能评价指标"切成了"主要性"+"评价指标"）。
_VERB_SPLIT_RE = re.compile(r"(?<![了解悉会])[；;。．]?\s*(了解|理解|熟悉|掌握)\s*[,，]?\s*")


def parse_834_outline(text: str) -> list[dict[str, Any]]:
    """解析 834 考纲正文为 [{module, requirement, name, verb}]。

    支持一行多条要求（"了解A；掌握B。了解C。"全部拆出）。
    """
    if not text:
        return []
    out: list[dict[str, Any]] = []
    module = ""
    for raw in text.splitlines():
        line = raw.strip().replace("\u3000", " ")
        if not line:
            continue
        m = _OUTLINE_MODULE_RE.match(line)
        if m:
            module = m.group(1)
            continue

        # 该行是否含考纲动词
        if not re.search(r"了解|理解|熟悉|掌握", line):
            continue
        # 跳过"考试基本要求"那类总述行（含"要求考生"）
        if "要求考生" in line or "考试" in line and "掌握" not in line:
            continue

        # 按动词切分为多条要求
        parts = _VERB_SPLIT_RE.split(line)
        # parts = [前导文本, 动词1, 内容1, 动词2, 内容2, ...]
        for i in range(1, len(parts) - 1, 2):
            verb = parts[i]
            body = (parts[i + 1] or "").strip().rstrip("。．").strip()
            if len(body) < 4:
                continue
            out.append({
                "module": module,
                "verb": verb,
                "requirement": body,
                "name": _condense(body),
            })
    return out


def _condense(requirement: str) -> str:
    """把考纲要求压成知识点名。

    "了解放大电路的主要性能评价指标以及分析方法" → "放大电路的主要性能评价指标"
    "掌握逻辑函数的代数化简方法及卡诺图化简方法" → "逻辑函数的代数化简方法"
    """
    s = requirement.strip()
    # 先砍并列："以及/及其" 之后基本都是次要内容
    s = re.split(r"以及|及其", s)[0]
    # 再按分隔符取第一段（不按单字"和"切，避免切坏"和信号"这类术语）
    s = re.split(r"[；;。．，,]", s)[0]
    s = s.strip("，,。.、 （）()")
    # 尾部"…的方法/…的特点"保留（是有意义的考点限定），只去掉纯虚词尾巴
    s = re.sub(r"[的及与和]$", "", s).strip()
    if len(s) > 30:
        s = s[:30]
    return s


# --------------------------------------------------------------------------- #
# 二、章节化资料文件名 → 知识点
# --------------------------------------------------------------------------- #
_CHAPTER_FILE_RE = re.compile(r"^第\s*([0-9]{1,2}|[一二三四五六七八九十]+)\s*章\s*(.+?)(?:\.[a-z]+)?$", re.I)


# 教材章名 → (科目, 标准章节)
# 有些资料文件名直接就是章名（"脉冲波形的产生和整形.pdf"），文件名里没有
# "数电/模电"字样，科目推断会落到"其他"。这类章名与科目的对应是确定的，
# 用显式映射比放宽全局关键词更安全（放宽会同时影响上千道题的分类）。
CHAPTER_NAME_TO_SUBJECT: dict[str, tuple[str, str]] = {
    "数模和模数转换": ("数字电子技术", "第8章 数模与模数转换"),
    "数模与模数转换": ("数字电子技术", "第8章 数模与模数转换"),
    "脉冲波形的产生和整形": ("数字电子技术", "第7章 脉冲波形的产生和整形"),
    "波形的产生和信号的转换": ("模拟电子技术", "第8章 波形的产生和信号的转换"),
    "波形的发生和信号的转换": ("模拟电子技术", "第8章 波形的产生和信号的转换"),
    "信号的运算和处理": ("模拟电子技术", "第7章 信号的运算和处理"),
    "三种基本电路动态性能比较": ("模拟电子技术", "第3章 多级放大电路"),
}


def resolve_chapter_name(body: str) -> tuple[str, str] | None:
    """章名 → (科目, 标准章节)。识别不了返回 None。"""
    b = (body or "").strip()
    if b in CHAPTER_NAME_TO_SUBJECT:
        return CHAPTER_NAME_TO_SUBJECT[b]
    for name, target in CHAPTER_NAME_TO_SUBJECT.items():
        if name in b or b in name:
            return target
    return None


def knowledge_points_from_chapter_files(docs: list[Any]) -> list[dict[str, Any]]:
    """文件名形如「第3章 门电路.pdf」的资料，章名即知识点。"""
    out = []
    for d in docs:
        name = (getattr(d, "file_name", "") or "").strip()
        m = _CHAPTER_FILE_RE.match(name)
        if not m:
            continue
        body = m.group(2).strip()
        if len(body) < 2:
            continue
        subj = taxonomy.normalize_subject(getattr(d, "subject", None))
        chapter = None

        # 文件名本身没暴露科目时，用章名显式表兜底
        if subj in ("其他", "真题综合", "电子技术基础"):
            target = resolve_chapter_name(body)
            if target:
                subj, chapter = target
        if not chapter:
            chapter = kp_cleaner.map_chapter(body, name, subj, getattr(d, "content", "") or "")

        out.append({
            "name": body,
            "subject": subj,
            "chapter": chapter,
            "document_id": getattr(d, "id", None),
            "source": "chapter_file",
        })
    return out


# --------------------------------------------------------------------------- #
# 三、真题考点 → 知识点
# --------------------------------------------------------------------------- #
def knowledge_points_from_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从真题里反推考点（按题干命中的核心术语聚合）。

    产出里带上 `question_count`：这样"这个考点考过多少题"是**推导出来的
    事实**，而不是靠递增累加 —— 脚本重跑时不会翻倍。
    """
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for q in questions:
        phrase = (q.get("knowledge_point") or "").strip()
        if len(phrase) < 2:
            continue
        subj = taxonomy.normalize_subject(q.get("subject"))
        key = (subj, phrase)
        item = agg.setdefault(key, {
            "name": phrase,
            "subject": subj,
            "chapter": q.get("chapter"),
            "question_types": [],
            "question_count": 0,
            "source": "exam",
        })
        qt = q.get("question_type") or ""
        if qt and qt not in item["question_types"]:
            item["question_types"].append(qt)
        item["question_count"] += 1
        if not item["chapter"] and q.get("chapter"):
            item["chapter"] = q["chapter"]
    return list(agg.values())


# --------------------------------------------------------------------------- #
# 四、落地：upsert 到 knowledge_points
# --------------------------------------------------------------------------- #
def upsert_knowledge_points(db, items: list[dict[str, Any]], *, commit: bool = True) -> dict[str, int]:
    """把知识点写入数据库（按 科目+名称 去重，已存在则补齐空缺字段）。

    返回 {created, updated, skipped}
    """
    from models import KnowledgePoint

    created = updated = skipped = 0
    for it in items:
        name = (it.get("name") or "").strip()
        if len(name) < 2 or len(name) > 60:
            skipped += 1
            continue
        assessment = kp_cleaner.assess_knowledge_point(name, it.get("subject"))
        if not assessment["is_valid"]:
            skipped += 1
            continue

        subj = taxonomy.normalize_subject(it.get("subject"))
        exists = (
            db.query(KnowledgePoint)
            .filter(KnowledgePoint.subject == subj, KnowledgePoint.name == name)
            .first()
        )
        qtypes = it.get("question_types") or []
        if not qtypes:
            qtypes = taxonomy.question_types_of(subj)

        if exists:
            changed = False
            if not exists.chapter and it.get("chapter"):
                exists.chapter = it["chapter"]
                changed = True
            if not exists.question_types:
                exists.question_types = qtypes
                changed = True
            if not exists.document_id and it.get("document_id"):
                exists.document_id = it["document_id"]
                changed = True
            if it.get("question_count"):
                exists.question_count = max(exists.question_count or 0, it["question_count"])
                changed = True
            if it.get("exam_frequency"):
                exists.exam_frequency = max(exists.exam_frequency or 0, it["exam_frequency"])
                changed = True
            updated += 1 if changed else 0
            skipped += 0 if changed else 1
        else:
            import datetime

            db.add(KnowledgePoint(
                name=name,
                subject=subj,
                chapter=it.get("chapter"),
                description=it.get("description") or it.get("requirement"),
                question_types=qtypes,
                document_id=it.get("document_id"),
                difficulty=int(it.get("difficulty") or 3),
                exam_frequency=int(it.get("exam_frequency") or 0),
                question_count=int(it.get("question_count") or 0),
                mastery=0,
                next_review=datetime.datetime.now() + datetime.timedelta(days=1),
            ))
            created += 1

    if commit:
        db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


# --------------------------------------------------------------------------- #
# 五、考纲要求的难度打分
# --------------------------------------------------------------------------- #
_VERB_DIFFICULTY = {"了解": 2, "理解": 3, "熟悉": 3, "掌握": 4, "会": 4, "能": 4}


def outline_difficulty(verb: str) -> int:
    return _VERB_DIFFICULTY.get((verb or "").strip(), 3)
