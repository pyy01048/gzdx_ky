# -*- coding: utf-8 -*-
"""从真实题库组装试卷（PostgreSQL 版）。

- 使用 services.paper_builder 的 build_paper + save_paper 组卷
- 按科目生成：数学、电路、数字电子技术、模拟电子技术、自动控制原理、政治
- 每科 1 套，每套 20 题，题型单选为主
- 补充 PG 特有的 year/paper_type/is_mock 字段（ORM 模型未同步这些列）
- 幂等：按 title 查重，已存在则跳过
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal  # noqa: E402
from services.paper_builder import build_paper, save_paper  # noqa: E402
from models import Paper  # noqa: E402

SUBJECTS = ["数学", "电路", "数字电子技术", "模拟电子技术", "自动控制原理", "政治"]

def main() -> int:
    parser = argparse.ArgumentParser(description="从题库组装试卷")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写库")
    parser.add_argument("--year", type=int, default=2024, help="试卷年份")
    parser.add_argument("--questions", type=int, default=20, help="每套题数")
    parser.add_argument("--paper-type", default="mock", help="paper_type: mock/real")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        for subject in SUBJECTS:
            title = f"{args.year}年考研{subject}模拟卷"
            # 幂等：按 title 查重
            exists = db.query(Paper).filter(Paper.title == title).first()
            if exists:
                print(f"[skip] {title} 已存在 (id={exists.id})")
                continue

            rules = {
                "subject": subject,
                "question_types": ["single"],
                "total_questions": args.questions,
            }
            result = build_paper(db, title=title, rules=rules, use_ai=False)
            if not result.get("ok"):
                print(f"[fail] {subject}: {result.get('message')}")
                continue

            print(f"[build] {subject}: 候选题→{len(result['items'])}题 总分{result['total_score']}")
            if args.dry_run:
                print("  dry-run 不写库")
                continue

            paper = save_paper(db, title=title, subject=subject,
                               description=f"{args.year}年考研{subject}模拟卷（自动组卷）",
                               rules=rules, items=result["items"])
            # 补充 PG 特有列（ORM 模型未映射）
            from sqlalchemy import text
            db.execute(
                text("UPDATE papers SET year=:y, paper_type=:pt, is_mock=:im WHERE id=:id"),
                {"y": args.year, "pt": args.paper_type, "im": args.paper_type == "mock", "id": paper.id},
            )
            db.commit()
            print(f"  -> 已写库 paper id={paper.id}")
    finally:
        db.close()
    return 0

if __name__ == "__main__":
    sys.exit(main())
