# -*- coding: utf-8 -*-
"""源文件夹批量导入：题目 → quiz_questions（全库查重），知识点 → knowledge_points。

设计要点（对抗历史踩坑）：
1. 不依赖有漂移的 ORM（legacy models.py 缺 source_kind/validation_status 等真实列，
   且 quiz_dedupe.build_index_from_db 查 QuizQuestion.source 会报错）。
   → 复用 quiz_dedupe 的**纯函数** canonical_hash / canonical_text / FingerprintIndex，
     自己用原生 SQL 建全库指纹索引 + 原生 SQL 写入，精确匹配真实表结构。
2. 查重范围是**全库**（跨来源），不是单文档：先扫描现有 11000+ 题建索引，
   入库前精确 SHA-256 指纹命中 → 合并补齐（不丢弃）；未命中即新增。
   近似题不自动合并，避免把仅差数字或公式的不同题误并为一题。
3. 幂等：重复跑不会长重复（指纹索引每次重建自全库）。
4. 全程留痕：写 JSON 报告（每文件解析数、入库/合并/跳过、按科目统计、错误明细）。

用法：
  python scripts/ingest_source_folder.py --root "D:\\下载\\QQ\\压缩文件.zip\\压缩文件" --dry-run
  python scripts/ingest_source_folder.py --root "..." --limit 5            # 先小样本验证
  python scripts/ingest_source_folder.py --root "..." --report-out .temp/ingest_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict

# 让脚本能直接 `python scripts/xxx.py` 运行：把后端根加入 sys.path
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
# services 也加入，直接 import quiz_dedupe（避开 services/__init__ 的副作用）
_SERVICES_DIR = os.path.join(_BACKEND_ROOT, "services")
if _SERVICES_DIR not in sys.path:
    sys.path.insert(0, _SERVICES_DIR)

import quiz_dedupe  # noqa: E402  # 纯函数：canonical_hash / canonical_text / FingerprintIndex
from database import engine  # noqa: E402
from sqlalchemy import text  # noqa: E402

# --------------------------------------------------------------------------- #
# 题型段标题 → 标准 question_type
# --------------------------------------------------------------------------- #
_TYPE_MAP = [
    (r"单项选择|单选题|单选", "single"),
    (r"多项选择|多选题|多选", "multiple"),
    (r"选择题", "single"),  # 无更明确限定，先按单选；运行时按选项数可修正
    (r"判断题|判断", "judge"),
    (r"填空题|填空", "fill"),
    (r"计算题|计算", "calc"),
    (r"简答题|简答|问答题|问答|论述题|分析题", "essay"),
    (r"作图题|绘图", "draw"),
    (r"证明题", "proof"),
]
_TYPE_HEADING_RE = re.compile(r"^[一二三四五六七八九十]+[、.．]\s*(.+?)\s*$")

# --------------------------------------------------------------------------- #
# 行级模式
# --------------------------------------------------------------------------- #
RE_CHAPTER = re.compile(r"^第[一二三四五六七八九十百千零\d]+[章节编部篇]\s*(.*)$")
RE_QNUM = re.compile(r"^\s*(\d+)[．.、]\s*(.+)$")
RE_OPTION = re.compile(r"^\s*([A-F])[．.、]\s*(.+)$")
RE_OPT_INLINE = re.compile(r"([A-F])[．.、]")
RE_ANSWER = re.compile(r"【答案】\s*(.+?)(?:查看答案)?\s*$")
RE_ANSWER_ALT = re.compile(r"^参考答案?[:：]?\s*(.+?)(?:查看答案)?\s*$")
RE_ANALYSIS = re.compile(r"【解析】\s*(.+)$")
RE_SOLUTION = re.compile(r"^解[:：]\s*(.*)$")
RE_TOC_MARK = re.compile(r"^目\s*录$")
RE_EDITORIAL = re.compile(r"圣才学习网编辑部|圣才考研网|内容简介")
# 复习笔记子层级标题（用于知识点抽取）
RE_KP_L1 = re.compile(r"^[一二三四五六七八九十]+[、.．]\s*(.+)$")  # 一、xxx
RE_KP_L2 = re.compile(r"^\d+[．.、]\s*(.+)$")  # 1．xxx
RE_KP_L3 = re.compile(r"^（\d+）\s*(.+)$")  # （1）xxx
RE_SECTION_NUM = re.compile(r"^\d+\.\d+\s")  # 1.1 复习笔记
RE_VIEW_ANS = re.compile(r"查看答案\s*$")

# 文件名分类
NAME_HAS_QUESTIONS = re.compile(r"题库|习题|真题|题解|试题|考研真题|课后习题|习题集|错题")
NAME_IS_NOTES = re.compile(r"笔记|复习笔记|知识总结|提纲|讲义|复习要点|公式总结|概念公式")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


# --------------------------------------------------------------------------- #
# docx 文本抽取（保持段落与表格的正文顺序）
# --------------------------------------------------------------------------- #
def iter_docx_blocks(path):
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(path)
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            # 找到对应的 paragraph 对象取文本（避免裸 XML 命名空间拼接）
            txt = "".join(node.text or "" for node in child.iter(qn("w:t")))
            if txt.strip():
                yield txt.strip()
        elif tag == "tbl":
            # 表格：按行拼成 " | " 分隔
            for row in child.iter(qn("w:tr")):
                cells = []
                for cell in row.iter(qn("w:tc")):
                    parts = [t.text or "" for t in cell.iter(qn("w:t"))]
                    c = "".join(parts).strip()
                    if c:
                        cells.append(c)
                if cells:
                    yield " | ".join(cells)


# --------------------------------------------------------------------------- #
# 题目解析
# --------------------------------------------------------------------------- #
def _classify_type(heading_text: str) -> str | None:
    for pat, qt in _TYPE_MAP:
        if re.search(pat, heading_text):
            return qt
    return None


def parse_questions(lines, file_label: str):
    """从按行文本中切出题目。返回 list[dict]。

    策略：只在出现过「题型段标题」（一、填空题/选择题/…）之后才开始收集题目，
    以此跳过前言与目录；题型段标题靠关键词区分知识点标题（一、通信的基本概念）。
    """
    questions = []
    cur = None  # {stem_parts, options, answer, analysis, qtype, chapter, no}
    cur_chapter = None
    cur_type = None
    in_type_zone = False  # 已进入过题型段（开始收集）
    started = False  # 已越过前言/目录

    def flush():
        nonlocal cur
        if cur and cur.get("stem_parts"):
            questions.append(cur)
        cur = None

    def new_q(no, first_line):
        return {
            "no": no,
            "chapter": cur_chapter,
            "qtype": cur_type or "single",
            "stem_parts": [first_line] if first_line else [],
            "options": [],  # [(key, text)]
            "answer": None,
            "analysis": None,
            "_in_solution": False,
        }

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # 越过前言/目录：见到「目　录」后，直到再次出现题型段或章标题才视为正文开始
        if not started:
            if RE_TOC_MARK.match(line):
                started = True  # 目录之后开始正文判定
                continue
            if RE_EDITORIAL.search(line):
                continue
            # 目录项本身形如 "第1章 绪论"，在 started 前忽略
            continue

        # 章标题
        m_ch = RE_CHAPTER.match(line)
        if m_ch:
            # 章标题出现在目录里也可能命中；只在 in_type_zone 之后或作为正文更新
            if in_type_zone:
                flush()
            cur_chapter = _norm(m_ch.group(1)) or line
            cur_type = None
            continue

        # 题型段标题：一、填空题
        m_th = _TYPE_HEADING_RE.match(line)
        if m_th:
            qt = _classify_type(m_th.group(1))
            if qt:
                flush()
                cur_type = qt
                in_type_zone = True
                continue

        if not in_type_zone:
            continue  # 还没到题型段，跳过（目录/前言残余）

        # 新编号题：1．xxx
        m_q = RE_QNUM.match(line)
        if m_q:
            # 防止把选项里的数字当成新题（选项是 A-F 开头，不会走这里），
            # 也防止把解析里的 "1." 列表误判：仅当当前没有未完成题或当前题已有答案时开新题
            if cur is None or cur.get("answer") or cur.get("_in_solution"):
                flush()
                cur = new_q(m_q.group(1), _norm(m_q.group(2)))
                continue
            # 否则当作当前题的延续（解析中编号列表）

        # 无编号题（填空等）：当前题不存在且行不像选项/答案/解析 → 起一道题
        if (
            cur is None
            and not RE_OPTION.match(line)
            and not RE_ANSWER.match(line)
            and not RE_ANALYSIS.match(line)
            and not RE_SOLUTION.match(line)
            and not RE_KP_L1.match(line)
            and not RE_CHAPTER.match(line)
        ):
            cur = new_q(None, _norm(line))
            continue

        if cur is None:
            continue

        # 选项行：A．xxx
        m_opt = RE_OPTION.match(line)
        if m_opt and not cur.get("answer"):
            cur["options"].append((m_opt.group(1), _norm(m_opt.group(2))))
            continue

        # 答案：【答案】xxx
        m_ans = RE_ANSWER.search(line)
        if m_ans:
            cur["answer"] = _norm(m_ans.group(1))
            continue
        m_ans2 = RE_ANSWER_ALT.match(line)
        if m_ans2 and not cur.get("answer"):
            cur["answer"] = _norm(m_ans2.group(1))
            continue

        # 解析：【解析】xxx 或 解：xxx
        m_an = RE_ANALYSIS.search(line)
        if m_an:
            cur["analysis"] = _norm(m_an.group(1))
            cur["_in_solution"] = True
            continue
        m_sol = RE_SOLUTION.match(line)
        if m_sol and not cur.get("_in_solution"):
            rest = _norm(m_sol.group(1))
            cur["analysis"] = rest if rest else ""
            cur["_in_solution"] = True
            continue

        # 普通续行：题干 或 解析
        if cur.get("answer") is None and not cur["options"] and not cur.get("_in_solution"):
            # 还在题干区
            cur["stem_parts"].append(_norm(line))
        elif cur.get("_in_solution"):
            cur["analysis"] = (cur.get("analysis") or "") + "\n" + _norm(line)
        elif cur["options"]:
            # 选项后的续行（选项文本跨行）→ 并入最后一个选项
            if cur["options"]:
                k, t = cur["options"][-1]
                cur["options"][-1] = (k, t + " " + _norm(line))
            else:
                cur["stem_parts"].append(_norm(line))
        else:
            cur["stem_parts"].append(_norm(line))

    flush()

    # 后处理：组装 stem、规范化选项、修正题型
    out = []
    for q in questions:
        stem = _norm(" ".join(q["stem_parts"]))
        stem = RE_VIEW_ANS.sub("", stem).strip()
        if len(stem) < 4:
            continue
        # 行内选项抽取（题干同线带 A．x B．y 的情况）
        opts = list(q["options"])
        if not opts:
            opts = _extract_inline_options(stem)
            if opts:
                # 从 stem 里去掉选项段
                stem = _strip_inline_options(stem)
        qtype = q["qtype"]
        # 题型修正：有选项但 qtype 是 essay → 改 single
        if opts and qtype in ("essay", "calc", "fill"):
            qtype = "single"
        # 多选判定：答案含多个字母
        atype = "objective" if qtype in ("single", "multiple", "judge") else "subjective"
        if qtype == "single" and q.get("answer") and len(re.findall(r"[A-F]", q["answer"])) > 1:
            qtype = "multiple"
        out.append(
            {
                "stem": stem,
                "options": [{"key": k, "text": t} for k, t in opts] if opts else None,
                "answer": q.get("answer"),
                "analysis": (q.get("analysis") or "").strip() or None,
                "qtype": qtype,
                "atype": atype,
                "chapter": q.get("chapter"),
                "no": q.get("no"),
            }
        )
    return out


def _extract_inline_options(text):
    """从 '题干 A．x B．y C．z D．w' 里抽选项。"""
    matches = list(RE_OPT_INLINE.finditer(text))
    if len(matches) < 2:
        return []
    opts = []
    for i, m in enumerate(matches):
        key = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        seg = text[start:end].strip(" 　\t")
        # 去掉尾部 "【答案】" 之后
        seg = re.split(r"【答案】", seg)[0].strip()
        if seg:
            opts.append((key, _norm(seg)))
    return opts if len(opts) >= 2 else []


def _strip_inline_options(text):
    m = RE_OPT_INLINE.search(text)
    if not m:
        return text
    return text[: m.start()].strip()


# --------------------------------------------------------------------------- #
# 知识点抽取（仅复习笔记段）
# --------------------------------------------------------------------------- #
def parse_knowledge_points(lines, subject, subject_id):
    """从复习笔记段抽层级知识点。返回 list[dict]：{name, parent_name, chapter, desc}."""
    kps = []
    in_notes = False
    chapter = None
    # 栈：每层最近的标题名，用于 parent 推导
    stack = []  # [(level, name)]
    desc_buf = []
    current = None

    def push_desc():
        if current and desc_buf:
            current["desc"] = _norm(" ".join(desc_buf))[:1500]

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if RE_CHAPTER.match(line):
            m = RE_CHAPTER.match(line)
            push_desc()
            chapter = _norm(m.group(1)) or line
            in_notes = False
            stack = []
            current = None
            desc_buf = []
            continue
        if RE_SECTION_NUM.match(line):
            # 1.1 复习笔记 / 1.2 课后习题详解
            push_desc()
            in_notes = "复习笔记" in line
            stack = []
            current = None
            desc_buf = []
            continue
        if not in_notes:
            continue
        # 层级标题识别（优先级：L1 > L2 > L3）
        lvl = name = None
        m1 = RE_KP_L1.match(line)
        if m1 and len(line) < 60:
            lvl, name = 1, _norm(m1.group(1))
        if lvl is None:
            m2 = RE_KP_L2.match(line)
            if m2 and len(line) < 60:
                lvl, name = 2, _norm(m2.group(1))
        if lvl is None:
            m3 = RE_KP_L3.match(line)
            if m3 and len(line) < 60:
                lvl, name = 3, _norm(m3.group(1))
        if lvl is not None and name and 2 <= len(name) <= 80:
            push_desc()
            # 收缩栈到父层
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            parent = stack[-1][1] if stack else None
            current = {
                "name": name,
                "parent_name": parent,
                "chapter": chapter,
                "subject": subject,
                "subject_id": subject_id,
                "desc": None,
            }
            kps.append(current)
            stack.append((lvl, name))
            desc_buf = []
            continue
        # 普通正文 → 归入当前知识点描述
        if current:
            desc_buf.append(line)
    push_desc()
    return kps


# --------------------------------------------------------------------------- #
# 科目匹配
# --------------------------------------------------------------------------- #
SUBJECT_ALIASES = {
    "C程序设计": "C/C++语言",
    "C语言": "C/C++语言",
    "C++": "C/C++语言",
    "微机原理": "微机原理与接口技术",
    "微型计算机原理": "微机原理与接口技术",
    "单片机原理及接口技术": "单片机原理",
    "数字信号处理教程": "数字信号处理",
    "信号与线性系统": "信号与系统",
    "电子技术基础": "电子技术基础",
    "普通物理": "普通物理",
    "大学物理": "普通物理",
    "概率论与数理统计": "数学",
    "高等数学": "数学",
    "线性代数": "数学",
    "数学一": "数学",
    "数学二": "数学",
    "数学公式": "数学",
}


def load_subjects(conn):
    rows = conn.execute(text("SELECT id, name FROM subjects")).fetchall()
    by_name = {r[1]: r[0] for r in rows}
    names = sorted(by_name.keys(), key=len, reverse=True)
    return by_name, names


def match_subject(path: str, names, by_name):
    text = path.replace("\\", "/")
    for alias, canon in SUBJECT_ALIASES.items():
        if canon in by_name and alias in text:
            return canon, by_name[canon]
    for nm in names:
        if nm and nm in text:
            return nm, by_name[nm]
    # 兜底：从《》里取书名前几个字作为 subject 文本（不绑 subject_id）
    m = re.search(r"《([^》]{2,12})》", text)
    guess = m.group(1) if m else None
    return guess, None


def classify_file(name: str):
    has_q = bool(NAME_HAS_QUESTIONS.search(name))
    is_notes = bool(NAME_IS_NOTES.search(name))
    return has_q, is_notes


# --------------------------------------------------------------------------- #
# DB：建索引 / 写题 / 写知识点
# --------------------------------------------------------------------------- #
def build_dedup_index(conn):
    idx = quiz_dedupe.FingerprintIndex()
    res = conn.execute(text("SELECT id, content FROM quiz_questions WHERE content IS NOT NULL"))
    n = 0
    for qid, content in res:
        norm = quiz_dedupe.canonical_text(content or "")
        idx.add(quiz_dedupe.canonical_hash(content or ""), qid, "", text=norm)
        n += 1
    return idx, n


def _exec(conn, stmt, params):
    """Execute within a SAVEPOINT: a failing statement rolls back only itself,
    never poisoning the surrounding transaction (avoids InFailedSqlTransaction)."""
    with conn.begin_nested():
        return conn.execute(stmt, params)


def _sanitize_options(opts):
    """净化选项：去重、过滤非法；不足 2 项则返回 None。"""
    if not opts:
        return None
    seen = set()
    out = []
    for o in opts:
        k = (o.get("key") or "").strip().upper()
        t = (o.get("text") or "").strip()
        if len(k) != 1 or k not in "ABCDEF" or not t or k in seen:
            continue
        seen.add(k)
        out.append({"key": k, "text": t})
    return out if len(out) >= 2 else None


def write_question(conn, q, idx, subject, subject_id, source_label, qcat):
    stem = q["stem"]
    h = quiz_dedupe.canonical_hash(stem)
    norm = quiz_dedupe.canonical_text(stem)
    if len(norm) < quiz_dedupe.MIN_CANONICAL_LEN:
        return "too_short"
    clean_opts = _sanitize_options(q.get("options"))
    if q["qtype"] in ("single", "multiple") and not clean_opts:
        return "invalid_options"
    if not (q.get("answer") or "").strip():
        return "missing_answer"
    hit = idx.lookup(h)
    if hit is not None:
        qid = hit[0]
        if qid > 0:
            # 命中：补齐已有题的空字段（不覆盖），并把新来源并入 source_label
            try:
                _exec(
                    conn,
                    text(
                        "UPDATE quiz_questions SET "
                        "  answer = COALESCE(NULLIF(answer,''), :ans), "
                        "  analysis = COALESCE(NULLIF(analysis,''), :an), "
                        "  options = CASE WHEN (options IS NULL OR options = 'null'::jsonb) "
                        "                 AND :opts IS NOT NULL THEN CAST(:opts AS jsonb) ELSE options END, "
                        "  subject = COALESCE(NULLIF(subject,''), :subject), "
                        "  subject_id = COALESCE(subject_id, :subject_id), "
                        "  chapter = COALESCE(NULLIF(chapter,''), :chapter), "
                        "  source_label = CASE WHEN source_label IS NULL OR source_label = '' THEN :sl "
                        "                 WHEN POSITION(:sl2 IN source_label) = 0 THEN source_label || ' | ' || :sl3 "
                        "                 ELSE source_label END "
                        "WHERE id = :id"
                    ),
                    {
                        "ans": q.get("answer"),
                        "an": q.get("analysis"),
                        "opts": json.dumps(clean_opts, ensure_ascii=False) if clean_opts else None,
                        "subject": subject,
                        "subject_id": subject_id,
                        "chapter": (q.get("chapter") or None) and (q["chapter"][:200]),
                        "sl": source_label[:200],
                        "sl2": source_label[:200],
                        "sl3": source_label[:200],
                        "id": qid,
                    },
                )
            except Exception as e:  # noqa: BLE001
                return f"error_merge:{type(e).__name__}:{str(e)[:120]}"
        return "merged"
    # 新增
    opts_json = json.dumps(clean_opts, ensure_ascii=False) if clean_opts else None
    params = {
        "content": stem,
        "options": opts_json,
        "answer": q.get("answer"),
        "analysis": q.get("analysis"),
        "qtype": q["qtype"],
        "atype": q["atype"],
        "diff": 3,
        "skind": "external_import",
        "slabel": source_label[:200],
        "subject": subject,
        "subject_id": subject_id,
        "chapter": (q.get("chapter") or None) and (q["chapter"][:200]),
        "kp": None,
        "qcat": qcat,
        "conf": "medium",
    }
    sql = (
        "INSERT INTO quiz_questions "
        "(content, options, answer, analysis, question_type, answer_type, difficulty, "
        " source_kind, source_label, subject, subject_id, chapter, knowledge_point, "
        " question_category, confidence, is_available, is_junk, validation_status) "
        "VALUES (:content, CAST(:options AS jsonb), :answer, :analysis, :qtype, :atype, :diff, "
        " :skind, :slabel, :subject, :subject_id, :chapter, :kp, "
        " :qcat, :conf, true, false, 'pending') "
        "RETURNING id"
    )
    try:
        new_id = _exec(conn, text(sql), params).scalar()
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}:{str(e)[:120]}"
    idx.add(h, new_id, "", text=norm)
    return "inserted"


def _kp_norm(name):
    """归一化知识点名用于去重匹配：仅压空白与去首尾空白（不剥离编号，避免过度合并）。"""
    return re.sub(r"\s+", " ", (name or "")).strip()


def _kp_key(subject_text, name):
    """去重键用 subject 文本（而非 subject_id），兼容历史 subject_id 为 NULL 的行。"""
    return ((subject_text or "").strip(), _kp_norm(name))


def load_existing_kps(conn):
    res = conn.execute(text("SELECT id, name, subject FROM knowledge_points WHERE name IS NOT NULL"))
    out = {}
    for r in res:
        out.setdefault(_kp_key(r[2], r[1]), r[0])  # 首次出现优先（最旧的规范行）
    return out


def write_knowledge_points(conn, kps, existing, subject_id):
    """先插入（parent_id 空）拿 id，再回填 parent_id。返回 (inserted, exists)。"""
    name_to_id = dict(existing)  # _kp_key(subject, name) -> id
    inserted = 0
    exists = 0
    errors = 0
    # 第一遍：插入
    for kp in kps:
        sid = kp.get("subject_id") or subject_id
        key = _kp_key(kp.get("subject"), kp["name"])
        if key in name_to_id:
            exists += 1
            continue
        try:
            new_id = _exec(
                conn,
                text(
                    "INSERT INTO knowledge_points "
                    "(name, subject, subject_id, chapter, description, extract_source, difficulty) "
                    "VALUES (:name, :subject, :sid, :chapter, :desc, 'batch', 3) RETURNING id"
                ),
                {
                    "name": kp["name"][:300],
                    "subject": kp.get("subject"),
                    "sid": sid,
                    "chapter": (kp.get("chapter") or None) and kp["chapter"][:200],
                    "desc": kp.get("desc"),
                },
            ).scalar()
            name_to_id[key] = new_id
            existing[key] = new_id
            inserted += 1
        except Exception:  # noqa: BLE001
            errors += 1
    # 第二遍：回填 parent_id
    for kp in kps:
        sid = kp.get("subject_id") or subject_id
        key = _kp_key(kp.get("subject"), kp["name"])
        if key not in name_to_id or not kp.get("parent_name"):
            continue
        pkey = _kp_key(kp.get("subject"), kp.get("parent_name"))
        if pkey in name_to_id and name_to_id[pkey] != name_to_id[key]:
            try:
                _exec(
                    conn,
                    text("UPDATE knowledge_points SET parent_id = :pid WHERE id = :id"),
                    {"pid": name_to_id[pkey], "id": name_to_id[key]},
                )
            except Exception:  # noqa: BLE001
                errors += 1
    return inserted, exists, errors


# --------------------------------------------------------------------------- #
# PDF 文本抽取（优先文本层，失败才尝试项目 parser）
# --------------------------------------------------------------------------- #
def extract_pdf_text(path):
    # 优先 PyMuPDF（文字版 PDF 极快）
    try:
        import fitz  # PyMuPDF
    except Exception:
        fitz = None
    if fitz is not None:
        try:
            doc = fitz.open(path)
            parts = []
            for page in doc:
                parts.append(page.get_text("text"))
            doc.close()
            text = "\n".join(parts)
            if len(text.strip()) > 200:
                return text.splitlines()
        except Exception:  # noqa: BLE001
            pass
    # 退回项目 document_parser（含 OCR 兜底）
    try:
        from document_parser import parse_document_to_text

        text = parse_document_to_text(path)
        return text.splitlines() if text else []
    except Exception:  # noqa: BLE001
        return []


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def collect_files(root, only_ext=""):
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in (".docx", ".pdf", ".doc"):
                continue
            if only_ext and ext != only_ext.lower():
                continue
            out.append(os.path.join(dirpath, f))
    return sorted(out)


def run(args):
    root = os.path.abspath(args.root)
    files = collect_files(root, args.ext)
    if args.limit:
        files = files[: args.limit]
    print(f"[scan] root={root}  files={len(files)}")

    report = {
        "root": root,
        "files_total": len(files),
        "dry_run": args.dry_run,
        "per_file": [],
        "totals": defaultdict(int),
        "by_subject": defaultdict(lambda: defaultdict(int)),
        "errors": [],
    }

    if args.dry_run:
        # dry-run：只解析不写库，不需要 DB 连接
        conn = None
        idx = None
    else:
        conn = engine.connect()
        idx, idx_n = build_dedup_index(conn)
        print(f"[dedup] built fingerprint index from {idx_n} existing questions")
        report["dedup_index_size"] = idx_n
        by_name, subj_names = load_subjects(conn)
        existing_kps = load_existing_kps(conn)
        report["existing_kps"] = len(existing_kps)

    t0 = time.time()
    for i, path in enumerate(files, 1):
        name = os.path.basename(path)
        rel = os.path.relpath(path, root)
        ext = os.path.splitext(path)[1].lower()
        frec = {
            "file": rel,
            "ext": ext,
            "questions_parsed": 0,
            "kps_parsed": 0,
            "inserted": 0,
            "merged": 0,
            "skipped": 0,
            "kp_inserted": 0,
            "subject": None,
            "error": None,
            "first_error": None,
            "sample": [],
        }
        try:
            if ext == ".docx":
                lines = list(iter_docx_blocks(path))
            elif ext == ".pdf":
                lines = extract_pdf_text(path)
            else:  # .doc 旧格式，python-docx 不支持，跳过（可后续用外部工具）
                frec["error"] = "skip_legacy_doc"
                report["per_file"].append(frec)
                continue
            if not lines:
                frec["error"] = "no_text_extracted"
                report["per_file"].append(frec)
                continue

            has_q, is_notes = classify_file(name)
            # 教材 PDF 无"题库/习题"字样 → 不抽题，只抽知识点（若 --kp）
            do_questions = has_q or is_notes
            subject = subject_id = None
            if not args.dry_run:
                subject, subject_id = match_subject(rel, subj_names, by_name)
            frec["subject"] = subject
            qcat = "真题" if "真题" in name else ("习题" if ("习题" in name or "题库" in name) else "练习题")

            qs = parse_questions(lines, name) if do_questions else []
            frec["questions_parsed"] = len(qs)
            if qs:
                frec["sample"] = [qs[0]["stem"][:80]] + ([qs[-1]["stem"][:80]] if len(qs) > 1 else [])
            kps = []
            if args.kp and (is_notes or ext == ".pdf"):
                kps = parse_knowledge_points(lines, subject, subject_id)
                frec["kps_parsed"] = len(kps)

            if args.dry_run:
                report["totals"]["questions_parsed"] += len(qs)
                report["totals"]["kps_parsed"] += len(kps)
            else:
                sub_key = subject or "(未匹配)"
                write_errors = 0
                for q in qs:
                    act = write_question(conn, q, idx, subject, subject_id, name, qcat)
                    if act == "inserted":
                        frec["inserted"] += 1
                        report["by_subject"][sub_key]["inserted"] += 1
                    elif act == "merged":
                        frec["merged"] += 1
                        report["by_subject"][sub_key]["merged"] += 1
                    else:
                        frec["skipped"] += 1
                        report["by_subject"][sub_key]["skipped"] += 1
                        if act.startswith("error"):
                            write_errors += 1
                            if not frec.get("first_error"):
                                frec["first_error"] = act[:200]
                if kps:
                    ki, ke, kerr = write_knowledge_points(conn, kps, existing_kps, subject_id)
                    frec["kp_inserted"] = ki
                    report["by_subject"][sub_key]["kp_inserted"] += ki
                    report["totals"]["kp_inserted"] += ki
                    report["totals"]["kp_exists"] += ke
                    report["totals"]["kp_errors"] += kerr
                if write_errors or kerr:
                    frec["error"] = f"write_errors:{write_errors + kerr}"
                    report["errors"].append({"file": rel, "error": frec["error"]})
                else:
                    report["totals"]["files_done"] += 1
                conn.commit()
        except Exception as e:  # noqa: BLE001
            frec["error"] = f"{type(e).__name__}:{str(e)[:160]}"
            report["errors"].append({"file": rel, "error": frec["error"]})
            if not args.dry_run:
                conn.rollback()
        report["per_file"].append(frec)
        # 进度
        if i % 10 == 0 or i == len(files):
            print(
                f"[{i}/{len(files)}] {rel[:60]} parsed_q={frec['questions_parsed']} "
                f"ins={frec['inserted']} merged={frec['merged']} skip={frec['skipped']} "
                f"kp={frec['kp_inserted']} err={frec['error']}"
            )

    if not args.dry_run:
        conn.commit()
        conn.close()

    # 汇总
    report["totals"]["inserted"] = sum(f["inserted"] for f in report["per_file"])
    report["totals"]["merged"] = sum(f["merged"] for f in report["per_file"])
    report["totals"]["skipped"] = sum(f["skipped"] for f in report["per_file"])
    report["totals"]["questions_parsed"] = sum(f["questions_parsed"] for f in report["per_file"])
    report["totals"]["kps_parsed"] = sum(f["kps_parsed"] for f in report["per_file"])
    report["elapsed_sec"] = round(time.time() - t0, 1)
    report["by_subject"] = {k: dict(v) for k, v in report["by_subject"].items()}

    if args.report_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.report_out)), exist_ok=True)
        with open(args.report_out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[report] written to {args.report_out}")

    print("\n=== SUMMARY ===")
    print(json.dumps({k: v for k, v in report["totals"].items()}, ensure_ascii=False, indent=2))
    print("by_subject:", json.dumps(report["by_subject"], ensure_ascii=False))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--dry-run", action="store_true", help="只解析统计，不写库")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--kp", action="store_true", help="同时抽取知识点入知识地图")
    ap.add_argument("--report-out", default="")
    ap.add_argument("--ext", default="", help="只处理指定扩展名，如 .docx")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
