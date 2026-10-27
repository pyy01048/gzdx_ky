# -*- coding: utf-8 -*-
"""院校数据自动采集一体脚本（每日定时任务用，也可手动跑）。

三段式：
  A. 通知增量爬取：各校研究生院官网公告列表（幂等 upsert，新增/更新通知）
  B. 名单提取：对新通知跑「标题强过滤 + 表格/PDF 解析 + 质量门」
  C. 入库：kaoyan_admissions（人数/均分，data_source 溯源到通知 URL）

用法：
  python pipeline/notice_data_autofill.py            # 全流程（约 5-10 分钟）
  python pipeline/notice_data_autofill.py --extract-only   # 只跑 B+C（通知已爬好时）
输出：一行 JSON 摘要（给定时任务日志/晨报用）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    summary = {"notices": {}, "admissions": {}}
    db_ready = True
    try:
        from database import SessionLocal
        from services.kaoyan.spider_notices import crawl_school_notices, ensure_notices_schema

        s = SessionLocal()
        ensure_notices_schema(s)
        if "--extract-only" not in sys.argv:
            try:
                r = crawl_school_notices(db_session=s, dry_run=False)
                s.commit()
                summary["notices"] = {k: r.get(k) for k in ("schools", "notices", "parse_failed")}
            except Exception as e:  # noqa: BLE001
                s.rollback()
                summary["notices"] = {"error": str(e)[:120]}
        s.close()
    except Exception as e:  # noqa: BLE001
        db_ready = False
        summary["notices"] = {"fatal": str(e)[:120]}

    if db_ready:
        import io
        from contextlib import redirect_stdout

        from pipeline import notice_admission_crawler as mac

        buf = io.StringIO()
        with redirect_stdout(buf):
            mac.main(200)
        log = buf.getvalue()
        import ast

        for line in log.splitlines():
            if line.startswith("REPORT "):
                summary["admissions"] = ast.literal_eval(line[7:])
        summary["admissions"]["log_tail"] = log.strip().splitlines()[-6:]
    print("AUTOFILL_SUMMARY " + json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
