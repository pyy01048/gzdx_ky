"""清洗 knowledge_points 噪声 + 统一 subject 分类。

噪声类型（真实跑模型后观察到的）：
1. 纯序号：``(1)`` ``(2)`` ``1.`` ``2、``
2. 纯数字：``555`` ``834``（多为题号/分值）
3. 进制转换式：``(1)(25.7)_{10}``（OCR 破损的公式残片）
4. 过短无意义：单字母、纯标点

统一 subject 到项目主分类：
  408 / 数模电 / 信号与系统 / 公共课（政治·英语·数学·物理）

安全策略：
- 默认 dry-run；``--apply`` 才写库。
- 「栈」这类真知识点不删：只删「纯数字」「纯序号」「下标残片」。
- 写库前用 SQLite backup API 备份。

用法：
    python scripts/clean_knowledge_points.py
    python scripts/clean_knowledge_points.py --apply
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

# ---- 噪声判定（保守，宁可漏删不可误删） ----
_RE_ONLY_NUM = re.compile(r"^[\d\s]+$")                      # 555 / 78 79
_RE_ONLY_SEQ = re.compile(r"^[（(【\[]?\s*\d{1,2}\s*[)）】\].、,，]?$")  # (1) / 2、 / 3.
_RE_SUBSCRIPT = re.compile(r"^[\(（]?\d+[\)）]?[\(（]?[\d\.\{\}_a-zA-Z]{0,12}[\)）]?_\{?\d+\}?$")
_RE_ONLY_PUNCT = re.compile(r"^[\W_]+$", re.U)
_RE_CJK_MIN = re.compile(r"[一-龥]")

# 短符号但确有专业含义，不删（如 fH/fL 触发器参数、栈/队列等数据结构）
_KEEP_SHORT = {
    # 数据结构 / 电路
    "栈", "队列", "树", "图", "网", "串", "堆", "表",
    "fH", "fL", "d", "q", "cp", "clk", "en", "oe", "wr", "rd", "cs",
    # 数论 / 代数
    "熵", "码", "阵", "群", "环", "域", "积", "和", "差", "角", "相", "态",
    "键", "路", "门", "栅", "极", "阻", "容", "感", "场", "位", "线", "面",
    "体", "点", "段", "区", "层", "序", "率", "幅", "频", "谱", "波", "峰",
    "谷", "阶", "弧", "隙", "耗", "散", "增益", "带宽",
}

# ---- subject 归一 ----
_SUBJECT_MAP: Dict[str, str] = {
    # 408
    "计算机学科专业基础408": "408",
    "计算机组成原理": "408",
    "数据结构": "408",
    "操作系统": "408",
    "计算机网络": "408",
    # 数模电
    "数模电": "数模电",
    "数字电子技术": "数模电",
    "模拟电子技术": "数模电",
    "电路": "数模电",
    "电路分析": "数模电",
    "电路与电子技术": "数模电",
    "数字电路": "数模电",
    "模拟电路": "数模电",
    # 信号与系统
    "信号与系统": "信号与系统",
    "通信原理": "信号与系统",
    "光学与工程光学": "信号与系统",
    # 公共课
    "数学": "公共课",
    "政治": "公共课",
    "英语": "公共课",
    "普通物理": "公共课",
    "专业课": "专业课",
    "真题综合": "真题综合",
}


def backup(con: sqlite3.Connection) -> str:
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_kpclean_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    return bak


def is_noise(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True
    if n in _KEEP_SHORT:
        return False
    if _RE_ONLY_NUM.match(n):
        return True
    if _RE_ONLY_SEQ.match(n):
        return True
    if _RE_SUBSCRIPT.match(n) and not _RE_CJK_MIN.search(n):
        return True
    if _RE_ONLY_PUNCT.match(n):
        return True
    # 2 字以内且不含中文（如 "K1" "AB"）视为噪声
    if len(n) <= 2 and not _RE_CJK_MIN.search(n):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    rows = con.execute("SELECT id, name, subject FROM knowledge_points").fetchall()

    noisy = [(i, n, s) for i, n, s in rows if is_noise(n)]
    remap: List[Tuple[str, str, str]] = []  # (new_subject, id, old_subject)
    for i, n, s in rows:
        key = (s or "").strip()
        new = _SUBJECT_MAP.get(key)
        if new and new != key:
            remap.append((new, i, key))

    print(f"知识点总数: {len(rows)}")
    print(f"噪声待删: {len(noisy)}")
    for i, n, s in noisy[:20]:
        print(f"  #{i} 「{n}」 subj={s}")
    print(f"subject 需归一: {len(remap)}")

    from collections import Counter
    pairs = Counter((old, new) for new, i, old in remap)
    print("归一明细:")
    for (old, new), c in pairs.most_common():
        print(f"  {old} → {new}  ({c})")

    if args.apply:
        bak = backup(con)
        print(f"\n备份 → {bak}")
        ids = [i for i, _, _ in noisy]
        if ids:
            con.execute(
                f"DELETE FROM knowledge_points WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
            print(f"已删除噪声 {len(ids)} 条")
        upd: Dict[str, int] = {}
        for new, i, _ in remap:
            con.execute("UPDATE knowledge_points SET subject=? WHERE id=?", (new, i))
            upd[new] = upd.get(new, 0) + 1
        con.commit()
        print(f"subject 归一写入 {sum(upd.values())} 条: {upd}")

    left = con.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0]
    print(f"\n当前知识点总数: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
