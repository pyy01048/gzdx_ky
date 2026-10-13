# -*- coding: utf-8 -*-
"""
IMA 知识库条目分类器
====================
把一条 IMA 资料映射到本平台的三维分类：

    stage    : 初试 / 复试
    subject  : 数模电 / 408 / 信号与系统 / 公共课-数学 / 公共课-政治 / 公共课-英语 / 其他
    doc_type : 知识 / 试题 / 单词

设计原则：
1. **规则优先、可解释**：纯关键词+路径规则，不依赖 LLM，保证可复现、可审计。
2. **优先级明确**：科目判定的顺序即优先级，先命中先得；避免"阶段测"这类
   跨科目词被单一规则误吞。
3. **存疑不硬猜**：无法判定时返回 subject='其他' + needs_review=True，
   交给人工或后续 LLM 复核，绝不把不确定结果写成确定值。

用法：
    from ima_classify import classify_item
    r = classify_item(title, folder_path, intro)
    # -> {"stage":..., "subject":..., "doc_type":..., "needs_review":..., "reason":...}
"""
from __future__ import annotations

import re
from typing import Optional

# --------------------------------------------------------------------------- #
# 科目规则表：(科目, 关键词正则)
# 顺序 = 优先级。靠前的先匹配。
# --------------------------------------------------------------------------- #
SUBJECT_RULES: list[tuple[str, str]] = [
    # 政治：主题词非常独有，放最前避免被"强化班/阶段测"等泛词干扰
    ("公共课-政治", r"政治|马原|史纲|毛中特|思修|徐涛|近代史|马克思主义|辩证法|认识论"),
    # 英语
    ("公共课-英语", r"英语|核心词|长难句|阅读理解|作文|词汇闪过|闪过"),
    # 数学：主题词 + 章节勘误（章节号 + 数学主题）
    ("公共课-数学", r"高数|线代|概率|数理统计|公式提速班|极限|导数|积分|级数|不等式|"
                    r"二重积分|三重积分|数学|章节[一二三四五六七八九十]+\s*(极限|导数|积分)"),
    # 数模电：专业课，主题词明确
    ("数模电", r"数电|模电|数字电子|模拟电子|电子技术|门电路|逻辑代数|触发器|"
               r"电工学|半导体|二极管|三极管|放大电路|834|915|电子技术基础"),
    # 408 计算机
    ("408", r"计算机|操作系统|组成原理|计算机网络|数据结构|微机|数图|数字图像|"
            r"EDA|Linux|linux|C\s*语言|算法"),
    # 信号与系统 / 通信
    ("信号与系统", r"信号与系统|通信原理|通信|高频|调制|混频|滤波"),
]

# 复试判定（比科目判定更优先，因为复试资料可能含任意专业课词汇）
RETEST_PAT = r"复试|面试|复试问答|调剂复试"

# 单词类判定（优先级最高，单词库是独立模块）
WORD_PAT = r"词汇|单词|闪过|核心词|背诵|默写本"

# doc_type 规则：(类型, 正则)，顺序=优先级
DOCTYPE_RULES: list[tuple[str, str]] = [
    ("试题", r"真题|刷题本|押题|阶段测|必刷|题库|试卷|模拟卷|测试卷|习题|课后题|"
             r"问答|简答|每日一题|100题|判分"),
    ("知识", r"讲义|笔记|框架|教材|知识点|详解|课本|复习笔记|勘误|大纲|总结|梳理"),
]

# 文件夹路径 → 科目提示（比标题弱，但能救"第二天讲义"这类无主题标题）
PATH_SUBJECT_HINTS: list[tuple[str, str]] = [
    (r"数电", "数模电"),
    (r"模电", "数模电"),
    (r"词汇|单词|闪过", "公共课-英语"),
    (r"数学|高数|线代|概率", "公共课-数学"),
    (r"政治", "公共课-政治"),
    (r"英语", "公共课-英语"),
    (r"通信|信号", "信号与系统"),
    (r"计算机|408|操作系统|组成|网络", "408"),
    (r"复试|面试", "复试"),
]


def _first_match(pattern: str, text: str) -> Optional[str]:
    m = re.search(pattern, text)
    return m.group(0) if m else None


