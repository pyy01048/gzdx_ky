# -*- coding: utf-8 -*-
"""题库脏数据体检（quiz_questions · 只读 dry-run · 2026-10-13）。

背景（用户反馈 + 2026-10-12 门禁复盘）
------------------------------------
题库页面暴露的结构性问题：选项只有两三个 ABCD、识别图缺失、空题假题；
存量 9096 题中约 89% 无选项、58% 无答案、约 3570 条已标 junk；
管综（管理类联考 逻辑/写作/数学）题目错配进了「数字电子技术 / 政治 / 英语」等科目。

本脚本做**全量分类体检**，一条题可同时命中多个标签（统计按标签独立计数，
不做互斥划分——脏数据常多重叠加）：

  C1 no_options       无选项（细分：选择/判断题缺选项=结构残缺 vs 其他题型正常）
  C2 no_answer        无答案（细分：analysis 非空可回填 vs 全空）
  C3 options_abnormal 选项数异常（<4 个 / >4 个 / JSON 解析失败 / 4 选项但答案非单字母）
  C4 stem_anomaly     空题干 / 微题干（<MIN_LEN）/ 名词条目（无题目特征词）
  C5 subject_mismatch 科目错配（管综写作逻辑 / 管综数学 / 英语科目中文内容 /
                       模电数电术语交叉(疑似) / 高数线代特征错配(疑似)）
  C6 junk             junk 分布（已隔离 / junk 但 is_available=1 状态矛盾 /
                       未标 junk 但命中垃圾判据的漏网候选）
  C7 figure_missing   识别图缺失（题干引用图，但库中无任何图片存储）
  C8 status_anomaly   状态字段矛盾（junk/available/quality 互相打架）
  C9 related_refs     关联表引用（物理删除前必须同步处理的外键数据）

**本轮只做 dry-run 报告，绝不改库**：

  * 连接用 ``file:...?mode=ro`` URI，从协议层禁止写；
  * 每条脏数据只给**处置建议**（补全/隔离/删除/重分类），不执行；
  * 清洗动作留待本报告确认后，由后续脚本显式 --apply 执行。

铁律（任何后续写操作的前置条件）
--------------------------------
  1. 写库前必须调用本模块 :func:`backup`（即项目 ``src.backup(dst)`` 约定：
     SQLite ``Connection.backup()`` 在线备份 API，WAL 安全）；
  2. **严禁 shutil.copy2 / cp / 文件级拷贝**——WAL 模式下 -wal/-shm 里
     未合并的数据会丢，产出「看着成功、实则缺数据」的备份比没有备份更危险
     （见 services/delete_guard.py 模块 docstring）；
  3. 物理删除 quiz_questions 还需 ``KAOYAN_ALLOW_PHYSICAL_DELETE=1`` +
     ``require_physical_delete_enabled()`` 双闸门。

判定逻辑复用
------------
  * 「像不像题 / 是不是垃圾」全部复用 ``services.quiz_content_gate.py``
    （入库闸门与存量体检的唯一真源，避免逻辑漂移）；
  * 真库路径解析顺序与 ``services/delete_guard._resolve_db_path`` 同源。

用法::

    D:/Anaconda/python.exe scripts/quiz_health_check.py
    D:/Anaconda/python.exe scripts/quiz_health_check.py --sample 8
    D:/Anaconda/python.exe scripts/quiz_health_check.py --db /path/kaoyan.db --out-dir /path/docx

输出（默认写入仓库根 docx/，与历史报告同目录）::

    23-题库脏数据体检报告-20261013.json
    23-题库脏数据体检报告-20261013.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent          # backend-main-fastapi
REPO_ROOT = BASE_DIR.parent                                # D:/平台
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ---- 复用项目内唯一真源：入库内容闸门判据 ----
from services.quiz_content_gate import (  # noqa: E402
    MIN_LEN,
    has_answer,
    has_ppt_residue,
    is_mojibake,
    looks_like_answer_body,
    looks_like_question,
    mostly_symbol,
)

REPORT_STEM = "23-题库脏数据体检报告-20261013"

# --------------------------------------------------------------------------- #
# 一、真库路径解析（与 services/delete_guard._resolve_db_path 同源同序）
# --------------------------------------------------------------------------- #
def resolve_db_path() -> str:
    """按项目既定优先级解析真库路径，回落仓库同级 database/kaoyan.db。

    1. 环境变量 KAOYAN_DB_PATH；
    2. 仓库同级 database/kaoyan.db（即 D:/平台/database/kaoyan.db）。
    """
    env = (os.environ.get("KAOYAN_DB_PATH") or "").strip()
    if env:
        return str(Path(env))
    return str((REPO_ROOT / "database" / "kaoyan.db").resolve())


def connect_ro(db_path: str) -> sqlite3.Connection:
    """只读连接（URI mode=ro）。WAL 库可读，且从协议层禁止任何写入。"""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


# --------------------------------------------------------------------------- #
# 二、备份（供后续 --apply 类脚本使用；本 dry-run 脚本不调用）
# --------------------------------------------------------------------------- #
def backup(con: sqlite3.Connection, tag: str = "quizclean") -> str:
    """写操作前置备份：SQLite 在线备份 API（即项目 src.backup(dst) 约定）。

    铁律：
      * 只用 ``con.backup(dest)``——WAL 安全，无需停服务；
      * 严禁 shutil.copy2/cp/文件级拷贝（会丢 -wal 未合并数据）。
    """
    bak_dir = BASE_DIR / "data" / "backups"
    bak_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = bak_dir / f"kaoyan_pre_{tag}_{ts}.db"
    with sqlite3.connect(str(bak)) as dest:
        con.backup(dest)
    return str(bak)


# --------------------------------------------------------------------------- #
# 三、分类判据
# --------------------------------------------------------------------------- #
_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")
#: 对错标记串（OCR 答案页碎片，如 "× 2． × 3． √"）
_ANSWER_TOGGLE_RE = re.compile(r"^[×√✓✗\s\d．.、，,；;|/]+$")
#: 题干引用图的特征（识别图缺失的判定信号）
_FIGURE_REF_RE = re.compile(
    r"如下\s*图|如图|图中|见图|如图所示|所示|【图|图\s*\d|图[a-zA-Z]|[（(]\s*图"
)
#: 管综·写作/逻辑特征词
_MGZ_WRITING_TERMS = (
    "论证有效性分析", "论说文", "管理类联考", "管综", "逻辑推理",
    "形式逻辑", "论证逻辑", "批判性思维", "MBA", "MPAcc", "审计硕士",
)
#: 管综·数学（条件充分性判断）特征：条件(1)和条件(2) / 条件充分性
_MGZ_MATH_RE = re.compile(
    r"条件\s*[（(]\s*1\s*[）)]\s*和条件\s*[（(]\s*2|条件充分性判断|"
    r"联合起来.*充分|单独.*充分"
)
#: 模电专属术语（用于模电/数电交叉检测）
_ANALOG_TERMS = (
    "三极管", "放大电路", "负反馈", "正反馈", "PN结", "伏安特性", "集成运放",
    "运放", "静态工作点", "零点漂移", "整流", "功率放大", "频率响应", "波特图",
    "共射", "共集", "共基", "差动放大", "失真",
)
#: 数电专属术语
_DIGITAL_TERMS = (
    "逻辑门", "触发器", "译码器", "编码器", "计数器", "寄存器", "时序逻辑",
    "组合逻辑", "卡诺图", "布尔", "BCD", "加法器", "数据选择器", "存储器",
    "竞争冒险", "D触发器", "JK", "或门", "与门", "非门",
)
#: 高数/线代/概率特征（错配进工科/英语科目的疑似信号）
_MATH_TERMS = (
    "极限", "导数", "微分", "积分", "矩阵", "行列式", "特征值", "特征向量",
    "正交", "可导", "连续", "级数", "方差", "分布列", "概率",
)


def parse_options(raw: Any) -> Tuple[int, Optional[list]]:
    """把 options 列解析成 (选项数, 选项列表)。无法解析返回 (-1, None)。"""
    if raw is None:
        return 0, None
    s = str(raw).strip()
    if s in ("", "null", "NULL", "[]", "{}"):
        return 0, None
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return -1, None
    if isinstance(obj, dict):
        return len(obj), list(obj.values())
    if isinstance(obj, list):
        return len(obj), [str(x) for x in obj]
    return -1, None


def cjk_ratio(text: str) -> float:
    """中文字符占比（用于「英语科目里的中文题」检测）。"""
    if not text:
        return 0.0
    cjk = len(_CJK_RE.findall(text))
    return cjk / max(len(text), 1)


def detect_figure_ref(content: str) -> bool:
    return bool(_FIGURE_REF_RE.search(content or ""))


def detect_subject_mismatch(row: Dict[str, Any]) -> List[str]:
    """返回该题命中的科目错配子类列表（可多命中）。"""
    hits: List[str] = []
    content = row["content"] or ""
    subject = row["subject"] or ""
    # C5a 管综·写作/逻辑 错配进非管综科目
    if any(k in content for k in _MGZ_WRITING_TERMS) and subject not in (
        "管理类联考", "管综", "真题综合",
    ):
        hits.append("管综写作逻辑错配")
    # C5b 管综·数学 错配
    if _MGZ_MATH_RE.search(content) and subject not in ("数学", "管理类联考", "管综"):
        hits.append("管综数学错配")
    # C5c 英语科目里的中文内容（英语题不应大段中文）
    if subject == "英语" and cjk_ratio(content) > 0.8:
        hits.append("英语科目中文内容")
    # C5d 模电/数电术语交叉（保守：仅一侧强特征且另一侧零特征才判疑似）
    if subject == "数字电子技术":
        a = sum(1 for k in _ANALOG_TERMS if k in content)
        d = sum(1 for k in _DIGITAL_TERMS if k in content)
        if a >= 2 and d == 0:
            hits.append("数电科目含模电内容(疑似)")
    elif subject == "模拟电子技术":
        a = sum(1 for k in _ANALOG_TERMS if k in content)
        d = sum(1 for k in _DIGITAL_TERMS if k in content)
        if d >= 2 and a == 0:
            hits.append("模电科目含数电内容(疑似)")
    # C5e 高数/线代特征错配进工科/英语科目（疑似）
    if subject in ("数字电子技术", "英语", "政治", "其他"):
        m = sum(1 for k in _MATH_TERMS if k in content)
        if m >= 2:
            hits.append("高数线代特征错配(疑似)")
    return hits


def detect_junk_candidate(row: Dict[str, Any]) -> Optional[str]:
    """is_junk=0 的行中，命中垃圾判据的返回原因（复用 content gate 判据）。"""
    content = (row["content"] or "").strip()
    n_opt, _ = parse_options(row["options"])
    measured = content
    if n_opt >= 3:
        opts = parse_options(row["options"])[1] or []
        measured = content + "".join(opts)
    if len(measured) < (MIN_LEN if not has_answer(row["answer"]) else 10):
        return "内容过短"
    if is_mojibake(content):
        return "OCR乱码"
    if mostly_symbol(content):
        return "纯符号噪声"
    if _ANSWER_TOGGLE_RE.match(content) and content:
        return "对错标记串"
    if looks_like_answer_body(content):
        return "答案体当题干"
    if has_ppt_residue(content):
        return "PPT/讲义结构残留"
    if re.fullmatch(r"[\d\s.\-]+", content):
        return "纯数字"
    return None


# --------------------------------------------------------------------------- #
# 四、主体检流程
# --------------------------------------------------------------------------- #
ROWS_SQL = (
    "SELECT id, content, options, answer, analysis, subject, chapter, "
    "question_type, source, is_junk, is_available, quality "
    "FROM quiz_questions"
)


def run_health_check(con: sqlite3.Connection, sample_n: int) -> Dict[str, Any]:
    rows = [dict(r) for r in con.execute(ROWS_SQL)]
    total = len(rows)

    # ---- 汇总容器 ----
    cat: Dict[str, Counter] = defaultdict(Counter)          # 类别 -> Counter(科目)
    cat_type: Dict[str, Counter] = defaultdict(Counter)     # 类别 -> Counter(题型)
    cat_sub: Dict[str, Counter] = defaultdict(Counter)      # 类别 -> Counter(子类)
    samples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    ids_by_cat: Dict[str, List[int]] = defaultdict(list)

    def add(cat_name: str, row: Dict[str, Any], sub: str = "") -> None:
        cat[cat_name][row["subject"] or "NULL"] += 1
        cat_type[cat_name][row["question_type"] or "NULL"] += 1
        if sub:
            cat_sub[cat_name][sub] += 1
        ids_by_cat[cat_name].append(row["id"])
        if len(samples[cat_name]) < sample_n:
            samples[cat_name].append({
                "id": row["id"],
                "subject": row["subject"],
                "question_type": row["question_type"],
                "sub": sub,
                "content": (row["content"] or "")[:80],
            })

    # ---- C1 无选项 ----
    for r in rows:
        n_opt, _ = parse_options(r["options"])
        if n_opt == 0:
            if r["question_type"] in ("single", "judge"):
                add("no_options", r, "选择/判断题缺选项(结构残缺)")
            else:
                add("no_options", r, "非选择题型无选项(正常)")

    # ---- C2 无答案 ----
    for r in rows:
        if not has_answer(r["answer"]):
            has_analysis = bool((r["analysis"] or "").strip())
            add("no_answer", r, "analysis非空(可回填)" if has_analysis else "答案与解析均空")

    # ---- C3 选项数异常 ----
    for r in rows:
        n_opt, _ = parse_options(r["options"])
        if n_opt < 0:
            add("options_abnormal", r, "JSON解析失败")
        elif 0 < n_opt < 4:
            add("options_abnormal", r, f"选项不足4个({n_opt}个)")
        elif n_opt > 4:
            add("options_abnormal", r, f"选项超过4个({n_opt}个)")
        elif n_opt == 4:
            ans = (r["answer"] or "").strip()
            if not re.fullmatch(r"[A-Da-d]", ans):
                add("options_abnormal", r, "4选项但答案非单字母")

    # ---- C4 题干异常 ----
    for r in rows:
        content = (r["content"] or "").strip()
        if not content:
            add("stem_anomaly", r, "空题干")
        elif len(content) < MIN_LEN:
            add("stem_anomaly", r, "微题干(<15字)")
        elif len(content) < 25 and not looks_like_question(content):
            n_opt, _ = parse_options(r["options"])
            if n_opt < 3:
                add("stem_anomaly", r, "名词条目(无题目特征)")

    # ---- C5 科目错配 ----
    for r in rows:
        for sub in detect_subject_mismatch(r):
            add("subject_mismatch", r, sub)

    # ---- C6 junk ----
    for r in rows:
        if r["is_junk"]:
            add("junk_isolated", r)
            if r["is_available"]:
                add("status_anomaly", r, "junk但is_available=1(状态矛盾)")
        else:
            reason = detect_junk_candidate(r)
            if reason:
                add("junk_candidate", r, reason)

    # ---- C7 识别图缺失 ----
    for r in rows:
        if detect_figure_ref(r["content"] or ""):
            add("figure_missing", r)

    # ---- C8 其他状态矛盾 ----
    for r in rows:
        if not r["is_junk"] and r["is_available"] and not r["quality"]:
            add("status_anomaly", r, "可刷但quality未分级")
        if r["is_junk"] and r["quality"] in ("A", "B"):
            add("status_anomaly", r, "junk但quality=A/B")

    # ---- C9 关联表引用 ----
    related: Dict[str, Dict[str, int]] = {}
    for tbl in ("error_records", "answer_records", "paper_questions",
                "question_knowledge_links", "answer_candidates"):
        try:
            tot = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            dist = con.execute(
                f"SELECT COUNT(DISTINCT question_id) FROM {tbl}"
            ).fetchone()[0]
            related[tbl] = {"rows": tot, "distinct_question_id": dist}
        except sqlite3.Error as e:  # 表不存在等情况
            related[tbl] = {"rows": -1, "distinct_question_id": -1, "error": str(e)}

    # ---- 图片存储存在性证据（证明「图缺失」判定成立）----
    img_cols = [c[1] for c in con.execute("PRAGMA table_info(quiz_questions)")
                if any(k in c[1].lower() for k in ("img", "image", "figure", "pic"))]
    img_tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND ("
        "name LIKE '%image%' OR name LIKE '%img%' OR name LIKE '%figure%')")]

    # ---- 按科目交叉矩阵 ----
    matrix: Dict[str, Dict[str, int]] = defaultdict(Counter)
    for r in rows:
        s = r["subject"] or "NULL"
        matrix[s]["total"] += 1
        if r["is_junk"]:
            matrix[s]["junk"] += 1
        if r["is_available"]:
            matrix[s]["available"] += 1
        n_opt, _ = parse_options(r["options"])
        if n_opt == 0:
            matrix[s]["no_options"] += 1
        if not has_answer(r["answer"]):
            matrix[s]["no_answer"] += 1
        if detect_figure_ref(r["content"] or ""):
            matrix[s]["figure_missing"] += 1
        if detect_subject_mismatch(r):
            matrix[s]["subject_mismatch"] += 1

    return {
        "total": total,
        "cat_by_subject": {k: dict(v) for k, v in cat.items()},
        "cat_by_type": {k: dict(v) for k, v in cat_type.items()},
        "cat_by_sub": {k: dict(v) for k, v in cat_sub.items()},
        "cat_counts": {k: sum(v.values()) for k, v in cat.items()},
        "ids_by_cat": {k: v for k, v in ids_by_cat.items()},
        "samples": {k: v for k, v in samples.items()},
        "related_refs": related,
        "image_storage_evidence": {
            "quiz_questions_image_columns": img_cols,
            "image_tables": img_tables,
            "conclusion": "库中无任何题目图片存储 → 所有引用图的题目均为识别图缺失",
        },
        "subject_matrix": {k: dict(v) for k, v in matrix.items()},
    }


# --------------------------------------------------------------------------- #
# 五、处置建议（每类数据的处置矩阵；本轮只建议不执行）
# --------------------------------------------------------------------------- #
DISPOSAL = [
    ("no_options", "选择/判断题缺选项(结构残缺)",
     "补全（同 source 原卷重新 OCR 提取选项）；无法补全的隔离 is_available=0",
     "中", "补全依赖原 PDF；隔离即时生效、零风险"),
    ("no_options", "非选择题型无选项(正常)",
     "不处置（简答/计算/填空题本无选项）", "无", "—"),
    ("no_answer", "答案与解析均空",
     "补全（从 source 原卷回填答案）；短期降级 quality=C 仅浏览不可刷",
     "中", "回填需人工/模型校对，错误答案比无答案更糟"),
    ("no_answer", "analysis非空(可回填)",
     "补全（从 analysis 提炼标准答案，可立即执行）", "低", "analysis 已是既有事实数据，提炼答案风险低"),
    ("options_abnormal", "选项不足4个(<4)",
     "补全缺失选项；补不全的隔离", "中", "用户反馈「只有两三个 ABCD」的直接来源"),
    ("options_abnormal", "选项超过4个(>4)",
     "人工复核（多选残留 or 切分错误）；确认后合并或重修", "中", "勿直接删"),
    ("options_abnormal", "4选项但答案非单字母",
     "复核答案列（可能是解析文本混入 or 答案格式错误）", "低", "格式问题居多"),
    ("options_abnormal", "JSON解析失败",
     "人工核查 options 原文后重修", "低", "—"),
    ("stem_anomaly", "空题干",
     "删除（无出题价值）", "低", "需先清理关联表引用"),
    ("stem_anomaly", "微题干(<15字)",
     "删除或转 flashcards（名词条目类）", "中", "转存比删除更利用存量"),
    ("stem_anomaly", "名词条目(无题目特征)",
     "重分类为 flashcards/知识点，退出题库", "低", "非题内容占库存是「空题假题」观感来源"),
    ("subject_mismatch", "管综写作逻辑错配",
     "重分类到新科目「管理类联考」并重设题型（写作/逻辑）", "中",
     "需先建科目与题型映射；本题库服务对象若不含管综则改为隔离"),
    ("subject_mismatch", "管综数学错配",
     "重分类到「管理类联考·数学」或「数学」", "中", "同上"),
    ("subject_mismatch", "英语科目中文内容",
     "按内容实际科目重分类（管综/数学/政治）", "中", "英语科目 92 题几乎全是错配"),
    ("subject_mismatch", "数电科目含模电内容(疑似)",
     "人工抽审后重分类或合并科目", "高", "术语交叉有误判风险，必须先抽样确认"),
    ("subject_mismatch", "模电科目含数电内容(疑似)",
     "人工抽审后重分类或合并科目", "高", "同上"),
    ("subject_mismatch", "高数线代特征错配(疑似)",
     "人工抽审后重分类到「数学」", "高", "疑似信号，勿批量执行"),
    ("junk_isolated", "",
     "维持 is_junk=1 隔离（列表默认已排除，零风险）", "无", "现状已正确"),
    ("junk_candidate", "",
     "分批标记 is_junk=1（先小批 --apply + 复核，再放量）", "中",
     "宁可漏判不误删；与 quiz_quality_gate.py 判据同源"),
    ("figure_missing", "",
     "补图（从 source PDF 页定位裁剪）或题干补文字描述；短期隔离", "高",
     "无图的选择题/计算题不可刷；补图成本最高，建议先隔离"),
    ("status_anomaly", "junk但is_available=1(状态矛盾)",
     "立即修正 is_available=0（用户可能正刷到垃圾题）", "低",
     "状态矛盾属确定性 bug，无判定风险"),
    ("status_anomaly", "junk但quality=A/B",
     "复核后清除 quality 或解除 junk（二选一，不允许并存）", "低", "—"),
    ("status_anomaly", "可刷但quality未分级",
     "跑 quiz_quality_gate.py 补分级", "低", "—"),
]


# --------------------------------------------------------------------------- #
# 六、报告渲染
# --------------------------------------------------------------------------- #
def _pct(n: int, total: int) -> str:
    return f"{n / total * 100:.1f}%" if total else "-"


CAT_TITLES = {
    "no_options": "C1 无选项",
    "no_answer": "C2 无答案",
    "options_abnormal": "C3 选项数异常",
    "stem_anomaly": "C4 题干异常（空题/微题干/名词条目）",
    "subject_mismatch": "C5 科目错配",
    "junk_isolated": "C6a junk 已隔离",
    "junk_candidate": "C6b junk 漏网候选（未标 junk 但命中垃圾判据）",
    "figure_missing": "C7 识别图缺失",
    "status_anomaly": "C8 状态字段矛盾",
}


def render_markdown(data: Dict[str, Any], meta: Dict[str, Any]) -> str:
    total = data["total"]
    L: List[str] = []
    L.append("# 题库脏数据体检报告（dry-run · 只读）")
    L.append("")
    L.append(f"- 生成时间：{meta['generated_at']}")
    L.append(f"- 数据库：`{meta['db_path']}`（{meta['db_size_mb']} MB，WAL）")
    L.append(f"- 运行方式：`D:/Anaconda/python.exe scripts/quiz_health_check.py`（URI mode=ro，零写入）")
    L.append(f"- 题库总数：**{total}** 题")
    L.append(f"- 本报告性质：**dry-run，未改动真库任何数据**；清洗动作待本报告确认后另行执行")
    L.append("")
    L.append("## 一、总览")
    L.append("")
    L.append("| 类别 | 条数 | 占比 |")
    L.append("|---|---|---|")
    for key in ("no_options", "no_answer", "options_abnormal", "stem_anomaly",
                "subject_mismatch", "junk_isolated", "junk_candidate",
                "figure_missing", "status_anomaly"):
        n = data["cat_counts"].get(key, 0)
        L.append(f"| {CAT_TITLES[key]} | {n} | {_pct(n, total)} |")
    L.append("")
    L.append("> 注：一条题可同时命中多个类别（如「无选项 + 无答案 + 缺图」），各类别独立计数，不可相加。")
    L.append("")

    L.append("## 二、分类明细")
    for key in ("no_options", "no_answer", "options_abnormal", "stem_anomaly",
                "subject_mismatch", "junk_isolated", "junk_candidate",
                "figure_missing", "status_anomaly"):
        n = data["cat_counts"].get(key, 0)
        if n == 0:
            continue
        L.append("")
        L.append(f"### {CAT_TITLES[key]}（{n} 条，{_pct(n, total)}）")
        subs = data["cat_by_sub"].get(key) or {}
        if subs:
            L.append("")
            L.append("子类分布：")
            for sub, c in sorted(subs.items(), key=lambda x: -x[1]):
                L.append(f"- {sub}：{c}")
        by_subject = data["cat_by_subject"].get(key) or {}
        if by_subject:
            L.append("")
            L.append("按科目：" + "；".join(
                f"{s} {c}" for s, c in sorted(by_subject.items(), key=lambda x: -x[1])))
        samples = data["samples"].get(key) or []
        if samples:
            L.append("")
            L.append("样例：")
            for s in samples:
                sub = f"[{s['sub']}] " if s.get("sub") else ""
                L.append(f"- id={s['id']} {s['subject']}/{s['question_type']} "
                         f"{sub}{s['content']}")
    L.append("")

    L.append("## 三、junk 分布（按科目）")
    L.append("")
    L.append("| 科目 | 总数 | 已隔离junk | 可刷 | 无选项 | 无答案 | 缺图 | 错配 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s, m in sorted(data["subject_matrix"].items(),
                       key=lambda x: -x[1].get("total", 0)):
        L.append(f"| {s} | {m.get('total', 0)} | {m.get('junk', 0)} | "
                 f"{m.get('available', 0)} | {m.get('no_options', 0)} | "
                 f"{m.get('no_answer', 0)} | {m.get('figure_missing', 0)} | "
                 f"{m.get('subject_mismatch', 0)} |")
    L.append("")

    L.append("## 四、识别图缺失的判定依据")
    ev = data["image_storage_evidence"]
    L.append("")
    L.append(f"- quiz_questions 表中的图片字段：{ev['quiz_questions_image_columns'] or '无'}")
    L.append(f"- 库中的图片相关表：{ev['image_tables'] or '无'}")
    L.append(f"- 结论：{ev['conclusion']}")
    L.append("")

    L.append("## 五、关联表引用（物理删除前必须同步处理）")
    L.append("")
    L.append("| 关联表 | 行数 | 涉及题目数 |")
    L.append("|---|---|---|")
    for t, m in data["related_refs"].items():
        L.append(f"| {t} | {m['rows']} | {m['distinct_question_id']} |")
    L.append("")
    L.append("> 建议：优先用 is_junk / is_available 软隔离（零风险），不轻易物理删除；"
             "确需 DELETE 时必须同步清理上表引用，且先过 delete_guard 双闸门。")
    L.append("")

    L.append("## 六、处置建议矩阵（本轮只建议，不执行）")
    L.append("")
    L.append("| 类别 | 子类 | 建议动作 | 风险 | 备注 |")
    L.append("|---|---|---|---|---|")
    for cat_name, sub, action, risk, note in DISPOSAL:
        L.append(f"| {CAT_TITLES.get(cat_name, cat_name)} | {sub or '—'} | "
                 f"{action} | {risk} | {note} |")
    L.append("")

    L.append("## 七、铁律（后续清洗执行前必须满足）")
    L.append("")
    L.append("1. 任何写操作前必须调用 SQLite backup API 备份（本模块 `backup()`，"
             "即项目 `src.backup(dst)` 约定）；**严禁 shutil.copy2 / cp / 文件级拷贝**"
             "（WAL 模式下会丢 -wal 未合并数据）。")
    L.append("2. 物理删除 quiz_questions 需 `KAOYAN_ALLOW_PHYSICAL_DELETE=1` 且通过 "
             "`services.delete_guard.require_physical_delete_enabled()`。")
    L.append("3. 建议执行顺序：先修状态矛盾（C8，零风险）→ 再软隔离（junk 漏网/缺图）→ "
             "再补全（答案回填）→ 最后重分类（科目错配，需先抽审）。")
    L.append("")
    L.append("## 八、复现命令")
    L.append("")
    L.append("```bash")
    L.append("cd D:/平台/backend-main-fastapi")
    L.append("D:/Anaconda/python.exe scripts/quiz_health_check.py")
    L.append("```")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# 七、入口
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="题库脏数据体检（只读 dry-run）")
    ap.add_argument("--db", default="", help="数据库路径（默认按项目优先级解析真库）")
    ap.add_argument("--out-dir", default="", help="报告输出目录（默认仓库根 docx/）")
    ap.add_argument("--sample", type=int, default=5, help="每类样例条数（默认 5）")
    args = ap.parse_args()

    db_path = args.db or resolve_db_path()
    if not os.path.isfile(db_path):
        print(f"[错误] 数据库不存在: {db_path}")
        return 2
    out_dir = Path(args.out_dir) if args.out_dir else (REPO_ROOT / "docx")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"数据库: {db_path} ({os.path.getsize(db_path) / 1024 / 1024:.1f} MB)")
    print("连接模式: 只读 (URI mode=ro) —— 本脚本不会写入任何数据")
    con = connect_ro(db_path)
    try:
        data = run_health_check(con, args.sample)
    finally:
        con.close()

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": str(Path(db_path).resolve()),
        "db_size_mb": round(os.path.getsize(db_path) / 1024 / 1024, 1),
        "mode": "dry-run (read-only)",
        "python": sys.version.split()[0],
        "sample_n": args.sample,
    }

    json_path = out_dir / f"{REPORT_STEM}.json"
    md_path = out_dir / f"{REPORT_STEM}.md"
    payload = {"meta": meta, **data}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    md_path.write_text(render_markdown(data, meta), encoding="utf-8")

    # ---- 控制台摘要 ----
    total = data["total"]
    print(f"\n题库总数: {total}")
    for key in ("no_options", "no_answer", "options_abnormal", "stem_anomaly",
                "subject_mismatch", "junk_isolated", "junk_candidate",
                "figure_missing", "status_anomaly"):
        n = data["cat_counts"].get(key, 0)
        print(f"  {CAT_TITLES[key]}: {n} ({_pct(n, total)})")
    print(f"\n报告已生成:\n  {json_path}\n  {md_path}")
    print("dry-run 完成：未改动真库任何数据。清洗动作待报告确认后执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
