"""
刷题元数据回填（幂等）

背景：quiz_questions 的 year / paper / question_no 三列长期全为 NULL，
导致「按年份 / 真题套卷 / 题号网格」这类结构化浏览无法实现，前端只能用
文档名临时猜测（且只覆盖前 500 题）。本脚本从 source 文档名里可靠地解析
出「真题套卷名(paper)」与「年份(year)」，并在套卷内按 id 顺序补 question_no。

诚实原则（重要）：
- 只对 source 以「真题」开头的题目回填 paper（知识库/教材题不属于任何套卷）。
- year 只在能无歧义解析时才写：4 位年份(19xx/20xx) 唯一，或明确的「NN年」。
  多年区间（如「贵大16-21真题」）不猜单一年份，year 留空，靠 paper 归组。
- question_no 是「套卷内按录入顺序的序号」，不是原卷题号（原卷题号无法可靠还原）。
- 全程幂等：重复运行结果一致；先自动备份数据库。

用法：
    python scripts/backfill_quiz_meta.py           # 预览（dry-run，不写库）
    python scripts/backfill_quiz_meta.py --apply    # 实际写库（先备份）
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime

# 真库路径：优先 DATABASE_PATH（与 .env 一致），回退到 database/kaoyan.db
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_DEFAULT_DB = os.path.join(os.path.dirname(_ROOT), "database", "kaoyan.db")
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or _DEFAULT_DB

_FOUR = re.compile(r"(?:19|20)\d{2}")
_RANGE = re.compile(r"\d{2}\s*[-–~]\s*\d{2}")
_TWO_YEAR = re.compile(r"(\d{2})\s*年")


def parse_paper(source: str) -> str | None:
    """从 source 文档名解析真题套卷名；非真题返回 None。

    兼容两种前缀：「真题:xxx」与「知识库:2009年计算机408统考真题」——
    后者虽挂在知识库前缀下，但本质是按年份组织的真题卷，同样归入套卷索引。
    判定标准：文档名中出现「真题」二字。纯教材/讲义（无「真题」）不归卷。
    """
    if not source or "真题" not in source:
        return None
    name = source
    # 去掉「真题:」/「知识库:」等来源前缀
    name = re.sub(r"^(真题|知识库|文档|资料)\s*[:：]\s*", "", name)
    # 去掉扩展名
    name = re.sub(r"\.(pdf|txt|docx?|md|pptx?)$", "", name, flags=re.I)
    # 收尾清理：去多余空格与句点
    name = name.strip().rstrip(".").strip()
    return name or None


def parse_year(source: str) -> int | None:
    """只在无歧义时解析年份，否则 None（宁缺毋滥）。"""
    if not source:
        return None
    # 多年区间 → 不猜单一年份
    if _RANGE.search(source):
        return None
    fours = sorted(set(_FOUR.findall(source)))
    if len(fours) == 1:
        return int(fours[0])
    if len(fours) > 1:
        return None  # 歧义
    # 明确的「NN年」两位年份
    twos = _TWO_YEAR.findall(source)
    if len(twos) == 1:
        n = int(twos[0])
        if 9 <= n <= 29:  # 2009..2029
            return 2000 + n
    return None


def main() -> int:
    apply = "--apply" in sys.argv
    if not os.path.exists(DB_PATH):
        print(f"[ERR] 数据库不存在: {DB_PATH}")
        return 1
    print(f"数据库: {DB_PATH}")
    print(f"模式: {'APPLY(写库)' if apply else 'DRY-RUN(预览)'}\n")

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    rows = cur.execute("SELECT id, source FROM quiz_questions").fetchall()

    updates = []  # (paper, year, qno, id)
    paper_seq: dict[str, int] = {}
    stat_paper = stat_year = 0
    for qid, source in rows:
        paper = parse_paper(source)
        year = parse_year(source)
        qno = None
        if paper:
            paper_seq[paper] = paper_seq.get(paper, 0) + 1
            qno = paper_seq[paper]
            stat_paper += 1
        if year:
            stat_year += 1
        if paper or year:
            updates.append((paper, year, qno, qid))

    # 按 (paper, id) 重新计算 question_no，保证套卷内按 id 升序编号
    updates.sort(key=lambda u: (u[0] or "", u[3]))
    seq = {}
    final = []
    for paper, year, _qno, qid in updates:
        if paper:
            seq[paper] = seq.get(paper, 0) + 1
            qno = seq[paper]
        else:
            qno = None
        final.append((paper, year, qno, qid))

    print(f"总题目: {len(rows)}")
    print(f"将回填 paper(真题套卷): {stat_paper} 题，涉及 {len(paper_seq)} 份套卷")
    print(f"将回填 year(无歧义年份): {stat_year} 题")
    print(f"将回填 question_no(套卷内序号): {sum(1 for f in final if f[2])} 题\n")

    print("=== 套卷样例（前 15，按题数）===")
    top = sorted(paper_seq.items(), key=lambda kv: kv[1], reverse=True)[:15]
    for name, cnt in top:
        yr = ""
        # 找该套卷一个可解析年份做展示
        for p, y, q, i in final:
            if p == name and y:
                yr = f" [{y}]"
                break
        print(f"  {cnt:>4} 题  {name}{yr}")

    if not apply:
        print("\n[DRY-RUN] 未写库。确认无误后加 --apply 执行。")
        con.close()
        return 0

    # 备份
    bak_dir = os.path.join(_ROOT, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(bak_dir, f"kaoyan_pre_qmeta_{ts}.db")
    shutil.copy2(DB_PATH, bak)
    print(f"\n已备份数据库 → {bak}")

    cur.executemany(
        "UPDATE quiz_questions SET paper=?, year=?, question_no=? WHERE id=?",
        final,
    )
    con.commit()
    print(f"已更新 {cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(final)} 行。")

    # 校验
    p = cur.execute("SELECT COUNT(paper) FROM quiz_questions").fetchone()[0]
    y = cur.execute("SELECT COUNT(year) FROM quiz_questions").fetchone()[0]
    q = cur.execute("SELECT COUNT(question_no) FROM quiz_questions").fetchone()[0]
    print(f"校验 → paper 非空 {p} / year 非空 {y} / question_no 非空 {q}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