def classify_item(
    title: str,
    folder_path: str = "",
    intro: str = "",
) -> dict:
    """把一条 IMA 资料分类到 (stage, subject, doc_type)。

    Args:
        title: IMA 条目标题（最重要的信号）
        folder_path: 所属文件夹路径，如 "考研资料数据集V1.0/数电资料"
        intro: IMA 已解析的正文片段（辅助判断，可为空）

    Returns:
        {
          "stage": "初试"|"复试",
          "subject": 科目字符串,
          "doc_type": "知识"|"试题"|"单词",
          "needs_review": bool,   # True 表示科目/类型存疑，需人工或 LLM 复核
          "reason": 命中说明（便于审计）
        }
    """
    t = (title or "").strip()
    path = (folder_path or "").strip()
    # intro 只取前 800 字符参与判断，避免长文本噪声与性能问题
    body = (intro or "")[:800]
    hay = f"{t} {path} {body}"

    reasons: list[str] = []

    # ---------- 1. stage：复试优先（复试资料可含任意专业课词） ----------
    stage = "初试"
    hit = _first_match(RETEST_PAT, hay)
    if hit:
        stage = "复试"
        reasons.append(f"复试命中「{hit}」")

    # ---------- 2. doc_type ----------
    doc_type = "知识"  # 默认：讲义类资料占多数
    # 单词类：标题 + 文件夹路径一起看。
    # 典型场景：标题是「单元词 List 1-2」这种无主题词，必须靠路径
    # 「27考研《词汇闪过》」里的「闪过」才能识别为单词库。
    if _first_match(WORD_PAT, f"{t} {path}"):
        doc_type = "单词"
        reasons.append("单词类(标题/路径命中)")
    else:
        for dtype, pat in DOCTYPE_RULES:
            hit = _first_match(pat, t)
            if hit:
                doc_type = dtype
                reasons.append(f"{dtype}(标题命中「{hit}」)")
                break
        else:
            # 标题没命中，退而求其次看路径+正文
            for dtype, pat in DOCTYPE_RULES:
                hit = _first_match(pat, f"{path} {body}")
                if hit:
                    doc_type = dtype
                    reasons.append(f"{dtype}(路径/正文命中「{hit}」)")
                    break

    # ---------- 3. subject ----------
    subject = None
    # 3.1 标题优先
    for subj, pat in SUBJECT_RULES:
        hit = _first_match(pat, t)
        if hit:
            subject = subj
            reasons.append(f"科目{subj}(标题命中「{hit}」)")
            break
    # 3.2 标题没命中 → 路径提示
    if subject is None:
        for pat, subj in PATH_SUBJECT_HINTS:
            if re.search(pat, path):
                subject = subj
                reasons.append(f"科目{subject}(路径命中「{path}」)")
                break
    # 3.3 路径也没有 → 正文兜底（放宽，仅取明确主题词）
    if subject is None:
        for subj, pat in SUBJECT_RULES:
            hit = _first_match(pat, body)
            if hit:
                subject = subj
                reasons.append(f"科目{subj}(正文命中「{hit}」)")
                break

    needs_review = False
    if subject is None:
        subject = "其他"
        needs_review = True
        reasons.append("科目未命中任何规则→待复核")

    # 单词类强制归入英语（词汇资料只可能是英语）
    if doc_type == "单词" and subject != "公共课-英语":
        reasons.append(f"单词类科目由{subject}校正为公共课-英语")
        subject = "公共课-英语"

    return {
        "stage": stage,
        "subject": subject,
        "doc_type": doc_type,
        "needs_review": needs_review,
        "reason": "; ".join(reasons) if reasons else "无命中(默认)",
    }


# --------------------------------------------------------------------------- #
# 自测：覆盖本库典型标题，防止规则回归
# --------------------------------------------------------------------------- #
_SELFTEST = [
    ("《数字电子技术基础（第6版）》阎石 笔记和课后习题（含考研真题）详解 .pdf", "", ""),
    ("线代讲义（数一二三全）.pdf", "", ""),
    ("高数刷题本（平板单题单页版）（数三）.pdf", "", ""),
    ("【27徐涛强化班】马原-10认识-复盘笔记.pdf", "", ""),
    ("2027强化课阶段测（史纲)【笔迹版】.pdf", "", ""),
    ("《计算机操作系统（第三版）》汤小丹 .pdf", "", ""),
    ("计算机网络问答.pdf", "", ""),
    ("模电押题.pdf", "", ""),
    ("考研复试真的很容易之通信电子类问答全集.pdf", "", ""),
    ("单元词 List 1-2.pdf", "考研资料数据集V1.0/27考研《词汇闪过》", ""),
    ("第二天讲义.pdf", "考研资料数据集V1.0/博学课划重点/数电", ""),
    ("章节一 极限勘误文件.pdf", "", ""),
    ("EDA简答.pdf", "", ""),
]


if __name__ == "__main__":
    print(f"{'标题':46s} | {'stage':4s} | {'subject':12s} | {'type':4s} | 复核")
    print("-" * 100)
    for title, path, intro in _SELFTEST:
        r = classify_item(title, path, intro)
        flag = "★" if r["needs_review"] else ""
        print(f"{title[:44]:46s} | {r['stage']:4s} | {r['subject']:12s} | "
              f"{r['doc_type']:4s} | {flag}")
