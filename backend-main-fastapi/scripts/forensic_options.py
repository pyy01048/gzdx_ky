# -*- coding: utf-8 -*-
"""第2 处修复的取证脚本：验证选项到底丢在哪一步（只读，不写库）。

回答 team-lead 指定的三个问题：
  1. 原始文档里这些题的选项文字在不在？
  2. 如果在，是切题时丢的还是本来就没有？
  3. 如果在而丢了，丢在 extract_questions 的哪一步？

做法：对每条样本，回源文档定位原文 → 手工模拟 extract_questions 的
      切块/抽答案/抽选项三个阶段 → 打印每一步的中间产物。

用法：python scripts/forensic_options.py
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import qbank_builder as qb  # noqa: E402
from services import extraction_noise as E  # noqa: E402

DB = r"D:\平台\database\kaoyan.db"

SAMPLES = [7931, 1072, 244, 26, 308]

_CN = re.compile(r"[^一-鿿]")


def cn_key(s: str, n: int = 10) -> str:
    """取前 n 个汉字做匹配键，规避 OCR 差异与标点差异。"""
    return _CN.sub("", s or "")[:n]


def locate(doc_text: str, content: str, window: int = 400):
    """在源文档中定位题目原文，返回 (绝对位置, 片段)。失败返回 (None, "")。"""
    for n in (10, 8, 6):
        key = cn_key(content, n)
        if len(key) < n:
            continue
        i = doc_text.find(key)
        if i >= 0:
            return i, doc_text[i: i + window]
    return None, ""


def option_label_count(segment: str) -> int:
    """统计片段里的选项标签数（A./A、/A）/A）…）。"""
    return len(re.findall(r"(?:^|[\s，,。；;：:、（(\[\]【】])[A-F]\s*[、.．)）]", segment))


def main() -> int:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    for qid in SAMPLES:
        r = db.execute(
            "SELECT id, content, options, answer, source FROM quiz_questions"
            " WHERE id=?",
            (qid,),
        ).fetchone()
        src_name = (r["source"] or "").split(":", 1)[-1]
        stem = src_name.rsplit(".", 1)[0]
        d = db.execute(
            "SELECT id, content FROM documents WHERE file_name LIKE ?"
            " AND length(content)>0 ORDER BY length(content) LIMIT 1",
            (f"%{stem}%",),
        ).fetchone()

        print("=" * 78)
        print(f"#{qid}   source={r['source']}")
        print(f"  入库题干: {r['content'][:76]}")
        print(f"  入库选项: {r['options']}")
        print(f"  入库答案: {r['answer']}")

        if not d:
            print("  [源文档未找到]")
            continue
        doc_text = d["content"] or ""
        pos, seg = locate(doc_text, r["content"])
        print(f"  源文档: doc{d['id']}  定位={'成功 @'+str(pos) if pos is not None else '失败'}")
        if pos is None:
            print("  [源文档未匹配到该题，无法取证]")
            continue

        n_opt_src = option_label_count(seg)
        print(f"\n  【Q1】原始文档里选项文字在不在？ -> {'在' if n_opt_src >= 2 else '不在'}（片段内选项标签 {n_opt_src} 个）")
        print(f"  源片段: {seg[:230]!r}")

        # —— 模拟 extract_questions 的三个阶段 ——
        lines = doc_text.splitlines()
        line_of = pos
        # 阶段 A：sec_type 识别
        sec = ""
        for ln in lines[: line_of + 1]:
            m = qb._SECTION_RE.match(ln.strip())
            if m and qb._is_real_section_title(m.group(1)):
                sec = qb._norm_section(m.group(1))
        print(f"\n  【Q3】逐阶段追踪：")
        print(f"    阶段A 题型识别 sec_type = {sec!r}")

        # 阶段 B：抽选项（旧逻辑 vs 新逻辑）
        om = list(qb._OPTION_RE.finditer(seg))
        print(f"    阶段B 旧逻辑 _OPTION_RE 命中 {len(om)} 个标签；"
              f"旧条件 `sec_type in (选择,多选,判断)` = {sec in ('选择', '多选', '判断')}"
              f" → {'拆分' if om and sec in ('选择', '多选', '判断') else '不拆分（选项并入题干）'}")

        stem_new, opts_new = E.split_stem_and_options(seg, sec)
        print(f"    阶段B 新逻辑 split_stem_and_options -> 选项 {len(opts_new)} 个")
        if opts_new:
            for o in opts_new:
                print(f"        {o[:50]!r}")

        # 阶段 C：闸门
        ok, why = None, ""
        if opts_new:
            from services.quiz_content_gate import admit

            ok, why = admit(stem_new, options=opts_new, answer=r["answer"],
                            source=src_name, section_type=sec)
            print(f"    阶段C 闸门 admit -> {ok} ({why})")

        print(f"\n  【Q2】结论：", end="")
        if n_opt_src >= 2 and not r["options"]:
            print("源文档有选项但入库 options 为空 → 切题丢失")
        elif n_opt_src >= 2 and r["options"]:
            print("源文档有选项且已入库 → 未丢失")
        else:
            print("源文档本就无选项 → 不属于切题丢失")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())