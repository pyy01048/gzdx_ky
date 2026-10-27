# -*- coding: utf-8 -*-
"""临时验证：院校简介回填结果。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import engine
from sqlalchemy import text

conn = engine.connect()
try:
    r = conn.execute(text("SELECT COUNT(*) FROM kaoyan_schools WHERE level IN ('985','211','双一流') AND (intro IS NULL OR intro='')"))
    print("重点院校缺简介:", r.scalar())
    r2 = conn.execute(text("SELECT COUNT(*) FROM kaoyan_schools WHERE intro IS NOT NULL AND intro<>''"))
    print("有简介院校总数:", r2.scalar())
    r3 = conn.execute(text("SELECT name, LEFT(intro, 40) FROM kaoyan_schools WHERE id IN (6, 273, 275, 317, 363)"))
    for row in r3.fetchall():
        print("sample:", row)
finally:
    conn.close()