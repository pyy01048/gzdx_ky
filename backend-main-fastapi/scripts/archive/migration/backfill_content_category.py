# -*- coding: utf-8 -*-
"""V11 模块5：存量文档内容语义分层 backfill。

做三件事：
1. 幂等 ALTER TABLE documents ADD COLUMN content_category（可空 VARCHAR(20)，
   不影响存量、不破坏题库/真题）。新库由 models.Document 模型 + create_all 自动建列。
2. 按文件名（cheap、与 classify_content_category 同口径）给全部存量文档标注
   content_category：textbook / example / exam / method。
3. 分批 commit，打印各分类数量分布，并抽查 exam / example 样本。

用法：
    python scripts/backfill_content_category.py
"""
import os
import sys
import time
import collections

# 以脚本所在项目根目录为 import 根
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from sqlalchemy import text  # noqa: E402
from database import SessionLocal  # noqa: E402
from services.kb_service import classify_content_category  # noqa: E402


def ensure_column(db) -> bool:
    """幂等补 content_category 列。返回本次是否新增。"""
    conn = db.connection().connection
    cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "content_category" in cols:
        return False
    # 常驻服务可能短暂持写锁，有限重试
    for i in range(8):
        try:
            conn.execute(
                "ALTER TABLE documents ADD COLUMN content_category VARCHAR(20)"
            )
            break
        except Exception as e:  # noqa: BLE001
            if "locked" in str(e).lower() and i < 7:
                time.sleep(2)
                continue
            raise
    db.commit()
    # 补索引（与 ORM index=True 对齐；IF NOT EXISTS 幂等）
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_documents_content_category "
            "ON documents(content_category)"
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return True


def main() -> None:
    db = SessionLocal()
    try:
        added = ensure_column(db)
        print(f"[ALTER] content_category 列已就绪（本次新增={added}）")

        rows = db.execute(
            text("SELECT id, file_name FROM documents ORDER BY id")
        ).fetchall()
        total = len(rows)
        print(f"[BACKFILL] 待标注文档数: {total}")

        dist = collections.Counter()
        BATCH = 100
        buf = []
        for _id, name in rows:
            cat = classify_content_category(name or "")
            dist[cat] += 1
            buf.append((cat, _id))
            if len(buf) >= BATCH:
                db.execute(
                    text("UPDATE documents SET content_category = :c WHERE id = :i"),
                    [{"c": c, "i": i} for c, i in buf],
                )
                db.commit()
                buf.clear()
        if buf:
            db.execute(
                text("UPDATE documents SET content_category = :c WHERE id = :i"),
                [{"c": c, "i": i} for c, i in buf],
            )
            db.commit()

        print("[分布] content_category 各分类数量：")
        for k in ("exam", "example", "method", "textbook"):
            print(f"  {k:10s}: {dist.get(k,0)}")
        print(f"  {'合计':10s}: {sum(dist.values())}")

        # 抽查：每类取 5 个文件名，人工核对
        print("\n[抽查] exam 样本:")
        for r in db.execute(
            text("SELECT file_name FROM documents WHERE content_category='exam' LIMIT 8")
        ).fetchall():
            print("   -", r[0])
        print("[抽查] example 样本:")
        for r in db.execute(
            text("SELECT file_name FROM documents WHERE content_category='example' LIMIT 8")
        ).fetchall():
            print("   -", r[0])
        print("[抽查] method 样本:")
        for r in db.execute(
            text("SELECT file_name FROM documents WHERE content_category='method' LIMIT 5")
        ).fetchall():
            print("   -", r[0])
        print("[抽查] textbook 样本:")
        for r in db.execute(
            text("SELECT file_name FROM documents WHERE content_category='textbook' LIMIT 5")
        ).fetchall():
            print("   -", r[0])

        # 完整性自检：题库 / 块数不变
        q = db.execute(text("SELECT COUNT(*) FROM quiz_questions")).scalar()
        ch = db.execute(text("SELECT COUNT(*) FROM knowledge_chunks")).scalar()
        unlabeled = db.execute(
            text("SELECT COUNT(*) FROM documents WHERE content_category IS NULL")
        ).scalar()
        print(f"\n[完整性] quiz_questions={q}  knowledge_chunks={ch}  未标注文档={unlabeled}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
