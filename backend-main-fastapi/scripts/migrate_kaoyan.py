# -*- coding: utf-8 -*-
"""建表迁移：创建考研择校数据中心的6张表。
用法: python scripts/migrate_kaoyan.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine, Base
# 导入所有模型确保表被注册
from models import (
    KaoyanSchool, KaoyanCollege, KaoyanMajor,
    KaoyanAdmission, KaoyanScoreLine, KaoyanSubject,
)

TABLES = ["kaoyan_schools", "kaoyan_colleges", "kaoyan_majors",
          "kaoyan_admissions", "kaoyan_scorelines", "kaoyan_subjects"]


def main():
    from sqlalchemy import inspect
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    created = []
    for t in TABLES:
        if t not in existing:
            created.append(t)
    if created:
        # 只创建不存在的表
        Base.metadata.create_all(engine, tables=[
            Base.metadata.tables[t] for t in created
        ])
        print(f"已创建表: {', '.join(created)}")
    else:
        print("所有表已存在，无需迁移")
    # 导入种子学科
    # 注意：写入 **Discipline**（disciplines 表），而不是 KaoyanSubject——
    # kaoyan_subjects 是 PG 视图（SELECT ... FROM disciplines），对视图 INSERT 会失败。
    from services.kaoyan.seed_txkyer import SEED_SUBJECTS
    from database import SessionLocal
    from core.models import Discipline
    db = SessionLocal()
    try:
        existing_codes = {s.code for s in db.query(Discipline).all()}
        added = 0
        for i, sub in enumerate(SEED_SUBJECTS):
            if sub["code"] not in existing_codes:
                db.add(Discipline(sort_order=i, **sub))
                added += 1
        if added:
            db.commit()
            print(f"已导入 {added} 个种子学科")
        else:
            print("学科已存在")
    finally:
        db.close()


if __name__ == "__main__":
    main()
