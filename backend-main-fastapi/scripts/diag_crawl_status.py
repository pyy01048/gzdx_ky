# -*- coding: utf-8 -*-
"""爬取进度诊断脚本（独立运行，避免 bash SIGTERM）。"""
import json
import sys
import time

import psycopg

CONN = "postgresql://kaoyan:kaoyan_dev_2026@127.0.0.1:5432/kaoyan"


def main():
    time.sleep(1)
    conn = psycopg.connect(CONN, connect_timeout=5)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM kaoyan_schools WHERE deleted_at IS NULL")
    total = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM kaoyan_schools s WHERE deleted_at IS NULL AND EXISTS "
        "(SELECT 1 FROM kaoyan_majors m WHERE m.school_id=s.id AND m.enabled=true AND m.deleted_at IS NULL)"
    )
    with_major = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM kaoyan_majors WHERE enabled=true AND deleted_at IS NULL")
    major_cnt = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(DISTINCT LEFT(subject_code,2)) FROM kaoyan_majors "
        "WHERE enabled=true AND deleted_at IS NULL AND subject_code IS NOT NULL AND subject_code<>''"
    )
    cat_cnt = cur.fetchone()[0]
    conn.close()
    print(f"学校总数={total} 有专业={with_major} 无专业={total-with_major} 专业数={major_cnt} 覆盖门类数={cat_cnt}")

    # 断点
    try:
        st = json.load(open(r"D:\平台\backend-main-fastapi\data\spider_state\school_crawler_state.json", encoding="utf-8"))
        print(f"断点completed单元数={len(st.get('completed', []))}")
    except Exception as e:
        print(f"断点读取失败: {e}")


if __name__ == "__main__":
    main()