# -*- coding: utf-8 -*-
"""重建答疑训练集：把"照抄型"样本换成真正的问答对。

### 为什么必须重建（实测证据）

| 指标 | 现状 |
|------|------|
| SFTExample 里 `assistant` 是 `user` 子串的比例 | **92.2%（4280/4641）** |
| train.jsonl 答案与题干重合度 >0.8 的样本 | **91.6%** |
| 微调模型照抄率（见 eval_qa_model.py） | **0.72** |

原数据集是"请根据以下资料讲解要点：<原文>" → "<同一段原文的前 180 字>"。
模型学到的唯一技能就是**复读输入**，完全没有答疑能力。

### 重建策略：只从有确定答案的来源生成

1. **真题（有答案）** —— 最可靠。题干 → 正确答案 + 解析
2. **知识分块里的定义句** —— "X 是指……" / "X 的定义是……" 反推 Q&A
3. **考纲考点** —— "X 是什么/在考试中怎么考" → 用知识点描述作答
4. **真题考点统计** —— "这一章考过哪些题型" → 用真实题量作答

**共同要求**：`assistant` 必须是**重新组织的讲解**，绝不能是 `user` 的切片。
生成后逐条校验：若 assistant 仍是 user 子串 → 直接丢弃。

执行：
    python scripts/build_qa_dataset.py --dry-run   # 先看产出与质检
    python scripts/build_qa_dataset.py             # 写出 train/val/jsonl
"""

from __future__ import annotations

import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from database import SessionLocal  # noqa: E402
from models import QuizQuestion, KnowledgeChunk, KnowledgePoint  # noqa: E402
from services import taxonomy  # noqa: E402

DRY_RUN = "--dry-run" in sys.argv
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "lora_finetune_v2",
)

SYSTEM = (
    "你是一位考研辅导老师，负责计算机与电子信息类考研的答疑，"
    "专长是数字电子技术、模拟电子技术（834 电子技术基础）以及数学二、英语二、政治。"
    "回答要求：先给结论，再解释原理，必要时给出解题步骤；"
    "只讲与问题相关的内容，不要复述题目原文。"
)

# 答案不能是题干的切片 —— 这是原数据集最大的问题
def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def answer_is_copy(question: str, answer: str, *, n: int = 16) -> bool:
    """答案是否基本照抄题干。"""
    a, q = _normalize(answer), _normalize(question)
    if len(a) < n:
        return False
    grams = [a[i:i + n] for i in range(len(a) - n + 1)]
    if not grams:
        return False
    return sum(1 for g in grams if g in q) / len(grams) > 0.5


# --------------------------------------------------------------------------- #
# 来源 1：真题（有答案）
# --------------------------------------------------------------------------- #
_OPT_LETTERS = "ABCD"

def from_quiz_questions(db) -> list[dict]:
    """真题 → Q&A。只有拿到答案（字母或文本）才可用。"""
    out = []
    rows = db.query(QuizQuestion).filter(
        QuizQuestion.answer.isnot(None), QuizQuestion.answer != ""
    ).all()
    for q in rows:
        stem = (q.content or "").strip()
        if len(stem) < 10:
            continue
        ans_raw = (q.answer or "").strip()
        opts = q.options if isinstance(q.options, list) else []

        # 把选项字母展开成选项内容，否则"答案：C"毫无信息量
        ans_text = ans_raw
        if re.fullmatch(r"[A-D]", ans_raw.upper()) and opts:
            idx = _OPT_LETTERS.find(ans_raw.upper())
            if 0 <= idx < len(opts):
                ans_text = opts[idx]

        parts = [f"答案是：{ans_text}"]
        if q.analysis:
            parts.append(f"解析：{q.analysis}")
        elif opts:
            parts.append("解析：其余选项与题干条件不符，逐一排查即可定位唯一正确项。")
        parts.append(
            f"这道题考的是「{q.knowledge_point or q.chapter or q.subject}」，"
            f"属于 {q.chapter or '本科目'} 的内容。"
        )
        answer = "\n".join(parts)

        question = stem + ("\n" + "\n".join(opts) if opts else "")
        if answer_is_copy(question, answer):
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
            "subject": taxonomy.normalize_subject(q.subject),
            "source": "quiz",
        })
    return out


# 页面导航/OCR 残留前缀：定义句常被抽到"上页输出脉冲的幅度"这种带噪声的术语
_TERM_NOISE = [
    "上页", "下页", "返回", "总目录", "推出", "目录", "单击", "标题文字",
    "本节", "本章", "小结", "作业", "思考题", "如图所示", "如下图",
]
# 明显不是术语的开头/结尾
_TERM_BAD_PREFIX = re.compile(r"^(的|了|是|在|和|与|或|这|那|其|该|本|如下|例如|因此|所以)")
_TERM_BAD_SUFFIX = re.compile(r"(的|了|是|在|和|与|或|等|中|上|下|里)$")


