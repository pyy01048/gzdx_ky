# -*- coding: utf-8 -*-
"""真题 → 结构化题库：从真题/试卷正文里抽取真正的题目。

### 为什么需要

实测 `quiz_questions` 只有 7 道题，而 `documents` 里有 1545 篇资料，
其中"贵州大学电子技术基础真题16-21"、"考试卷带解析(1)-(4)"都是**真实题目**，
只是一直躺在 `documents.content` 里当纯文本，没被结构化。

本模块把这些文本抽成 `quiz_questions`：
  - 识别题型大标题（一、填空题 / 二、选择题 / 三、判断题 …）
  - 按题号切分单题（1、 / 12、 / 1. ）
  - 拆出选项（A、… B、… C、… D、…）
  - 按关键词判定 科目 / 章节 / 知识点 / 题型

纯本地正则实现，不依赖 AI，可重复执行（内容哈希去重）。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from services import taxonomy, kp_cleaner
from services.quiz_content_gate import admit as _gate_admit
from services.quiz_content_gate import gate_log_summary
from services.extraction_noise import (
    clean_answer as _clean_answer,
    clean_content as _clean_content,
    split_options_enabled as _split_options_enabled,
    split_stem_and_options as _split_stem_options,
    strip_cross_question_leak as _strip_cross_leak,
)


# --------------------------------------------------------------------------- #
# 一、题型大标题 → 标准题型
# --------------------------------------------------------------------------- #
SECTION_TYPES: list[tuple[str, str]] = [
    ("填空", "填空"),
    ("选择", "选择"),
    ("判断", "判断"),
    ("简答", "简答"),
    ("计算", "计算"),
    ("分析", "分析"),
    ("设计", "设计"),
    ("证明", "证明"),
    ("作图", "画图"),
    ("画图", "画图"),
    ("论述", "论述"),
    ("综合", "综合"),
]

# 大标题正则：一、填空题（45分，每空3分）
_SECTION_RE = re.compile(
    r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*([^\n（(]{2,20}?)\s*(?:[（(][^）)]*[）)])?\s*$"
)

# 讲义/PPT 里形似"题型大标题"、实为知识点小标题的前缀词。
# 这些标题一旦被 _SECTION_RE 命中，_norm_section 会把整篇讲义误判成
# "进入某个题型区"，导致后续所有 `1. / 2、` 编号行都被当成题号切分 ——
# 这正是 3576 条 JUNK 的源头。
_NOT_A_SECTION_PREFIX = (
    "设计步骤", "设计关键", "设计方法", "设计原则", "设计要求",
    "综上所述", "综上", "小结", "本章小结", "要点", "重点", "难点",
    "知识点", "考点", "重点难点", "内容提要", "内容盛要", "目录",
    "引言", "绪论", "本章", "第", "复习", "回顾", "思考题", "习题",
    "举例", "例题", "说明", "注意", "补充", "小结与", "问题",
)
#: 命中这些词的小标题一律不视作题型大标题
_SECTION_VETO_RE = re.compile(
    r"^(?:设计步骤|设计关键|设计方法|设计原则|综上所述|综上|小结|本章小结|要点|"
    r"重点|难点|知识点|考点|内容提要|内容盛要|目录|引言|绪论|复习|回顾|"
    r"思考题|习题|举例|例题|说明|注意|补充)"
)


def _is_real_section_title(title: str) -> bool:
    """该行是否真的是"题型大标题"（而非讲义的知识点小标题）。"""
    t = (title or "").strip()
    if not t:
        return False
    if _SECTION_VETO_RE.match(t):
        return False
    # 归一化后必须真的能映射到一个标准题型，否则不是题型标题
    return bool(_norm_section(t))

# 题号正则：1、  12、  1.  3．
_QNUM_RE = re.compile(r"(?:^|\n)\s*(\d{1,3})\s*[、.．)）]\s*")

# 选项正则：A、xxx  A. xxx  A．xxx
_OPTION_RE = re.compile(r"([A-F])\s*[、.．)）]\s*")

# 答案行
_ANSWER_RE = re.compile(r"(?:答案|参考答案|【答案】)\s*[:：]?\s*([^\n]{1,200})")

# 解析行
_ANALYSIS_RE = re.compile(r"(?:解析|【解析】)\s*[:：]?\s*([^\n]{1,500})")


def _norm_section(title: str) -> str:
    for kw, t in SECTION_TYPES:
        if kw in title:
            return t
    return ""


def _clean_text(t: str) -> str:
    t = t.replace("\u3000", " ").replace("\xa0", " ")
    t = re.sub(r"\\\(|\\\)|\\\[|\\\]", "", t)          # LaTeX 定界符
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extract_questions(text: str, *, source_hint: str = "") -> list[dict[str, Any]]:
    """从一篇试卷/题库正文里抽取题目。

    返回 [{section_type, number, content, options, answer, analysis, raw}]

    ``source_hint``：文档标题/来源描述（如 ``"…康华光 精品复习课件.txt"``）。
    传入后闸门能识别"讲义/课件"来源并额外加严 —— 这是 JUNK 的主要来源；
    不传时按中性来源判定（基础规则仍然生效）。

    **入库前闸门**：每条候选都必须通过 ``services.quiz_content_gate.admit``，
    不通过的直接丢弃（不返回、不入库），并计入 ``GATE_STATS``。
    """
    if not text or len(text) < 60:
        return []

    text = _clean_text(text)
    lines = text.splitlines()

    # —— 1. 标记每行所属的大题区 —— #
    sections: list[str] = [""] * len(lines)
    cur = ""
    for i, ln in enumerate(lines):
        m = _SECTION_RE.match(ln.strip())
        # 双重判定：既要能映射到标准题型，也要排除讲义知识点小标题
        if m and _is_real_section_title(m.group(1)):
            cur = _norm_section(m.group(1))
        sections[i] = cur

    # —— 2. 收集全部题号位置 —— #
    marks: list[tuple[int, int, str]] = []   # (字符偏移, 行号, 题号)
    offset = 0
    line_offsets: list[int] = []
    for i, ln in enumerate(lines):
        line_offsets.append(offset)
        offset += len(ln) + 1

    for i, ln in enumerate(lines):
        for m in _QNUM_RE.finditer("\n" + ln):
            num = m.group(1)
            # 排除年份（2016、834 之类）与小节编号误判
            if len(num) >= 4:
                continue
            if not sections[i]:
                continue
            pos = line_offsets[i] + max(0, m.start() - 1)
            marks.append((pos, i, num))

    if not marks:
        return []

    # —— 3. 按题号切块 —— #
    questions: list[dict[str, Any]] = []
    for idx, (pos, line_no, num) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(text)
        block = text[pos:end].strip()
        if len(block) < 8:
            continue

        sec_type = sections[line_no]
        # 去掉开头题号
        body = _QNUM_RE.sub("", block, count=1).strip()

        # 抽答案 / 解析
        ans = None
        ana = None
        am = _ANSWER_RE.search(body)
        if am:
            ans = am.group(1).strip()
            body = body[:am.start()].strip()
        nm = _ANALYSIS_RE.search(body)
        if nm:
            ana = nm.group(1).strip()
            body = body[:nm.start()].strip()

        # ===== 切题源头修复 3：跨题串接检测 =====
        # 题块末尾若出现下一个题型大标题（如「四、简答题（共4题，每题6分，共24分）」），
        # 说明本块吃掉了下个题型区标题 —— 剔除后仍为空则视为切题失败。
        body, _leaked = _strip_cross_leak(body)
        if len(body) < 6:
            continue

        # ===== 切题源头修复 1：剔除页眉/页脚/试卷通知噪声 =====
        body = _clean_content(body)

        # ===== 抽选项 =====
        # 第 2 处修复（不再依赖 sec_type 判定是否为选择题）由独立开关控制，
        # 默认关闭（QUIZ_EXTRACT_SPLIT_OPTIONS=0）—— 取证发现该判据对 PDF
        # 排版乱序选项（B/C/A/D）会清空库里已有的 options，属回归。
        # 关闭时完整保留修复前的原逻辑，一行不改。
        if _split_options_enabled():
            stem_txt, options = _split_stem_options(body, sec_type)
        else:
            options = []
            om = list(_OPTION_RE.finditer(body))
            if om and sec_type in ("选择", "多选", "判断"):
                for j, o in enumerate(om):
                    ostart = o.start()
                    oend = om[j + 1].start() if j + 1 < len(om) else len(body)
                    opt_text = re.sub(r"\s+", " ", body[ostart:oend]).strip()
                    if opt_text:
                        options.append(opt_text)
                body = body[: om[0].start()].strip()
            stem_txt = body
        content = stem_txt

        # ===== 答案清洗（修复 1 的另一半：脏答案置空）=====
        ans = _clean_answer(ans)

        content = re.sub(r"\s+", " ", content).strip()
        if len(content) < 6:
            continue

        # 题干里如果选项被吞掉（如"（   ）。"后无内容），跳过
        if not content:
            continue

        # ===== 入库前内容闸门（防讲义/PPT/教材正文被当成题目）=====
        # 讲义正文常以"1. / 2、"开头，上面的编号切分无法区分二者；
        # 这里用统一的"像不像一道可回答的考试题"判据把非题目拦掉。
        ok, _reason = _gate_admit(
            content,
            options=options,
            answer=ans,
            source=source_hint,
            section_type=sec_type,
        )
        if not ok:
            continue

        questions.append({
            "section_type": sec_type,
            "number": num,
            "content": content[:2000],
            "options": options,
            "answer": ans,
            "analysis": ana,
        })

    gate_log_summary()
    return questions


# --------------------------------------------------------------------------- #
# 二、题目归位：科目 / 章节 / 知识点 / 题型
# --------------------------------------------------------------------------- #
def classify_question(
    content: str,
    *,
    subject_hint: str | None = None,
    section_type: str | None = None,
) -> dict[str, Any]:
    """判定题目的科目、章节、知识点。"""
    # 科目：数电/模电关键词（834 只有这两门，先判这两门）
    subj = subject_hint
    if not subj or taxonomy.normalize_subject(subj) in ("其他", "真题综合", "电子技术基础"):
        subj = _guess_subject(content) or taxonomy.normalize_subject(subj)

    std = taxonomy.normalize_subject(subj)

    # 章节：复用 kp_cleaner 的关键词打分。
    # 题干的证据强度等同于"知识点名"，所以传给 name 参数（权重 ×3）；
    # content 必须留空 —— 否则同一段文本还会按 content(×1) 再计一次，
    # 把"冠亚军接近则判为不确定"的保护绕过去。
    chapter = kp_cleaner.map_chapter(content, None, std)

    qtype = section_type or ""
    if not qtype:
        qtype = taxonomy.guess_question_type(content, std)
    if qtype not in taxonomy.question_types_of(std):
        # 判断/简答/综合 等不在各科表里时保留，便于统计
        qtype = qtype or "其他"

    # 知识点名：从题干里提取最可能的核心考点短语
    kp_name = _core_phrase(content, std)

    return {
        "subject": std,
        "chapter": chapter,
        "knowledge_point": kp_name or "",
        "question_type": _norm_qtype(qtype),
        "difficulty": _guess_difficulty(content, qtype),
    }


_QTYPE_MAP = {
    "选择": "single", "多选": "multiple", "判断": "judge",
    "填空": "fill", "简答": "essay", "计算": "calc",
    "分析": "essay", "设计": "essay", "证明": "essay",
    "画图": "draw", "论述": "essay", "综合": "essay", "其他": "single",
}


def _norm_qtype(t: str) -> str:
    return _QTYPE_MAP.get(t, "single")


def _guess_subject(content: str) -> str | None:
    """按关键词判断是数电还是模电。"""
    digital_kw = ["逻辑", "门电路", "触发器", "卡诺图", "真值表", "计数器", "寄存器",
                  "编码器", "译码器", "时序", "组合逻辑", "TTL", "CMOS", "与非门",
                  "或非门", "异或", "二进制", "D/A", "A/D", "数制", "555", "三态门",
                  "存储器", "可编程", "移位", "竞争冒险", "化简", "最小项", "触发器"]
    analog_kw = ["二极管", "三极管", "场效应", "放大电路", "共射", "共集", "共基",
                 "运放", "运算放大", "反馈", "差分", "静态工作点", "稳压", "整流",
                 "滤波", "功率放大", "振荡", "偏置", "PN结", "饱和失真", "截止失真",
                 "交越失真", "射极跟随", "集成运放", "有源滤波", "直流电源", "三端稳压"]
    d = sum(1 for k in digital_kw if k in content)
    a = sum(1 for k in analog_kw if k in content)
    if d == 0 and a == 0:
        return None
    return "数字电子技术" if d >= a else "模拟电子技术"


def _guess_difficulty(content: str, qtype: str) -> int:
    """粗略难度：计算/设计/分析偏难，填空选择偏易。"""
    base = {"填空": 2, "选择": 2, "判断": 2, "简答": 3,
            "计算": 4, "分析": 4, "设计": 5, "证明": 5, "画图": 4}.get(qtype, 3)
    if len(content) > 200:
        base = min(5, base + 1)
    return base


# 考点核心短语：命中术语表就取术语
_TERM_CACHE: dict[str, list[str]] = {}


def _terms_for(subject: str) -> list[str]:
    if subject in _TERM_CACHE:
        return _TERM_CACHE[subject]
    kws = kp_cleaner.CHAPTER_KEYWORDS
    terms: list[str] = []
    for ch, words in kws.items():
        std_ch = ch
        # 只取该科目大纲内的章
        if std_ch not in taxonomy.chapters_of(subject):
            continue
        for w in words:
            if 2 <= len(w) <= 12 and w not in terms:
                terms.append(w)
    terms.sort(key=len, reverse=True)
    _TERM_CACHE[subject] = terms
    return terms


def _core_phrase(content: str, subject: str) -> str:
    """从题干里提取最可能的考点短语（最长的命中术语）。"""
    for t in _terms_for(subject):
        if t in content:
            return t
    return ""


# --------------------------------------------------------------------------- #
# 三、去重
# --------------------------------------------------------------------------- #
def content_hash(content: str) -> str:
    """内容指纹（用于题目去重）。

    归一化时**必须同时去掉中英文标点** —— 只去半角的话，
    "触发器是什么？" 和 "触发器是什么" 会得到两个不同指纹，同一道题重复入库。
    """
    norm = re.sub(
        r"[\s（）()【】\[\]、,，。.；;：:？?！!“”\"'’‘、·—\-]+",
        "",
        content or "",
    )
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# 四、题库流水线升级（2026-10）：指纹 + 编辑距离去重 / 变式聚类 / AI 答案解析
# --------------------------------------------------------------------------- #
def normalize_text(content: str) -> str:
    """去空白/标点的归一化文本，用于编辑距离相似度比较。

    ==================  ⚠️ 旧口径，待废弃，禁止直接删除  ==================

    **本函数是旧归一化口径**，已知缺陷：

      * **不剥 OCR 乱码**（U+FFFD 等）—— 导致仅因乱码差异而"不同"的题
        得到不同指纹，重复检测静默失效（实测全库精确重复组因此为 0）；
      * **不归一填空位** —— ``________`` / ``＿＿`` / ``（ ）`` 被当作不同
        文本，填空题变体永远匹配不上。

    **新增判重逻辑请一律使用** ``services.quiz_content_gate.normalize_dedup``
    （剥乱码 + 归一填空位 + 去标点）。

    **不得直接删除本函数**：它仍被以下位置依赖，删除会直接报错 ——
      - ``services/qbank_builder.py`` 内部链路：``similarity_ratio`` /
        ``is_duplicate`` / ``dedupe_scan`` / ``group_variants``
      - ``routers/kb_import.py``：``_build_existing_index`` / ``_is_bank_dup``
      - ``scripts/qbank_upgrade.py``：``dedupe_scan`` / ``group_variants``
        （**注意：这是一条能改写题库的脚本链路，却跑在旧口径上**，
        改口径前必须先与本函数行为对齐，否则会按不同判据改数据）
      - ``scripts/audit_quiz_duplicates.py``

    口径统一（含上述调用点迁移与 ``qbank_upgrade.py`` 对齐）是独立立项，
    在此之前保持现状、只做归档。
    =====================================================================
    """
    norm = re.sub(
        r"[\s（）()【】\[\]、,，。.；;：:？?！!“”\"'’‘、·—\-]+",
        "",
        content or "",
    )
    return norm.lower()


def similarity_ratio(a: str, b: str) -> float:
    """两题干文本相似度 0~1（基于 difflib.SequenceMatcher）。"""
    from difflib import SequenceMatcher
    na, nb = normalize_text(a), normalize_text(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def is_duplicate(a: str, b: str, threshold: float = 0.86) -> bool:
    """编辑距离去重判定：题干高度相似视为重复（阈值默认 0.86）。"""
    return similarity_ratio(a, b) >= threshold


def dedupe_scan(rows: list[dict], threshold: float = 0.86) -> list[dict]:
    """全量疑似重复题扫描（指纹预筛 + 编辑距离复核）。

    rows: [{"id": int, "content": str}, ...]
    返回 [{id_a, id_b, ratio, same_hash}]，ratio >= threshold 视为重复对。
    指纹相同（content_hash 一致）的直接记 same_hash=True，不再算编辑距离。
    """
    groups: dict[str, list[int]] = {}
    for r in rows:
        h = content_hash(r.get("content") or "")
        groups.setdefault(h, []).append(r["id"])

    pairs: list[dict] = []
    for h, ids in groups.items():
        if len(ids) > 1:
            for a in ids:
                for b in ids:
                    if a < b:
                        pairs.append({"id_a": a, "id_b": b, "ratio": 1.0, "same_hash": True})
    return pairs


def group_variants(rows: list[dict], threshold: float = 0.75) -> list[list[int]]:
    """相似题/变式题聚类：按题干编辑距离 >= threshold 聚成组（增量贪心）。

    指纹不同的题才做编辑距离比较，避免 O(n^2)。返回长度 >= 2 的组列表。
    """
    by_hash: dict[str, list[dict]] = {}
    for r in rows:
        h = content_hash(r.get("content") or "")
        by_hash.setdefault(h, []).append(r)

    by_id = {r["id"]: r for r in rows}
    clusters: list[list[int]] = []
    visited: set[int] = set()

    # 指纹完全相同的先成一组
    for h, lst in by_hash.items():
        if len(lst) >= 2:
            clusters.append([r["id"] for r in lst])
            for r in lst:
                visited.add(r["id"])

    # 贪心：未访问项与既有聚类代表比较
    for r in rows:
        if r["id"] in visited:
            continue
        merged = None
        for i, cl in enumerate(clusters):
            rep = by_id.get(cl[0], {}).get("content") or ""
            if similarity_ratio(r.get("content") or "", rep) >= threshold:
                merged = i
                break
        if merged is not None:
            clusters[merged].append(r["id"])
        else:
            clusters.append([r["id"]])
        visited.add(r["id"])

    return [c for c in clusters if len(c) >= 2]


# 多角色互校：答案解析生成提示词（答题者 / 考官 / 校对 三视角）
def generate_answer_prompt(question: dict) -> str:
    """为一道题构造多角色互校的答案解析生成提示词。

    question: {"content", "options"?, "question_type"?, "subject"?}
    约定输出 JSON：{"answer": "...", "analysis": "...", "confidence": 0~1}
    """
    qtype = question.get("question_type") or "single"
    type_name = {"single": "单选题", "multiple": "多选题", "judge": "判断题",
                 "fill": "填空题", "essay": "简答题/计算题", "calc": "计算题",
                 "draw": "作图题"}.get(qtype, "题目")
    lines = [
        "你是一名严谨的考研专业课（834 电子技术基础：数字电子技术/模拟电子技术）命题与教研专家。",
        "请对下面这道" + type_name + "给出正确答案与解析。",
        "",
        "【要求：多角色互校】",
        "1. 答题者视角：先独立作答并写出推理过程；",
        "2. 考官视角：按考纲与常考陷阱复核该答案是否完备、是否有更优解；",
        "3. 校对视角：检查表述是否严谨（符号、单位、条件前提），修正后给出最终版。",
        "仅输出最终 JSON，不要额外解释：",
        '{"answer": "最终答案", "analysis": "简明解析（含关键推理/公式/陷阱提醒）", "confidence": 0.0~1.0}',
        "",
        "【题目信息】",
        "科目：" + str(question.get("subject") or "未指定"),
        "题型：" + type_name,
        "题干：" + str(question.get("content") or ""),
    ]
    opts = question.get("options") or []
    if opts:
        lines.append("选项：" + "；".join(str(o) for o in opts))
    return "\n".join(lines)


def generate_variant_prompt(question: dict) -> str:
    """为一道题构造变式题生成提示词（换数据/换问法/换角度，保留考点）。"""
    qtype = question.get("question_type") or "single"
    type_name = {"single": "单选题", "multiple": "多选题", "judge": "判断题",
                 "fill": "填空题", "essay": "简答题/计算题", "calc": "计算题",
                 "draw": "作图题"}.get(qtype, "题目")
    lines = [
        "你是一名考研专业课命题专家。请基于下面这道题生成 1 道同考点的变式题：",
        "要求：保持考点与难度基本一致，但更换数据/参数、改变提问角度或情境；",
        "必须给出答案与解析。仅输出 JSON：",
        '{"content": "变式题题干", "options": ["A...", "B...", "C...", "D..."] 或 null, "answer": "答案", "analysis": "解析", "knowledge_point": "考点"}',
        "",
        "【原题·" + type_name + "】",
        "题干：" + str(question.get("content") or ""),
    ]
    opts = question.get("options") or []
    if opts:
        lines.append("原选项：" + "；".join(str(o) for o in opts))
    lines.append("原答案：" + str(question.get("answer") or ""))
    lines.append("原解析：" + str(question.get("analysis") or ""))
    return "\n".join(lines)
