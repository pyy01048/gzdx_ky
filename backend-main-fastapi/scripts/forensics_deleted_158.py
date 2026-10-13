# -*- coding: utf-8 -*-
"""核实 158 条被删的 quiz_questions 是否真为重复（只读，不写库）。

方法：
  1. 备份（13:35，9164 条）与当前库（9006 条）做 id 差集 → 精确定位被删的 158 条
  2. 对每条被删记录，在当前库中找"孪生"（同题的另一份拷贝）
     - 先用去乱码+去标点的完整签名做 O(1) 精确匹配
     - 匹配不到再退回编辑距离（0.86 阈值）与 is_junk=0 存量比对
  3. 判定：找不到孪生 = 真唯一内容 = 数据丢失；有孪生 = 真重复，删除正确
"""

from __future__ import annotations

import difflib
import os
import re
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
BAK_PATH = os.path.abspath(os.path.join(
    BASE_DIR, "..", "database", "_backup", "kaoyan_20261012_133542.db"))

OCR_JUNK = re.compile(r"[\ufffd\ufffe\u001a-\u001f\ue000-\uf8ff]+")
SIGN_STRIP = re.compile(r"[\s（）()【】\[\]、,，。.；;：:？?！！“”\"'’‘、·—\-]+")
# 填空位变体：同一道题里 "____" / "（  ）" / "＿＿＿＿" / "_________" 表示同一个空。
# 不归一化这些，会把「稳压管的稳压区是其工作在________。」（#156）
# 与「稳压管的稳压区是其工作在（ ）。（#172）」判成两道不同的题。
BLANK = re.compile(r"[_＿﹍﹏]{2,}|[（(]\s*[）)]|…+|\.{3,}")
SIM_THRESHOLD = 0.86


def canon(s: str) -> str:
    s = OCR_JUNK.sub("", s or "")
    s = BLANK.sub("　", s)          # 填空位统一成一个全角空格
    return SIGN_STRIP.sub("", s)


def main() -> None:
    cur = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    bak = sqlite3.connect(f"file:{BAK_PATH}?mode=ro", uri=True)

    old_ids = {r[0] for r in bak.execute("SELECT id FROM quiz_questions")}
    new_ids = {r[0] for r in cur.execute("SELECT id FROM quiz_questions")}
    gone = sorted(old_ids - new_ids)
    added = sorted(new_ids - old_ids)
    print(f"备份 {len(old_ids)} 条 / 当前 {len(new_ids)} 条")
    print(f"被删 {len(gone)} 条，新增 {len(added)} 条")
    print()

    # 当前库按完整签名建索引
    sig_index: dict[str, list[tuple[int, bool, int]]] = {}
    pool_norm: list[tuple[int, str, bool, int]] = []
    for qid, content, ans, junk in cur.execute(
            "SELECT id, content, answer, is_junk FROM quiz_questions"):
        s = canon(content)
        sig_index.setdefault(s, []).append((qid, bool((ans or "").strip()), int(junk or 0)))
        if not int(junk or 0):
            pool_norm.append((qid, s.lower(), bool((ans or "").strip()), int(junk or 0)))
    print(f"对照池（当前库 is_junk=0）: {len(pool_norm)} 条")

    qm = ",".join("?" * len(gone))
    deleted = bak.execute(
        f"SELECT id, content, answer, is_junk, source FROM quiz_questions "
        f"WHERE id IN ({qm})", gone).fetchall()

    true_dup = []       # 找到了孪生 → 删对了
    orphan = []         # 找不到孪生 → 真唯一内容
    for qid, content, ans, junk, source in deleted:
        s = canon(content)
        hit = sig_index.get(s)
        if hit:
            true_dup.append((qid, hit, "exact-sign"))
            continue
        sl = s.lower()
        if len(sl) >= 6:
            best_ratio, best_row = 0.0, None
            for pid, pn, pans, pjunk in pool_norm:
                # 先按长度粗筛，显著降低无谓的 SequenceMatcher 调用
                if not pn or abs(len(pn) - len(sl)) > max(len(sl), len(pn)) * 0.5:
                    continue
                r = difflib.SequenceMatcher(None, sl, pn).quick_ratio()
                if r < SIM_THRESHOLD:
                    continue
                r = difflib.SequenceMatcher(None, sl, pn).ratio()
                if r > best_ratio:
                    best_ratio, best_row = r, (pid, pans, pjunk)
            if best_ratio >= SIM_THRESHOLD and best_row:
                true_dup.append((qid, [best_row], f"edit-{best_ratio:.3f}"))
                continue
        orphan.append((qid, content, ans, junk, source))

    print()
    print("=" * 78)
    print(f"判定：真重复（找到孪生，删除正确）: {len(true_dup)} 条")
    print(f"      真唯一（找不到孪生，疑似误删）: {len(orphan)} 条")
    print("=" * 78)
    print()
    print("### 被删的 158 条构成")
    print(f"  is_junk=1        : {sum(1 for _, _, _, j, _ in deleted if j)}")
    print(f"  is_junk=0        : {sum(1 for _, _, _, j, _ in deleted if not j)}")
    print(f"  answer 非空      : {sum(1 for _, _, a, _, _ in deleted if (a or '').strip())}")
    print()
    print("### 真唯一（若非空即为数据丢失，应从备份恢复）明细")
    for qid, content, ans, junk, source in orphan:
        flag = "★有答案" if (ans or "").strip() else "  无答案"
        print(f"  #{qid} junk={junk} {flag}")
        print(f"     src: {source}")
        print(f"     题 : {(content or '')[:110]}")
    print()
    print("### 真重复（前 15 条，含保留的孪生 id）")
    for qid, hit, how in true_dup[:15]:
        print(f"  #{qid} ({how}) → 保留孪生 {hit}")

    out = {
        "deleted_ids": gone,
        "true_dup": [{"id": q, "hit": h, "how": w} for q, h, w in true_dup],
        "orphan": [{"id": q, "content": (c or "")[:300], "answer": a,
                    "is_junk": j, "source": s} for q, c, a, j, s in orphan],
    }
    import json
    with open(os.path.join(BASE_DIR, "data", "diagnostics", "deleted_158_forensics.json"),
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()