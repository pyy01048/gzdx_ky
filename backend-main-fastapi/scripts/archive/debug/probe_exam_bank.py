# -*- coding: utf-8 -*-
"""扫描「配套题库 / 真题精选」类文档，评估可抽取的选择题规模。

只读评估，不写库。用于决定是否投入解析器开发。
"""
import re
import sqlite3
import sys

DB = r"D:\平台\database\kaoyan.db"


def probe(content: str) -> dict:
    """探测文本中的选择题结构，返回计数。"""
    # 选项行：A．/ A. / A、 / A) 开头
    opt_lines = re.findall(r"(?m)^\s*[ABCD][．.、)）]\s*\S", content)
    # 答案标记
    ans_marks = len(re.findall(r"【答案】", content))
    # 解析标记
    exp_marks = len(re.findall(r"【解析】", content))
    # 院校年份标注 [XX大学2015研]
    tags = re.findall(r"\[([^\]]{2,30}?(\d{4})研)\]", content)
    return {
        "opt_lines": len(opt_lines),
        "ans_marks": ans_marks,
        "exp_marks": exp_marks,
        "tags": len(tags),
    }


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.text_factory = str
    try:
        rows = conn.execute(
            "SELECT id, file_name, length(coalesce(content,'')) AS l, content "
            "FROM documents "
            "WHERE (file_name LIKE '%配套题库%' OR file_name LIKE '%真题精选%' "
            "       OR file_name LIKE '%真题解析%') "
            "  AND length(coalesce(content,'')) > 20000 "
            "ORDER BY l DESC"
        ).fetchall()

        print(f"候选文档：{len(rows)} 篇\n")
        print(f"{'选项行':>7} {'答案':>5} {'解析':>5} {'院校标记':>8}  文件")
        print("-" * 100)

        total_opt = total_ans = 0
        good = 0
        for _id, name, _l, content in rows:
            p = probe(content or "")
            total_opt += p["opt_lines"]
            total_ans += p["ans_marks"]
            if p["opt_lines"] >= 8 and p["ans_marks"] >= 4:
                good += 1
            print(f"{p['opt_lines']:>7} {p['ans_marks']:>5} {p['exp_marks']:>5} "
                  f"{p['tags']:>8}  {name[:52]}")

        print("-" * 100)
        print(f"合计：选项行 {total_opt}，答案标记 {total_ans}")
        print(f"结构完整（选项≥8 且 答案≥4）的文档：{good} / {len(rows)}")
        print(f"按每题 4 选项估算可抽取题量：约 {total_opt // 4} 题")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
