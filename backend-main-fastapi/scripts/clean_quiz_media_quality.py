# -*- coding: utf-8 -*-
"""题库「媒体质量」第二轮清洗（docx/22 §3.2 ⑤⑥ + E2/E3）。

覆盖四件事（deterministic、幂等、可重跑）：

⑥ 题面 / 选项水印清洗
    quiz_questions.content 与 options 里混入的水印碎片（"微信：xxx"、"公众号"、
    "QQ群"、手机号、"第X页(OCR)"、"淘宝店"、文库站名、"东坡哥"、"水木观畴/珞研"、
    "电子通信考研"、"你身边的考研专家"、"小红书"…）。复用
    ``clean_document_watermarks.py`` 同族规则（同一套正则 + 同一删行阈值），
    并针对题库 OCR 残留补充一批实测变体：
      * 纯水印行整行丢；混合行只删水印片段、保留正文；
      * 清洗后实义字符 < 4 的**整题** → ``is_junk=1``（水印占了全部）。

E2 题图质量（题库无图片存储 → 识别图缺失）
    quiz_questions 表**没有** image 字段、库中也**没有**题目图片表（本脚本会
    现场探测佐证）。因此题图质量问题落到「题干引用了图/表，但库里没有任何
    图片存储」这一类。命中者标记 ``figure_missing=1``（**新增附加列**，见下）。

    ⚠️ 为什么不用 quality 字段：真库里 ``quality`` 已被 A/B/C 分级
    （A=人工校验 / B=AI 生成未校验 / C=仅浏览不可刷）+ 'incomplete' 占用，
    ``services/kaoyan/supplement_answers.py`` 等代码依赖该语义；把
    'missing_image' 写进 quality 会**覆盖并毁掉分级**。故本轮新增一个
    **可空附加列** ``figure_missing INTEGER NOT NULL DEFAULT 0``（附录式、
    向后兼容：ORM 未声明该列时自动忽略，写入不受影响），只置位不删题。

E3 空题
    content 清洗后为空或仅剩符号（实义字符 = 0）→ ``quality='incomplete'`` 且
    ``is_available=0``（标记不可作答，不删除）。

⑤ 真题卷补选项
    针对 ``subject='真题综合'`` 中无选项的题，尝试从 content 里解析 A/B/C/D
    选项写回 ``options``；**解析不出就跳过，绝不瞎猜**，并产出「待人工处理清单」。

安全红线
--------
* dry-run 默认开，必须显式 ``--apply`` 才写库。
* ``--apply`` 前强制调用 ``services/backup_service.py::create_backup()``
  （内部走 SQLite ``backup()`` API，禁 cp / copy2）。
* **不做任何物理删除**（只置位/标记），故无需 delete_guard 放行。
* 只写 quiz_questions 表，且只写有命中的行。

用法
----
    python scripts/clean_quiz_media_quality.py                  # dry-run（默认）
    python scripts/clean_quiz_media_quality.py --show-samples 8
    python scripts/clean_quiz_media_quality.py --report-json ../docx/24-quiz-media.json
    python scripts/clean_quiz_media_quality.py --apply          # 真清洗（自动先备份）
    python scripts/clean_quiz_media_quality.py --selftest       # 只跑判据自检
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.clean_document_watermarks import (  # noqa: E402  （复用同族规则）
    _SPAN_PATTERNS,
    _URL_RE,
    _FAST_MARKERS as _BASE_FAST_MARKERS,
)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

# 无选项判定（与 clean_quiz_quality.py / quiz_health_check.py 同口径）
NO_OPT_SQL = "(options IS NULL OR TRIM(options)='' OR options='[]' OR options='null')"

#: 识别图缺失判定（与 quiz_health_check.py 的 C7 同源）
_FIGURE_REF_RE = re.compile(
    r"如下\s*图|如图|图中|见图|如图所示|所示|【图|图\s*\d|图[a-zA-Z]|[（(]\s*图"
)

#: 优先规则（最先执行）。分两类，都必须抢在基础规则之前：
#:  1) 页眉页脚页码。否则基础规则里的 ``公众号\s*[:：]\s*[\w\u4e00-\u9fff]{0,20}``
#:     会把紧随其后的 "第" 当成公众号名吃掉，导致 "第 6 页" 只剩 "6 页"。
#:  2) 引流「启动词」。只吃 ``微信公众号 / 微信号 / 公众号`` 这几个启动符，
#:     后面跟的**品牌名交给品牌规则**去删；否则基础规则的贪婪
#:     ``[\u4e00-\u9fff]{0,20}`` 会把品牌名后**紧邻的正文首字**（如 "二、填空题"
#:     的 "二"）一起吃掉，污染正文。
_PRIORITY_SPAN_PATTERNS: tuple[str, ...] = (
    r"-{2,}\s*第\s*\d+\s*页\s*[（(]?\s*OCR\s*[)）]?\s*-{2,}",
    r"第\s*\d+\s*页\s*[（(]?\s*OCR\s*[)）]?",
    r"第\s*\d+\s*页",
    r"微信公众号\s*[&＆]?\s*B?\s*站?\s*[:：]?\s*",
    r"微信号?\s*[:：]?\s*",
    r"公众号\s*[&＆]?\s*B?\s*站?\s*[:：]?\s*",
)

# --------------------------------------------------------------------------- #
# 题库专属品牌 / 号码补充规则（真库实测变体枚举）
# --------------------------------------------------------------------------- #
_EXTRA_SPAN_PATTERNS: tuple[str, ...] = (
    # —— 品牌家族实测变体（水木观畴 / 水木珞研 / 水木现听 / 水木洛研…）——
    #    统一收尾吃掉紧邻的标点，避免删掉品牌后留下孤立逗号 "，"
    r"水木(?:珞|洛|路|观|现|時|时)(?:研|畴|听|呀)?[，,、！!]?",
    r"观畴考研[，,、]?",
    r"电子与通信工程考研[，,、！!]?",
    r"电子通信考研[，,、！!]?",
    r"(?:子)?与通信工程[，,、！!]?",       # 被分页截断的 "…与通信工程" 残片
    r"你身边的考研专家[！!，,。]?",
    r"东坡哥[，,、]?",
    r"haidongpo\d*",
    r"亮亮学长\s*(?:QQ)?\s*[:：]?\s*\d*",
    r"考研交流区\s*[:：]?\s*\d*",
    r"小红书号?\s*[:：]?\s*\d*",
    r"[Qq]{2}\s*获取\s*联系方式[?？]?",
    r"获取\s*联系方式",
    r"(?i)[Ss][Ee][Cc]{2}[Oo][Ee]?[Dd][Uu][Cc][Aa][Tt][Ii][Oo][Nn]",  # SECCOEDUCATION
    # 品牌名被删后残留的 "【…解题】" 抬头（如 "【 解题】"）
    r"【\s*[^\】】]{0,10}解\s*题\s*】",
    # —— 手机号（仅在含水印标记的行上生效，见 prefilter）——
    r"(?<!\d)1[3-9]\d{9}(?!\d)",
)

_SPAN_RES: tuple[re.Pattern, ...] = tuple(
    re.compile(p)
    for p in (_PRIORITY_SPAN_PATTERNS + _EXTRA_SPAN_PATTERNS + _SPAN_PATTERNS)
)

#: 行内快速预筛标记（含题库实测变体；不含裸数字，避免误伤数理正文）。
_FAST_MARKERS: frozenset[str] = frozenset(_BASE_FAST_MARKERS) | {
    "水木", "电子通信考研", "东坡哥", "亮亮", "交流区", "小红书",
    "OCR", "页", "SECCO", "你身边的考研专家", "B站",
}

#: 整行丢弃阈值：抹掉水印后，实义字符少于该值即视为纯水印行。
_MIN_MEANINGFUL = 4


def meaningful_count(s: str) -> int:
    """实义字符计数（Unicode 字母 / 数字）。

    比 ``clean_document_watermarks._meaningful_count`` 更宽：后者只认
    ASCII 字母数字 + 中日韩汉字，会把全角数字（１１）、数学斜体（𝑌）、希腊
    字母（α）等**真·正文**误判成空，从而把正常数理题 wash 成 junk/空题。
    这里改用 ``unicodedata`` 分类（L=字母 / N=数字），覆盖全角与数学字母。
    """
    return sum(1 for ch in s if unicodedata.category(ch)[0] in ("L", "N"))


#: 水印删除后常留下一枚孤立分隔符（如品牌名后的 "，"/"、"）。仅清理
#: **前后是空白或行首尾**的孤立分隔符，绝不动正文内相邻的标点。
_ORPHAN_PUNCT_RE = re.compile(r"(?:(?<=\s)|^)[，,、；;](?=\s|$)")


def _tidy(t: str) -> str:
    t = _ORPHAN_PUNCT_RE.sub(" ", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def clean_line(line: str) -> tuple[str | None, bool]:
    """清洗单行水印。

    Returns:
        (新行 or None 表示整行丢弃, 是否发生过水印移除)
    """
    if not any(m in line for m in _FAST_MARKERS):
        return line, False
    t = line
    touched = False
    for rx in _SPAN_RES:
        new = rx.sub(" ", t)
        if new != t:
            touched = True
            t = new
    if _URL_RE.search(t):
        stripped = _URL_RE.sub(" ", t)
        if meaningful_count(stripped) < _MIN_MEANINGFUL:
            touched = True
            t = stripped
    t = _tidy(t)
    if not touched:
        return line, False
    if meaningful_count(t) < _MIN_MEANINGFUL:
        return None, True
    return t, True


def clean_text(text: str | None) -> tuple[str, int, int]:
    """清洗整段题面/选项文本。

    Returns:
        (清洗后文本, 被丢弃的纯水印行数, 被移除水印片段的混合行数)
    """
    if not text:
        return text or "", 0, 0
    kept: list[str] = []
    dropped = 0
    mixed = 0
    for line in text.split("\n"):
        if not line.strip():
            kept.append(line)
            continue
        new, touched = clean_line(line)
        if new is None:
            dropped += 1
            continue
        if touched:
            mixed += 1
        kept.append(new)
    if dropped == 0 and mixed == 0:
        return text, 0, 0
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, dropped, mixed


_OPT_LABEL_RE = re.compile(r"^\s*([A-Za-z])\s*[\.\、\．\)）]?")


def clean_option_element(el: Any) -> tuple[str, bool]:
    """清洗单个选项元素。

    与题面不同：**绝不删除元素**（删了会破坏 A/B/C/D 结构）；仅抹掉水印片段，
    清洗后若只剩空壳则回退到原选项字母标签（如 ``"D."``），保留槽位。
    """
    if not isinstance(el, str):
        return str(el), False
    if not any(m in el for m in _FAST_MARKERS):
        return el, False
    t = el
    touched = False
    for rx in _SPAN_RES:
        new = rx.sub(" ", t)
        if new != t:
            touched = True
            t = new
    if _URL_RE.search(t):
        s = _URL_RE.sub(" ", t)
        if meaningful_count(s) < _MIN_MEANINGFUL:
            touched = True
            t = s
    t = _tidy(t)
    if not touched:
        return el, False
    if meaningful_count(t) < 1:
        m = _OPT_LABEL_RE.match(el)
        t = m.group(1) if m else ""
    return t, True


# --------------------------------------------------------------------------- #
# ⑤ 从题面解析 A/B/C/D 选项（保守：四标签齐全且有序、每段非空，否则放弃）
# --------------------------------------------------------------------------- #
_ABCD_DELIM_RE = re.compile(r"(?<![A-Za-z0-9])([ABCD])\s*[\.\、\．\)）]\s*")


def parse_abcd_options(content: str | None) -> list[str] | None:
    """从题面解析出 4 个选项；解析不出返回 None（绝不瞎猜）。"""
    if not content:
        return None
    found: dict[str, re.Match] = {}
    for m in _ABCD_DELIM_RE.finditer(content):
        lab = m.group(1)
        if lab not in found:
            found[lab] = m
    if set(found) != set("ABCD"):
        return None
    pos = [found[lab].start() for lab in "ABCD"]
    if pos != sorted(pos):
        return None
    if pos[3] - pos[0] > 2000:            # 跨度太大 → 大概率是正文里的字母，非选项
        return None
    opts: list[str] = []
    for idx, lab in enumerate("ABCD"):
        start = found[lab].end()
        end = found["ABCD"[idx + 1]].start() if idx < 3 else len(content)
        body = content[start:end].strip()
        if meaningful_count(body) < 1:
            return None
        opts.append(f"{lab}.{body}")
    return opts


# --------------------------------------------------------------------------- #
# 备份（唯一正确方式：backup_service.create_backup → SQLite backup API）
# --------------------------------------------------------------------------- #
def _do_backup(db_path: str) -> str:
    from services.backup_service import DB_PATH as _REAL_DB, create_backup  # noqa

    if os.path.abspath(db_path) != os.path.abspath(_REAL_DB):
        raise RuntimeError(
            f"拒绝对非真库执行备份/写入：--db={db_path} != 真库 {_REAL_DB}"
        )
    return create_backup()


# --------------------------------------------------------------------------- #
# 扫描与计划
# --------------------------------------------------------------------------- #
def _image_storage_evidence(conn: sqlite3.Connection) -> dict[str, Any]:
    """探测题库是否存在任何题目图片存储（佐证 E2 的判定）。"""
    img_cols: list[str] = []
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        try:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
        except sqlite3.Error:
            continue
        if name == "quiz_questions":
            img_cols += [c for c in cols if any(k in c.lower() for k in ("img", "image", "figure", "pic"))]
    img_tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "(name LIKE '%image%' OR name LIKE '%img%' OR name LIKE '%figure%')"
        )
    ]
    return {"quiz_image_columns": img_cols, "image_tables": img_tables}


def plan(conn: sqlite3.Connection) -> dict[str, Any]:
    """扫描全表，产出待改清单（只读，不写库）。"""
    content_changes: list[tuple[int, str]] = []        # (id, new_content)
    options_changes: list[tuple[int, str]] = []        # (id, new_options_json)
    junk_ids: list[int] = []                           # ⑥ 水印占满 → is_junk=1
    incomplete_ids: list[int] = []                     # E3 清洗后为空 → incomplete
    figure_ids: list[int] = []                         # E2 引用图但无图存储
    option_filled: list[tuple[int, str, list[str]]] = []   # ⑤ 解析成功
    option_manual: list[dict[str, Any]] = []               # ⑤ 待人工

    for qid, content, options, subject, qtype, source, is_junk in conn.execute(
        "SELECT id, content, options, subject, question_type, source, is_junk FROM quiz_questions"
    ):
        # ⑥ 题面水印
        new_c, _d, _mx = clean_text(content or "")
        if new_c != (content or ""):
            content_changes.append((qid, new_c))
            if meaningful_count(new_c) < _MIN_MEANINGFUL:
                junk_ids.append(qid)

        # ⑥ 选项水印
        if options is not None and str(options).strip() not in ("", "null"):
            try:
                arr = json.loads(options)
            except (ValueError, TypeError):
                arr = None
            if isinstance(arr, list):
                new_arr: list[str] = []
                touched = False
                for el in arr:
                    ne, ch = clean_option_element(el)
                    if ch:
                        touched = True
                    new_arr.append(ne)
                if touched:
                    options_changes.append((qid, json.dumps(new_arr, ensure_ascii=False)))

        # E3 空题（清洗后实义字符 = 0）
        if meaningful_count(new_c) == 0:
            incomplete_ids.append(qid)

        # E2 识别图缺失（判定与 quiz_health_check C7 同源；junk 题无需再置位）
        if not is_junk and _FIGURE_REF_RE.search(content or ""):
            figure_ids.append(qid)

        # ⑤ 真题综合补选项
        if subject == "真题综合" and (
            options is None or str(options).strip() in ("", "null", "[]")
        ):
            parsed = parse_abcd_options(content or "")
            if parsed:
                option_filled.append((qid, json.dumps(parsed, ensure_ascii=False), parsed))
            else:
                option_manual.append({
                    "id": qid, "question_type": qtype, "source": source,
                    "content_head": (content or "")[:120],
                })

    return {
        "content_changes": content_changes,
        "options_changes": options_changes,
        "junk_ids": junk_ids,
        "incomplete_ids": incomplete_ids,
        "figure_ids": figure_ids,
        "option_filled": option_filled,
        "option_manual": option_manual,
        "image_evidence": _image_storage_evidence(conn),
    }


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        try:
            return conn.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return -1

    wm = (
        "content LIKE '%微信%' OR content LIKE '%公众号%' OR content LIKE '%东坡哥%' "
        "OR content LIKE '%水木%' OR content LIKE '%haidongpo%' OR content LIKE '%QQ%' "
        "OR content LIKE '%qq%' OR content LIKE '%OCR%' OR content LIKE '%电子通信考研%' "
        "OR content LIKE '%你身边的考研专家%'"
    )
    return {
        "total": one("SELECT COUNT(*) FROM quiz_questions"),
        "junk": one("SELECT COUNT(*) FROM quiz_questions WHERE is_junk=1"),
        "content_wm": one(f"SELECT COUNT(*) FROM quiz_questions WHERE {wm}"),
        "options_null": one(f"SELECT COUNT(*) FROM quiz_questions WHERE {NO_OPT_SQL}"),
        "quality_incomplete": one("SELECT COUNT(*) FROM quiz_questions WHERE quality='incomplete'"),
        "figure_missing": one("SELECT COUNT(*) FROM quiz_questions WHERE figure_missing=1"),
    }


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def selftest() -> int:
    cases: list[tuple[str, str, str]] = [
        ("纯水印题面", "东坡哥微信:haidongpo3", "drop"),
        ("纯公众号题面", "微信公众号:电子与通信工程考研", "drop"),
        ("水木珞研解题", "【水木珞研解题】", "drop"),
        ("截断微信公", "微信公", "drop"),
        ("页码OCR", "--- 第7页(OCR) ---", "drop"),
        ("小红书号", "小红书 小红书号：4152858007", "drop"),
        ("混合：水印+正文", "观畴考研，你身边的考研专家东坡哥微信:haidongpo3QQ:3428047568水木观畴月考-数字电路2023年5月满分：150", "keep"),
        ("混合：选项尾巴带水印", "D.放大区 观畴考研，你身边的考研专家 东坡哥微信:haidongpo3 QQ:3428047568", "keep"),
        ("正常题目", "8位DAC转换器，数字01000001转换后的电压值为（ ）V。A.0.05 B.0.10", "keep"),
        ("数理正文含第X章", "分析第2章课后习题，写出Y1、Y2的逻辑函数式并化简。", "keep"),
        ("全角数理（不得判空）", "（１１．００１）２＝（３．１２５）１０", "keep"),
    ]
    print("=" * 64)
    print("SELFTEST：题库水印清洗判据（防误杀优先）")
    print("=" * 64)
    failed = 0
    for desc, text, expect in cases:
        new, _d, _m = clean_text(text)
        got = "drop" if (not new or meaningful_count(new) < _MIN_MEANINGFUL) else "keep"
        ok = got == expect
        mark = "✓" if ok else "✗ FAIL"
        print(f"  [{mark}] {desc}  期望={expect} 实际={got}")
        print(f"         → {new[:64]!r}")
        if not ok:
            failed += 1

    # 选项元素：绝不删除、保留字母槽位
    opt_cases: list[tuple[str, str]] = [
        ("D.放大区 观畴考研 东坡哥微信:haidongpo3 QQ:3428047568", "D.放大区"),
        ("D. 东坡哥微信:haidongpo8 微信公众号:水木观畴", "D."),
        ("A.截止区", "A.截止区"),
    ]
    print("  ——— 选项元素清洗（不得删元素）———")
    for src, expect in opt_cases:
        out, ch = clean_option_element(src)
        ok = out == expect
        mark = "✓" if ok else "✗ FAIL"
        print(f"  [{mark}] {src[:40]!r} → {out!r} (期望 {expect!r})")
        if not ok:
            failed += 1

    # 选项解析器
    print("  ——— ⑤ 选项解析器 ———")
    ok_case = "关于X，下列说法： A.甲 B.乙 C.丙 D.丁"
    bad_case = "条件充分性判断： (1) 已知A (2) 已知B"
    p1 = parse_abcd_options(ok_case)
    p2 = parse_abcd_options(bad_case)
    c1 = p1 == ["A.甲", "B.乙", "C.丙", "D.丁"]
    c2 = p2 is None
    print(f"  [{'✓' if c1 else '✗ FAIL'}] 可解析 → {p1}")
    print(f"  [{'✓' if c2 else '✗ FAIL'}] 不可解析应返回 None → {p2}")
    failed += (0 if c1 else 1) + (0 if c2 else 1)

    print(f"\n  通过 {len(cases) + len(opt_cases) + 2 - failed} / {len(cases) + len(opt_cases) + 2}"
          f" → " + ("PASS" if failed == 0 else f"FAIL ({failed})"))
    return 0 if failed == 0 else 1


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="题库媒体质量清洗（dry-run 默认）")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--apply", action="store_true", help="真正写库（自动先备份）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--show-samples", type=int, default=6)
    ap.add_argument("--report-json", default=None, help="把结构化结果写入该 JSON 路径")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if not os.path.isfile(args.db):
        print(f"数据库不存在: {args.db}")
        return 1

    conn = sqlite3.connect(args.db)
    try:
        before = stats(conn)
        p = plan(conn)

        print("=" * 78)
        print("题库媒体质量清洗" + ("（DRY-RUN，不写库）" if not args.apply else "（APPLY）"))
        print("=" * 78)
        print("  清理前：")
        for k, v in before.items():
            print(f"    {k:<22} {v}")
        print()
        print(f"  ⑥ 题面水印命中     = {len(p['content_changes'])} 行"
              f"（其中清洗后成 junk 的整题 = {len(p['junk_ids'])}）")
        print(f"  ⑥ 选项水印命中     = {len(p['options_changes'])} 行")
        print(f"  E2 识别图缺失      = {len(p['figure_ids'])} 行"
              f"（题库图片列 {p['image_evidence']['quiz_image_columns'] or '无'}"
              f" / 图片表 {p['image_evidence']['image_tables'] or '无'}）")
        print(f"  E3 空题            = {len(p['incomplete_ids'])} 行")
        print(f"  ⑤ 真题综合补选项   = 自动补出 {len(p['option_filled'])} 题，"
              f"待人工 {len(p['option_manual'])} 题")
        print()

        if args.show_samples:
            n = args.show_samples
            print(f"  样例（前 {n} 条）：")
            for qid, new in p["content_changes"][:n]:
                old = conn.execute("SELECT content FROM quiz_questions WHERE id=?", (qid,)).fetchone()[0]
                print(f"   · content #{qid}")
                print(f"       旧 {(old or '')[:78]!r}")
                print(f"       新 {new[:78]!r}")
            for qid, new in p["options_changes"][:n]:
                old = conn.execute("SELECT options FROM quiz_questions WHERE id=?", (qid,)).fetchone()[0]
                print(f"   · options #{qid}")
                print(f"       旧 {(old or '')[:78]!r}")
                print(f"       新 {new[:78]!r}")
            print()

        if args.report_json:
            rep = {
                "mode": "apply" if args.apply else "dry-run",
                "db": os.path.abspath(args.db),
                "before": before,
                "counts": {
                    "content_watermark_rows": len(p["content_changes"]),
                    "options_watermark_rows": len(p["options_changes"]),
                    "junk_marked": len(p["junk_ids"]),
                    "figure_missing_marked": len(p["figure_ids"]),
                    "incomplete_marked": len(p["incomplete_ids"]),
                    "options_autofilled": len(p["option_filled"]),
                    "options_manual": len(p["option_manual"]),
                },
                "content_change_ids": [q for q, _ in p["content_changes"]],
                "options_change_ids": [q for q, _ in p["options_changes"]],
                "junk_ids": p["junk_ids"],
                "incomplete_ids": p["incomplete_ids"],
                "figure_missing_ids": p["figure_ids"],
                "option_filled": [{"id": q, "options": o} for q, _j, o in p["option_filled"]],
                "option_manual_list": p["option_manual"],
                "image_evidence": p["image_evidence"],
            }
            os.makedirs(os.path.dirname(os.path.abspath(args.report_json)), exist_ok=True)
            with open(args.report_json, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=2)
            print(f"  >>> 已写出 JSON 报告：{args.report_json}")

        if not args.apply:
            print(">>> DRY-RUN 结束，未做任何改动。确认无误后加 --apply（自动先备份）。")
            return 0

        if not (p["content_changes"] or p["options_changes"] or p["junk_ids"]
                or p["incomplete_ids"] or p["figure_ids"] or p["option_filled"]):
            print(">>> 无需清洗。")
            return 0

        bk = _do_backup(args.db)
        print(f">>> 备份完成（create_backup）：{bk} "
              f"({os.path.getsize(bk) / 1e6:.1f} MB)")

        cur = conn.cursor()
        # ⑥ 题面
        n_c = 0
        for qid, new in p["content_changes"]:
            n_c += cur.execute("UPDATE quiz_questions SET content=? WHERE id=?", (new, qid)).rowcount
        # ⑥ 选项
        n_o = 0
        for qid, new in p["options_changes"]:
            n_o += cur.execute("UPDATE quiz_questions SET options=? WHERE id=?", (new, qid)).rowcount
        # ⑥ junk
        n_j = 0
        for qid in p["junk_ids"]:
            n_j += cur.execute("UPDATE quiz_questions SET is_junk=1 WHERE id=?", (qid,)).rowcount
        # E3 空题
        n_i = 0
        for qid in p["incomplete_ids"]:
            n_i += cur.execute(
                "UPDATE quiz_questions SET quality='incomplete', is_available=0 WHERE id=?",
                (qid,),
            ).rowcount
        # E2 图缺失：新增附加列 figure_missing（不动 quality 分级）
        has_fm = any(r[1] == "figure_missing"
                     for r in cur.execute("PRAGMA table_info(quiz_questions)"))
        if p["figure_ids"] and not has_fm:
            cur.execute(
                "ALTER TABLE quiz_questions ADD COLUMN figure_missing INTEGER NOT NULL DEFAULT 0"
            )
            print(">>> 已新增附加列 quiz_questions.figure_missing（不覆盖 quality 分级）")
            has_fm = True
        n_f = 0
        if has_fm:
            for qid in p["figure_ids"]:
                n_f += cur.execute(
                    "UPDATE quiz_questions SET figure_missing=1 "
                    "WHERE id=? AND is_junk=0 AND figure_missing=0",
                    (qid,),
                ).rowcount
        # ⑤ 补选项
        n_p = 0
        for qid, js, _o in p["option_filled"]:
            n_p += cur.execute("UPDATE quiz_questions SET options=? WHERE id=?", (js, qid)).rowcount
        conn.commit()

        after = stats(conn)
        print(f">>> ⑥ 题面 {n_c} 行 / 选项 {n_o} 行 / junk {n_j} 题")
        print(f">>> E3 incomplete {n_i} 题 / E2 figure_missing {n_f} 题")
        print(f">>> ⑤ 补选项 {n_p} 题")
        print("\n  清理前后对比：")
        for k in before:
            b, a = before[k], after[k]
            print(f"    {k:<22} {b:>7} → {a:>7}")
        if args.report_json:
            with open(args.report_json, "r", encoding="utf-8") as fh:
                rep = json.load(fh)
            rep["after"] = after
            rep["applied"] = {
                "content_rows": n_c, "options_rows": n_o, "junk": n_j,
                "incomplete": n_i, "missing_image": n_f, "options_autofilled": n_p,
                "backup": bk,
            }
            with open(args.report_json, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=2)
            print(f">>> JSON 已更新（含 after/applied）：{args.report_json}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
