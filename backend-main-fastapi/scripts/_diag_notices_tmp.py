# -*- coding: utf-8 -*-
"""临时诊断：通知行数按校分布 + id 范围。执行后删除。"""
import sys

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print("total:", db.execute(text("SELECT COUNT(*) FROM kaoyan_notices")).scalar())
    print("id range:", db.execute(text("SELECT MIN(id), MAX(id) FROM kaoyan_notices")).fetchone())
    rows = db.execute(text(
        "SELECT school_name, COUNT(*) FROM kaoyan_notices GROUP BY school_name ORDER BY 2 DESC LIMIT 12"
    )).fetchall()
    for r in rows:
        print(r[0], r[1])
    print("fetch_at range:", db.execute(text("SELECT MIN(fetched_at), MAX(fetched_at) FROM kaoyan_notices")).fetchone())
finally:
    db.close()
