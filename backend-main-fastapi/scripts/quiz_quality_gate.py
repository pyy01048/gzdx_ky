"""题库质量门禁（quiz_questions 分级 + 污染物隔离）。

背景（2026-10-12 体检）：真库 9171 题里只有约 3500 题真正可刷。
污染来源：
  1. 讲义/PPT/课件正文被当成题目抽进题库（答案率仅 21%）
  2. 答案被当成题干（题干以「解：/答：」开头）
  3. OCR 乱码、过短文本、纯数字
  4. AI 凭空生成的 seed 伪题（id 1-7，source 却写着「真题」）
  5. 无答案题无法练习

分级规则（deterministic，可复现）：
  A 类：真题/试题/试卷来源 + 有答案 + 题干像题 + 无乱码 + 长度合理
  B 类：有答案，但来源是讲义/笔记，或题干特征弱
  C 类：无答案，但题干像真题（保留可浏览，不进默认可刷池）
  JUNK：非题目文本（PPT 残留/答案体/乱码/过短/纯符号/seed 伪题）

写库策略：
  * JUNK → is_junk=1（列表默认已排除，立即生效）
  * A/B/C → quality 字段 + is_available
  * seed 伪题单独物理删除（前 7 条，非真实数据）

用法：
    python scripts/quiz_quality_gate.py            # dry-run
    python scripts/quiz_quality_gate.py --apply
    python scripts/quiz_quality_gate.py --apply --delete-seed
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

# ---- 词表与启发式：唯一真源在 services/quiz_content_gate.py ----
# 本脚本只做「存量分级 + 写库」，判定逻辑全部复用共享模块，
# 避免历史体检与入库闸门两处逻辑漂移。
sys.path.insert(0, BASE_DIR)
from services.quiz_content_gate import (  # noqa: E402
    LECTURE_SRC,
    MIN_LEN,
    REAL_SRC,
    has_answer,
    has_ppt_residue,
    is_mojibake,
    looks_like_answer_body,
    looks_like_question,
    mostly_symbol,
)

from services.delete_guard import require_physical_delete_enabled  # noqa: E402


def classify(row) -> Tuple[str, str]:
    """返回 (等级, 原因)。等级 ∈ {A,B,C,JUNK}。"""
    qid, content, answer, source, qtype, options = row
    c = (content or "").strip()
    src = source or ""
    has_ans = has_answer(answer)

    # 0. AI 凭空生成的 seed 伪题（id 1-7，source 却写着「真题」）
    SEED_FAKE_IDS = {1, 2, 3, 4, 5, 6, 7}
    if qid in SEED_FAKE_IDS:
        return "JUNK", "AI伪造seed题"

    # 1. 硬性垃圾（无论有无答案）
    if len(c) < MIN_LEN:
        return "JUNK", "内容过短"
    if is_mojibake(c):
        return "JUNK", "OCR乱码"
    if mostly_symbol(c):
        return "JUNK", "纯符号噪声"
    if looks_like_answer_body(c):
        return "JUNK", "答案体当题干"
    if has_ppt_residue(c):
        return "JUNK", "PPT/讲义结构残留"
    if re.fullmatch(r"[\d\s\.\-]+", c):
        return "JUNK", "纯数字"

    is_real = bool(REAL_SRC.search(src))
    is_lecture = bool(LECTURE_SRC.search(src))
    like_q = looks_like_question(c)

    # 2. 无答案：像题且篇幅合理 → C（可浏览，不进默认可刷池）
    if not has_ans:
        if like_q and len(c) <= 400:
            tag = "真题缺答案" if is_real else "习题缺答案"
            return "C", f"{tag}（可浏览不可刷）"
        if like_q:
            return "JUNK", "讲义长段落（非离散题目）"
        return "JUNK", "无答案且不像题"

    # 3. 有答案 → A / B
    if is_real and like_q:
        return "A", "真题+有答案+像题"
    if is_lecture and len(c) > 600:
        # 讲义长段落 + 有答案 → 更像知识点，仍降级
        return "B", "讲义长段落"
    return "B", "有答案"


def backup(con: sqlite3.Connection) -> str:
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_quizgate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    return bak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--delete-seed", action="store_true",
                    help="物理删除 id<=7 的 AI 伪造 seed 题")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")

    rows = con.execute(
        "SELECT id, content, answer, source, question_type, options "
        "FROM quiz_questions"
    ).fetchall()

    from collections import Counter, defaultdict
    dist = Counter()
    reasons = Counter()
    by_grade: Dict[str, List[int]] = defaultdict(list)
    for r in rows:
        g, why = classify(r)
        dist[g] += 1
        reasons[(g, why)] += 1
        by_grade[g].append(r[0])

    print(f"题库总数: {len(rows)}")
    for g in ("A", "B", "C", "JUNK"):
        print(f"  {g}: {dist.get(g, 0)}")
    print()
    print("判定原因分布:")
    for (g, why), n in reasons.most_common():
        print(f"  [{g}] {why}: {n}")

    if args.apply:
        bak = backup(con)
        print(f"\n备份 → {bak}")
        con.execute("BEGIN")

        # JUNK → is_junk=1
        junk = by_grade["JUNK"]
        if junk:
            for i in range(0, len(junk), 500):
                chunk = junk[i:i + 500]
                con.execute(
                    f"UPDATE quiz_questions SET is_junk=1 WHERE id IN "
                    f"({','.join('?' * len(chunk))})", chunk)
        # A/B/C → quality
        for g in ("A", "B", "C"):
            ids = by_grade[g]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                con.execute(
                    f"UPDATE quiz_questions SET quality=?, is_junk=0 WHERE id IN "
                    f"({','.join('?' * len(chunk))})", [g] + chunk)

        # C 类不可刷（无答案）
        cids = by_grade["C"]
        if cids:
            con.execute(
                f"UPDATE quiz_questions SET is_available=0 WHERE id IN "
                f"({','.join('?' * len(cids))})", cids)
        # A/B 可刷
        avail = by_grade["A"] + by_grade["B"]
        if avail:
            for i in range(0, len(avail), 500):
                chunk = avail[i:i + 500]
                con.execute(
                    f"UPDATE quiz_questions SET is_available=1 WHERE id IN "
                    f"({','.join('?' * len(chunk))})", chunk)

        if args.delete_seed:
            seed = [r[0] for r in rows if r[0] <= 7]
            if seed:
                # 物理删除闸门：quiz_questions 物理删除不可逆。硬编码的
                # seed 判定（id<=7）若与真实数据冲突，会直接吃掉真题。
                require_physical_delete_enabled("quiz_questions")
                con.execute(
                    f"DELETE FROM quiz_questions WHERE id IN "
                    f"({','.join('?' * len(seed))})", seed)
                print(f"已删除 seed 伪题 {len(seed)} 条: {seed}")

        con.commit()
        print("\n写库完成")

    # 复核
    print()
    print("=== 复核 ===")
    for r in con.execute(
        "SELECT coalesce(quality,'NULL'), count(*) FROM quiz_questions "
        "WHERE coalesce(is_junk,0)=0 GROUP BY 1 ORDER BY 2 DESC"
    ):
        print(f"  可见题 quality={r[0]}: {r[1]}")
    tot_visible = con.execute(
        "SELECT count(*) FROM quiz_questions WHERE coalesce(is_junk,0)=0"
    ).fetchone()[0]
    tot_junk = con.execute(
        "SELECT count(*) FROM quiz_questions WHERE is_junk=1"
    ).fetchone()[0]
    print(f"  可见 {tot_visible} / 隔离 {tot_junk} / 总计 {tot_visible + tot_junk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