def _clean_term(term: str) -> str | None:
    """清洗抽出来的术语；不合格返回 None。"""
    t = (term or "").strip()
    # 去掉导航噪声前缀
    for noise in _TERM_NOISE:
        if t.startswith(noise) and len(t) > len(noise) + 1:
            t = t[len(noise):].strip()
    # 去掉出现的标点/空白
    t = re.sub(r"^[\s，,。.、：:；;（）()【】\[\]]+", "", t)
    t = re.sub(r"[\s，,。.、：:；;（）()【】\[\]]+$", "", t)
    if len(t) < 2 or len(t) > 14:
        return None
    if any(n in t for n in _TERM_NOISE):
        return None
    if _TERM_BAD_PREFIX.match(t) or _TERM_BAD_SUFFIX.search(t):
        return None
    # 必须含中文或像英文术语
    if not re.search(r"[\u4e00-\u9fff]", t) and not re.fullmatch(r"[A-Za-z][A-Za-z0-9\-/]{1,12}", t):
        return None
    # 全数字
    if re.fullmatch(r"[\d\s.]+", t):
        return None
    return t


# --------------------------------------------------------------------------- #
# 来源 2：知识分块里的定义句
# --------------------------------------------------------------------------- #
# 只认明确的定义句式，避免把普通叙述句当定义
_DEF_PATTERNS = [
    re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,14})\s*(?:是指|指的是|定义为|称为|叫做)\s*([^。；\n]{8,120})"),
    re.compile(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,14})\s*的?定义\s*[:：是]\s*([^。；\n]{8,120})"),
    re.compile(r"所谓\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,14})\s*[,，]?\s*(?:就是|是指)\s*([^。；\n]{8,120})"),
]


def from_definitions(db, *, limit: int = 3000) -> list[dict]:
    """知识分块 → 「X 是什么」问答。

    覆盖全部主线科目（不只数电模电）—— 英语/数学的术语同样值得进训练集。
    """
    out = []
    rows = db.query(KnowledgeChunk).filter(
        KnowledgeChunk.subject.in_(list(taxonomy.CORE_SUBJECTS))
    ).limit(limit * 4).all()
    seen: set[str] = set()
    for c in rows:
        text = (c.text or "").strip()
        if len(text) < 30:
            continue
        subject = taxonomy.normalize_subject(c.subject)
        for pat in _DEF_PATTERNS:
            matched = False
            for m in pat.finditer(text):
                term = _clean_term(m.group(1))
                body = re.sub(r"\s+", " ", m.group(2)).strip()
                if not term or term in seen or len(body) < 8:
                    continue
                seen.add(term)
                question = f"考研{subject}里，{term}是什么？"
                answer = (
                    f"{term}是指{body}。\n"
                    f"理解时要抓住它的判定条件与典型应用场景，"
                    f"这部分内容属于「{subject}」。"
                )
                if answer_is_copy(question, answer):
                    continue
                out.append({
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": answer},
                    ],
                    "subject": subject,
                    "source": "definition",
                })
                matched = True
                break
            if matched:
                break
    return out


# --------------------------------------------------------------------------- #
# 来源 3：考纲考点
# --------------------------------------------------------------------------- #
def from_outline_points(db) -> list[dict]:
    """考纲考点 → 「怎么考」问答（用考纲要求与难度作答）。"""
    out = []
    rows = db.query(KnowledgePoint).filter(
        KnowledgePoint.description.isnot(None),
        KnowledgePoint.description != "",
    ).all()
    for kp in rows:
        desc = (kp.description or "").strip()
        m = re.search(r"【考纲要求·(.+?)】(.+)", desc)
        if not m:
            continue
        verb, requirement = m.group(1), m.group(2).strip()
        subject = taxonomy.normalize_subject(kp.subject)
        qtypes = "、".join((kp.question_types or [])[:4]) or "综合"
        question = f"834 考纲对「{kp.name}」的要求是什么？复习时要注意什么？"
        answer = (
            f"考纲对这部分的要求是「{verb}」：{requirement}。\n"
            f"它在「{kp.chapter or subject}」这一章，可能的题型包括 {qtypes}。\n"
            f"复习建议：按「{verb}」的力度分配时间 —— "
            + ("要求掌握的内容需要能独立推算并写出完整过程。"
               if "掌握" in verb else
               "要求理解/熟悉的内容重在辨析概念与判别正误。"
               if ("理解" in verb or "熟悉" in verb) else
               "要求了解的内容把握基本结论和适用范围即可，不必深挖推导。")
        )
        if answer_is_copy(question, answer):
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
            "subject": subject,
            "source": "outline",
        })
    return out


