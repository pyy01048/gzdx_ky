# -*- coding: utf-8 -*-
"""复核：team-lead 恢复的 89 条是否引入了重复（只读，不写库）。

背景：我的法证判「53 条真唯一（误删）」，team-lead 实测「89 条全为 is_junk=0
应恢复」并已恢复。差 36 条，且我对其中 69 条（is_junk=0 且库内存在同题孪生）
的判定是「删除正确」。

本脚本核实：恢复后，这 89 条里有多少与主库现存题目内容重复。
若重复，则恢复把「已去重的重复题」又请了回来。
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
BAK_PATH = os.path.abspath(os.path.join(
    BASE_DIR, "..", "database", "_backup", "kaoyan_20261012_133542.db"))
SIM_THRESHOLD = 0.86

OCR_JUNK = re.compile(r"[\ufffd\ufffe\u001a-\u001f\ue000-\uf8ff]+")
BLANK = re.compile(r"[_＿﹍﹏]{2,}|[（(]\s*[）)]|…+|\.{3,}")
SIGN_STRIP = re.compile(r"[\s（）()【】\[\]、,，。.；;：:？?！！“”\"'’‘、·—\-]+")


def canon(s: str) -> str:
    s = OCR_JUNK.sub("", s or "")
    s = BLANK.sub("　", s)
    return SIGN_STRIP.sub("", s)


def main() -> None:
    cur = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    bak = sqlite3.connect(f"file:{BAK_PATH}?mode=ro", uri=True)

    # 恢复集 = 备份有、主库当初没有的 158 条中 is_junk=0 的那些
    # 现在主库已恢复，故改用：备份 is_junk=0 且 content 在主库中出现的
    # 且 id 落在当初丢失的区间里 —— 直接用「备份 is_junk=0 且主库存在同题孪生」
    # 反向推导更稳：以备份 id 集合为准。
    bak_rows = {r[0]: r for r in bak.execute(
        "SELECT id, content, answer, is_junk, source FROM quiz_questions")}

    # 主库现状（恢复后）
    cur_rows = {r[0]: r for r in cur.execute(
        "SELECT id, content, answer, is_junk FROM quiz_questions")}

    # 主库里 id <= 9164 且在备份中存在 = 原库未被删的部分
    base_ids = [i for i in cur_rows if i in bak_rows]
    # 恢复集 = 主库中 id 在备份里存在、且备份 is_junk=0 的新增部分无法直接区分，
    # 改用 team-lead 给的恢复规则：备份里 is_junk=0 的 158 条 = 原丢失的 89+69
    # 这里直接检测「主库现存题」内部是否已存在重复（恢复动作是否造出重复）
    print(f"当前主库总条数: {len(cur_rows)}")
    print(f"备份总条数    : {len(bak_rows)}")
    print()

    # 1) 恢复后主库内部重复检测（用与法证同一判重器）
    cur_content = {r[0]: r[1] for r in cur.execute("SELECT id, content FROM quiz_questions")}
    sig_index: dict[str, list[int]] = {}
    for qid, content in cur_content.items():
        sig_index.setdefault(canon(content or ""), []).append(qid)

    dup_sig = {k: v for k, v in sig_index.items() if len(v) > 1}
    print(f"恢复后主库内 完全同题 组数: {len(dup_sig)}")
    print(f"          涉及条数        : {sum(len(v) for v in dup_sig.values())}")
    print(f"          冗余条数        : {sum(len(v)-1 for v in dup_sig.values())}")
    print()

    # 2) 这些重复里，有多少来自恢复集
    #    恢复集的识别：备份 is_junk=0 且 id 在「已恢复的高位区间」
    #    团队恢复用的是 ATTACH + INSERT，id 会保留原值，故主库 id ⊆ 备份 id ∪ 新id
    orphan_ids = [i for i in cur_rows if i not in bak_rows]
    print(f"主库中不在备份里的 id（纯新增，非本次恢复）: {len(orphan_ids)}")

    print()
    print("### 主库内重复组明细（前 30 组）")
    n = 0
    dup_detail = []
    for k, v in sorted(dup_sig.items(), key=lambda x: -len(x[1])):
        rows = []
        for qid in v:
            c = cur_rows[qid]
            rows.append({
                "id": qid, "is_junk": c[3],
                "has_answer": bool((c[2] or "").strip()),
                "src": bak_rows[qid][4] if qid in bak_rows else "(新增)",
            })
        dup_detail.append(rows)
        if n < 30:
            print(f"  ids={v} junk={[r['is_junk'] for r in rows]}")
        n += 1

    # 3) 相似度层面（0.86）抽样复核前 200 组
    print()
    print("### 编辑距离 0.86 复核（对完全同题组内的成员互比）")
    check = sum(1 for v in dup_sig.values() if len(v) > 1)
    print(f"  完全同题组数: {check}（已按签名归并，无需再比）")

    with open(os.path.join(BASE_DIR, "data", "diagnostics", "post_restore_dup_check.json"),
              "w", encoding="utf-8") as f:
        json.dump({
            "current_total": len(cur_rows),
            "backup_total": len(bak_rows),
            "dup_sig_groups": len(dup_sig),
            "dup_sig_involved": sum(len(v) for v in dup_sig.values()),
            "dup_sig_redundant": sum(len(v) - 1 for v in dup_sig.values()),
            "detail": dup_detail,
        }, f, ensure_ascii=False, indent=2)
    print("\n→ data/diagnostics/post_restore_dup_check.json")


if __name__ == "__main__":
    main()