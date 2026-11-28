#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""贵州大学 834 真题导入回滚脚本（由 import_major_zhenti_pg.py 生成）。

删除本批次插入的 quiz_questions 行（按 external_id），并记录删除行数。
用法：python rollback_zhenti_import_20261120_213643.py
"""

import sys

sys.path.insert(0, r"D:\研途\gzdx_ky\backend-main-fastapi")
import psycopg
from scripts._conn import dsn

EXTERNAL_IDS = [
    "guizhou834-2016-12",
    "guizhou834-2016-13",
    "guizhou834-2016-14",
    "guizhou834-2016-16",
    "guizhou834-2016-17",
    "guizhou834-2016-18",
    "guizhou834-2016-20",
    "guizhou834-2016-21",
    "guizhou834-2016-22",
    "guizhou834-2017-12",
    "guizhou834-2017-13",
    "guizhou834-2017-14",
    "guizhou834-2017-15",
    "guizhou834-2017-16",
    "guizhou834-2017-17",
    "guizhou834-2017-18",
    "guizhou834-2017-19",
    "guizhou834-2017-20",
    "guizhou834-2017-21",
    "guizhou834-2017-22",
    "guizhou834-2018-12",
    "guizhou834-2018-13",
    "guizhou834-2018-14",
    "guizhou834-2018-15",
    "guizhou834-2018-16",
    "guizhou834-2018-17",
    "guizhou834-2018-18",
    "guizhou834-2018-22",
    "guizhou834-2018-23",
    "guizhou834-2019-12",
    "guizhou834-2019-13",
    "guizhou834-2019-14",
    "guizhou834-2019-15",
    "guizhou834-2019-16",
    "guizhou834-2019-17",
    "guizhou834-2019-18",
    "guizhou834-2019-20",
    "guizhou834-2019-21",
    "guizhou834-2019-23",
    "guizhou834-2020-1",
    "guizhou834-2020-2",
    "guizhou834-2020-3",
    "guizhou834-2020-4",
    "guizhou834-2020-5",
    "guizhou834-2020-6",
    "guizhou834-2020-7",
    "guizhou834-2020-8",
    "guizhou834-2020-9",
    "guizhou834-2020-10",
    "guizhou834-2020-11",
    "guizhou834-2020-12",
    "guizhou834-2020-13",
    "guizhou834-2020-14",
    "guizhou834-2020-15",
    "guizhou834-2020-16",
    "guizhou834-2020-17",
    "guizhou834-2020-18",
    "guizhou834-2021-1",
    "guizhou834-2021-2",
    "guizhou834-2021-3",
    "guizhou834-2021-4",
    "guizhou834-2021-5",
    "guizhou834-2021-6",
    "guizhou834-2021-7",
    "guizhou834-2021-8",
    "guizhou834-2021-9",
    "guizhou834-2021-10",
    "guizhou834-2021-11",
    "guizhou834-2021-13",
    "guizhou834-2021-15",
    "guizhou834-2021-17",
    "guizhou834-2021-18",
    "guizhou834-2021-19",
    "guizhou834-2021-20",
    "guizhou834-2021-23",
    "guizhou834-2021-25",
    "guizhou834-2021-26",
    "guizhou834-2023-1",
    "guizhou834-2023-2",
    "guizhou834-2023-3",
    "guizhou834-2023-4",
    "guizhou834-2023-5",
    "guizhou834-2023-7",
    "guizhou834-2023-8",
    "guizhou834-2023-9",
]
conn = psycopg.connect(dsn(), connect_timeout=10)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM quiz_questions WHERE external_id = ANY(%s::text[])", (EXTERNAL_IDS,))
print("回滚删除前命中行数:", cur.fetchone()[0])
cur.execute("DELETE FROM quiz_questions WHERE external_id = ANY(%s::text[])", (EXTERNAL_IDS,))
print("已删除行数:", cur.rowcount)
conn.commit()
conn.close()