# --------------------------------------------------------------------------- #
# 来源 4：真题考点统计
# --------------------------------------------------------------------------- #
def from_exam_stats(db) -> list[dict]:
    """按章节/题型统计 → 「这一章考什么、题量多大」问答。"""
    out = []
    rows = db.query(KnowledgePoint).filter(KnowledgePoint.question_count > 0).all()
    by_chapter: dict[tuple[str, str], list] = {}
    for kp in rows:
        if not kp.chapter:
            continue
        key = (taxonomy.normalize_subject(kp.subject), kp.chapter)
        by_chapter.setdefault(key, []).append(kp)

    for (subject, chapter), kps in by_chapter.items():
        kps_sorted = sorted(kps, key=lambda k: -(k.question_count or 0))
        total = sum(k.question_count or 0 for k in kps_sorted)
        if total < 3:
            continue
        top = kps_sorted[:5]
        types: list[str] = []
        for k in kps_sorted:
            for t in (k.question_types or []):
                if t not in types:
                    types.append(t)
        question = f"{subject}的「{chapter}」主要考哪些知识点？题量大吗？"
        lines = [
            f"这一章在题库里共有 {total} 道题，是{subject}的重点章节之一。",
            "考得最多的考点依次是：",
        ]
        for i, k in enumerate(top, 1):
            lines.append(f"{i}. {k.name}（{k.question_count} 题）")
        lines.append(f"常见题型：{'、'.join(types[:6])}。")
        lines.append(
            f"复习优先级建议：先把「{top[0].name}」这类高频考点吃透，"
            f"再往下铺开覆盖面。"
        )
        answer = "\n".join(lines)
        if answer_is_copy(question, answer):
            continue
        out.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
            "subject": subject,
            "source": "exam_stats",
        })
    return out


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    db = SessionLocal()
    try:
        print("=" * 74)
        print("重建答疑训练集" + ("（DRY-RUN）" if DRY_RUN else ""))
        print("=" * 74)

        sources = [
            ("真题（有答案）", from_quiz_questions),
            ("知识分块定义句", from_definitions),
            ("834 考纲考点", from_outline_points),
            ("真题章节统计", from_exam_stats),
        ]

        all_items: list[dict] = []
        for name, fn in sources:
            try:
                items = fn(db)
            except Exception as e:
                print(f"  [!] {name} 生成失败: {type(e).__name__}: {e}")
                items = []
            print(f"  {name:<16} → {len(items):>5} 条")
            all_items.extend(items)

        print(f"\n  合计 {len(all_items)} 条")

        # —— 去重 —— #
        seen: set[str] = set()
        deduped = []
        for it in all_items:
            key = _normalize(it["messages"][1]["content"])[:120]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(it)
        print(f"  去重后 {len(deduped)} 条（去掉 {len(all_items)-len(deduped)} 条重复）")

        # —— 质检：确保没有照抄样本 —— #
        bad = [it for it in deduped
               if answer_is_copy(it["messages"][1]["content"],
                                 it["messages"][2]["content"])]
        print(f"  照抄样本残留 {len(bad)} 条（应为 0）")
        deduped = [it for it in deduped if it not in bad]

        # —— 分布 —— #
        from collections import Counter
        print("\n  按来源:")
        for k, v in Counter(it["source"] for it in deduped).most_common():
            print(f"     {k:<14} {v:>5}")
        print("  按科目:")
        for k, v in Counter(it["subject"] for it in deduped).most_common():
            print(f"     {k:<14} {v:>5}")

        # —— 长度分布 —— #
        ql = [len(it["messages"][1]["content"]) for it in deduped]
        al = [len(it["messages"][2]["content"]) for it in deduped]
        if ql:
            print(f"\n  提问长度  均值 {sum(ql)/len(ql):.0f}  最大 {max(ql)}")
            print(f"  回答长度  均值 {sum(al)/len(al):.0f}  最大 {max(al)}")

        # —— 样例 —— #
        print("\n  样例（每来源 1 条）:")
        shown = set()
        for it in deduped:
            if it["source"] in shown:
                continue
            shown.add(it["source"])
            print(f"\n   [{it['source']}]")
            print(f"   Q: {it['messages'][1]['content'][:110]}")
            print(f"   A: {it['messages'][2]['content'][:180]}")

        if DRY_RUN:
            print("\n[!] DRY-RUN，未写文件")
            return 0

        # —— 划分并写出 —— #
        random.seed(42)
        random.shuffle(deduped)
        n_val = max(1, int(len(deduped) * 0.1))
        val, train = deduped[:n_val], deduped[n_val:]

        os.makedirs(OUT_DIR, exist_ok=True)
        for name, data in (("train.jsonl", train), ("val.jsonl", val)):
            path = os.path.join(OUT_DIR, name)
            with open(path, "w", encoding="utf-8") as f:
                for it in data:
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
            print(f"  [✓] {path}  {len(data)} 条")

        print(f"\n[✓] 新训练集就绪：{OUT_DIR}")
        print("    下一步：")
        print(f"      python lora_finetune.py --stage train --data-dir {OUT_DIR}")
        print("      python eval_qa_model.py --limit 8 --compare")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
