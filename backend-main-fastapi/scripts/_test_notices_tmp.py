# -*- coding: utf-8 -*-
"""临时验证 v2：全量院校通知爬取（ENGINEERING 清单）+ 枚举/统计校验。执行后删除。"""
import sys
import logging

sys.path.insert(0, r"D:\平台\backend-main-fastapi")
logging.basicConfig(level=logging.ERROR)

from database import SessionLocal
from services.kaoyan.spider_notices import crawl_school_notices
from sqlalchemy import text

db = SessionLocal()
try:
    print("ENUM:", [r[0] for r in db.execute(text("SELECT unnest(enum_range(NULL::notice_type))")).fetchall()])
    r = crawl_school_notices(db_session=db, dry_run=False)
    db.commit()
    print("RESULT schools:", r.get("schools"), "notices:", r.get("notices"),
          "robots_skip:", r.get("skipped_robots"), "parse_fail:", r.get("parse_failed"))
    print("BY TYPE:", dict(db.execute(text("SELECT notice_type, COUNT(*) FROM kaoyan_notices GROUP BY notice_type")).fetchall()))
    print("total:", db.execute(text("SELECT COUNT(*) FROM kaoyan_notices")).scalar())
except Exception as e:
    db.rollback()
    print("OUTER", type(e).__name__, str(e)[:150])
finally:
    db.close()
