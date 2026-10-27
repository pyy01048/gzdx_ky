# -*- coding: utf-8 -*-
"""临时冒烟：/api/kaoyan/notices/stats 的函数逻辑。执行后删除。"""
import sys

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
from database import SessionLocal
from routers.kaoyan import notices_center_stats

db = SessionLocal()
try:
    r = notices_center_stats(db)
    print("STATS:", r)
finally:
    db.close()
