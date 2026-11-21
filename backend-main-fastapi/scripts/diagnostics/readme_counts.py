# -*- coding: utf-8 -*-
"""README 数据口径：从库里出数（完善方案 12 §3.2）。

两种用法：

    python scripts/diagnostics/readme_counts.py                 # 打印计数，供人工核对
    python scripts/diagnostics/readme_counts.py --write-readme  # 写进 README 的 COUNTS 自动块

README 中必须有下面这对标记（脚本只替换块内内容，不会碰其它文字）::

    <!-- COUNTS:BEGIN ... -->
    <!-- COUNTS:END -->

项目铁律：README/面板/报告的数字**只允许**从这里出数，禁止手填（历次口径漂移的根因）。
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
REPO = BASE.parent
README = REPO / "README.md"

sys.path.insert(0, str(BASE))

from sqlalchemy import text  # noqa: E402

BEGIN = "<!-- COUNTS:BEGIN"
END = "<!-- COUNTS:END -->"

#: 指标 → (表名, where 条件, 中文标签)
METRICS = [
    ("quiz_questions", "is_available IS TRUE", "可用题目"),
    ("quiz_questions", "is_past_exam IS TRUE", "其中真题"),
    ("words", "1=1", "单词"),
    ("knowledge_chunks", "1=1", "知识分块"),
    ("knowledge_points", "1=1", "知识点"),
    ("documents", "1=1", "文档"),
    ("kaoyan_schools", "1=1", "院校"),
    ("kaoyan_majors", "1=1", "专业"),
    ("kaoyan_scorelines", "1=1", "分数线行"),
    ("papers", "1=1", "试卷"),
]


def _count(db, table: str, where: str = "1=1") -> int | None:
    try:
        return int(db.execute(text(f"select count(*) from {table} where {where}")).scalar())
    except Exception:  # noqa: BLE001 表不存在 → None（诚实标注，不静默当 0）
        return None


def collect() -> dict:
    from database import SessionLocal

    db = SessionLocal()
    try:
        tables = {
            r[0]
            for r in db.execute(text("select table_name from information_schema.tables where table_schema='public'"))
        }
        out = {}
        for table, where, label in METRICS:
            out[label] = _count(db, table, where) if table in tables else None
        return out
    finally:
        db.close()


def render_block(counts: dict) -> str:
    today = datetime.date.today().isoformat()
    lines = [
        f"{BEGIN}（自动生成，勿手改；刷新：python backend-main-fastapi/scripts/diagnostics/readme_counts.py --write-readme）-->",
        "",
        "| 指标 | 数值 | 口径日期 |",
        "|---|---|---|",
    ]
    for _, _, label in METRICS:
        value = counts.get(label)
        shown = "—（表不存在）" if value is None else f"{value:,}"
        lines.append(f"| {label} | {shown} | {today} |")
    lines += ["", END]
    return "\n".join(lines)


def write_readme(counts: dict) -> bool:
    if not README.exists():
        print(f"[x] 找不到 {README}")
        return False
    content = README.read_text(encoding="utf-8")
    start = content.find(BEGIN)
    end = content.find(END)
    if start == -1 or end == -1 or end < start:
        print("[x] README 缺少 COUNTS 标记块（<!-- COUNTS:BEGIN --> … <!-- COUNTS:END -->）")
        return False
    new = content[:start] + render_block(counts) + content[end + len(END) :]
    README.write_text(new, encoding="utf-8", newline="\n")
    print(f"[✓] 已刷新 {README} 的数据实况块")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-readme", action="store_true")
    args = ap.parse_args()

    counts = collect()
    print("== 核心计数 ==")
    for _, _, label in METRICS:
        print(f"{label:<10} = {counts.get(label)}")
    if args.write_readme:
        return 0 if write_readme(counts) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
