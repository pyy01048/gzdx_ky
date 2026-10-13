"""恢复 knowledge_points.subject 的细分学科口径。

背景（2026-10-12）：为消除「模型吐书名当学科」的长尾污染，
clean_knowledge_points.py 把 subject 粗粒度归一成了 数模电/公共课/408，
但这破坏了 taxonomy 的细分学科体系：
  CORE_SUBJECTS = [数字电子技术, 模拟电子技术, 数学, 英语, 政治, 真题综合]
结果知识地图里「数字电子技术」「数学」「英语」「政治」分支全空
（数电 2335 道题、9791 个知识块在图上完全消失）。

修复策略：
  1. 从备份 kaoyan_pre_kpclean_*.db 按 id 还原原始 subject（最可靠）
  2. 备份中不存在的（后续抽取新增的）按章节/名称推断细分学科
  3. 只把真正的垃圾学科（书名等）映射到细分学科，不做粗粒度合并

用法：
    python scripts/restore_kp_subject.py
    python scripts/restore_kp_subject.py --apply
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))

# 细分学科（与 services/taxonomy.py CORE/MAJOR/EXT 对齐）
DIGITAL = "数字电子技术"
ANALOG = "模拟电子技术"
CS408 = "计算机学科专业基础408"

_DIGITAL_KW = ("逻辑", "门电路", "触发器", "计数器", "寄存器", "组合", "时序",
               "编码", "译码", "加法器", "存储器", "RAM", "ROM", "ADC", "DAC",
               "卡诺", "真值表", "与或", "或非", "与非", "异或", "CMOS", "TTL",
               "进制", "BCD", "数模", "模数", "波形", "555", "VHDL", "时钟")
_ANALOG_KW = ("放大", "运放", "运算放大", "功放", "功率放大", "反馈", "稳压",
              "整流", "滤波", "三极管", "二极管", "场效应", "晶体管", "偏置",
              "静态工作点", "频率响应", "差分", "共射", "共集", "共基", "振荡",
              "直流电源", "半导体", "小信号")
_MATH_KW = ("积分", "微分", "极限", "矩阵", "向量", "级数", "方程", "函数",
            "概率", "统计", "导数", "线性代数", "高数", "数列")
_EN_KW = ("词汇", "单词", "语法", "阅读", "翻译", "作文", "时态", "从句", "长难句")
_POL_KW = ("马原", "毛概", "思修", "史纲", "马克思主义", "政治", "唯物", "辩证",
           "社会主义", "近代史")


def infer(subject: str, chapter: str, name: str) -> str:
    """把粗粒度/垃圾学科归到细分学科。"""
    s = (subject or "").strip()
    ctx = f"{chapter or ''} {name or ''} {s}"

    # 已是细分学科
    if s in (DIGITAL, ANALOG, CS408, "数学", "英语", "政治", "真题综合",
             "电路", "电路分析", "信号与系统", "通信原理", "光学与工程光学",
             "光学", "普通物理", "网络补充", "其他"):
        return s

    if re.search(r"408|计算机|数据结构|操作系统|计算机网络|组成原理", s):
        return CS408
    if s == "数模电" or re.search(r"数电|数字电子|模拟电子|模电", s):
        d = sum(1 for k in _DIGITAL_KW if k in ctx)
        a = sum(1 for k in _ANALOG_KW if k in ctx)
        return DIGITAL if d >= a else ANALOG
    if s == "公共课":
        e = sum(1 for k in _EN_KW if k in ctx)
        p = sum(1 for k in _POL_KW if k in ctx)
        m = sum(1 for k in _MATH_KW if k in ctx)
        best = max((m, "数学"), (e, "英语"), (p, "政治"), key=lambda x: x[0])
        return best[1] if best[0] > 0 else "数学"
    # 垃圾学科（书名等）→ 按上下文推断
    if re.search(r"真题|试题|试卷", ctx):
        d = sum(1 for k in _DIGITAL_KW if k in ctx)
        a = sum(1 for k in _ANALOG_KW if k in ctx)
        if d + a > 0:
            return DIGITAL if d >= a else ANALOG
    if re.search(r"数学|高数", ctx):
        return "数学"
    if re.search(r"英语", ctx):
        return "英语"
    if re.search(r"政治", ctx):
        return "政治"
    return "其他"


def backup(con: sqlite3.Connection) -> str:
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_kpsubjrestore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    return bak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    baks = sorted(glob.glob(os.path.join(BASE_DIR, "data", "backups",
                                         "kaoyan_pre_kpclean_*.db")))
    if not baks:
        print("找不到 kpclean 备份")
        return 1
    src = sqlite3.connect(baks[0])
    orig = dict(src.execute("SELECT id, subject FROM knowledge_points").fetchall())
    print(f"备份 {baks[0]} 含 {len(orig)} 条原始 subject")

    con = sqlite3.connect(DB_PATH, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    rows = con.execute("SELECT id, subject, chapter, name FROM knowledge_points").fetchall()

    updates = []
    for i, s, ch, nm in rows:
        if i in orig and orig[i]:
            new = orig[i]
        else:
            new = infer(s, ch, nm)
        if new != s:
            updates.append((i, s, new))

    from collections import Counter
    print(f"待更新 {len(updates)} 条")
    for (old, new), c in Counter((o, n) for _, o, n in updates).most_common():
        print(f"  {old} → {new}  ({c})")

    if args.apply and updates:
        bak = backup(con)
        print(f"\n备份 → {bak}")
        con.execute("BEGIN")
        for i, _, new in updates:
            con.execute("UPDATE knowledge_points SET subject=? WHERE id=?", (new, i))
        con.commit()
        print(f"已更新 {len(updates)} 条")

    print("\n=== 复核（当前 subject 分布）===")
    for r in con.execute("SELECT subject, count(*) FROM knowledge_points "
                         "GROUP BY subject ORDER BY 2 DESC"):
        print(f"  {r[0]}: {r[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
