# -*- coding: utf-8 -*-
"""从 knowledge_points 批量生成正反面闪卡（命令行入口）。

用法：
    python scripts/generate_flashcards.py                  # 全量生成
    python scripts/generate_flashcards.py --subject 数学    # 仅指定科目
    python scripts/generate_flashcards.py --limit 100      # 最多生成 100 张
    python scripts/generate_flashcards.py --overwrite      # 重建已有关联的卡片

说明：保持 186 接口不变，本生成能力以 CLI + services.flashcard_gen 提供。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.flashcard_gen import generate_from_knowledge_points


def main() -> int:
    parser = argparse.ArgumentParser(description="从知识点批量生成闪卡")
    parser.add_argument("--subject", default=None, help="仅生成指定科目")
    parser.add_argument("--limit", type=int, default=None, help="最多生成张数")
    parser.add_argument("--overwrite", action="store_true", help="重建已有关联的卡片")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = generate_from_knowledge_points(
            db, subject=args.subject, limit=args.limit, overwrite=args.overwrite
        )
        print(
            f"生成 {result['generated']} 张闪卡，"
            f"跳过 {result['skipped_existing']} 个已存在知识点，"
            f"当前闪卡总数 {result['total']}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
