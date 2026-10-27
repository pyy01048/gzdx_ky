# -*- coding: utf-8 -*-
"""只读：导出「同题干冲突组」候选，供人工裁决。不做任何写操作。

冲突组定义：归一化签名相同、且answer 非空、且答案互斥。
签名归一化要点：把连续下划线填空位整体删除，使「保留了填空下划线的版本」
与「OCR 吃掉填空位的版本」能落到同一个签名上。
"""
from pathlib import Path
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict

# 路径按本文件位置推导（P0-B2：拆除机器专属绝对路径绑定）
_REPO = Path(__file__).resolve().parents[2]
DB = str(_REPO / "database" / "kaoyan.db")
OUT = str(_REPO / "backend-main-fastapi" / "data" / "diagnostics" / "quiz_conflicts_dump.json")


def norm(s):
    """内容归一化签名。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[_—－\-–]{2,}", "\x00", s)
    s = re.sub(r"[\s\u3000]+", "", s)
    s = s.replace("\x00", "")
    s = re.sub(r"[，。、；：？！（）()\[\]【】“”\"'‘’,.;:?!…·《》〈〉]", "", s)
    return s.lower()


def has_blank(s):
    """题干是否保留了填空下划线。"""
    if not s:
        return False
    return bool(re.search(r"[_—－]{2,}", unicodedata.normalize("NFKC", s)))


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cols = [
        "id", "content", "options", "answer", "analysis", "subject", "chapter",
        "source", "question_type", "is_junk", "verified", "confidence",
        "quality", "variant_group", "paper", "source_ids",
    ]
    rows = conn.execute("SELECT %s FROM quiz_questions" % ",".join(cols)).fetchall()

    groups = defaultdict(list)
    for r in rows:
        key = norm(r["content"])
        if len(key) < 4:
            continue
        groups[key].append({c: r[c] for c in cols})

    conflicts = []
    for key, members in groups.items():
        answered = [m for m in members if (m["answer"] or "").strip()]
        if len(answered) < 2:
            continue
        if len({(m["answer"] or "").strip() for m in answered}) < 2:
            continue
        blanks = {has_blank(m["content"]) for m in answered}
        conflicts.append(
            {
                "sig": key,
                "blank_asymmetry": len(blanks) > 1,  # True = 下划线不对称组
                "n_answered": len(answered),
                "members": sorted(members, key=lambda m: m["id"]),
            }
        )

    conflicts.sort(key=lambda g: (not g["blank_asymmetry"], g["members"][0]["id"]))
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(conflicts, f, ensure_ascii=False, indent=2)

    target = [g for g in conflicts if g["blank_asymmetry"]]
    print("全部冲突组:", len(conflicts))
    print("下划线不对称组(=用户所说 25 组):", len(target))
    print("纯 OCR 异体重复组(另需单独处理):", len(conflicts) - len(target))
    print("wrote", OUT)


if __name__ == "__main__":
    sys.exit(main())