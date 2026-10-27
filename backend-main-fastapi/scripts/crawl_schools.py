# -*- coding: utf-8 -*-
"""院校公告采集 CLI。

用法
----
    # 只看队列状态（不抓取）
    python scripts/crawl_schools.py --stats

    # 试跑：不写库，只跑完整链路（抓取 → 抽取 → 分类 → 去重）
    python scripts/crawl_schools.py --dry-run --url https://yz.example.edu.cn/

    # 采集指定院校（官网来自 kaoyan_schools.official_url）
    python scripts/crawl_schools.py --school-id 12 --school-id 34 --limit 20

    # 从库里已有的公告 URL 重新采集
    python scripts/crawl_schools.py --from-notices --limit 50

参数
----
``--school-id``      可重复；指定院校 id
``--from-notices``   用 ``kaoyan_notices`` 里已有的 URL 作为采集目标
``--url``            可重复；直接给 URL（手工补采）
``--limit``          本批最多处理多少条（默认 5）
``--dry-run``        走完整流程但不写库
``--respect-robots/--no-robots``  默认尊重 robots.txt
``--stats``          只打印队列统计，不抓取

注意：真实落库依赖 ``models.CrawlJob`` / ``CrawlPage`` / ``CrawlDeadLetter``
（ingest-pipeline 同事定义）与 PostgreSQL 适配层 ``queue_pg.py``；
两者未就绪时，非 dry-run 会明确报错并退出（不会自己猜表结构建表）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.crawl.classifier import classify_notice  # noqa: E402
from services.crawl.extractor import extract  # noqa: E402
from services.crawl.fetcher import PoliteFetcher  # noqa: E402
from services.crawl.queue import (  # noqa: E402
    CrawlQueue,
    MemoryJobStore,
    _ModelsUnavailable,
)
from services.crawl.runner import (  # noqa: E402
    MemoryNoticeWriter,
    MemoryPageIndex,
    NullPageWriter,
    PgNoticeWriter,
    run_once,
)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="院校公告采集栈 CLI（抓取 → 抽取 → 分类 → 去重 → 入库）"
    )
    parser.add_argument("--school-id", action="append", type=int, default=None,
                        help="院校 id，可重复")
    parser.add_argument("--from-notices", action="store_true",
                        help="用 kaoyan_notices 里已有的 URL 作为采集目标")
    parser.add_argument("--url", action="append", default=None, help="直接指定 URL，可重复")
    parser.add_argument("--limit", type=int, default=5, help="本批最多处理多少条")
    parser.add_argument("--dry-run", action="store_true", help="不写库，只跑完整流程")
    robots = parser.add_mutually_exclusive_group()
    robots.add_argument("--respect-robots", dest="respect_robots", action="store_true",
                        default=True, help="尊重 robots.txt（默认）")
    robots.add_argument("--no-robots", dest="respect_robots", action="store_false",
                        help="不查 robots.txt（不推荐）")
    attach = parser.add_mutually_exclusive_group()
    attach.add_argument("--attachments", dest="attachments", action="store_true", default=True,
                        help="下载公告附件并解析 PDF（默认开，仅真实落库时生效）")
    attach.add_argument("--no-attachments", dest="attachments", action="store_false",
                        help="不下载附件")
    parser.add_argument("--stats", action="store_true", help="只打印队列统计")
    return parser.parse_args(argv)


def _school_rows(session, school_ids: Optional[List[int]]) -> List[Dict[str, Any]]:
    """取待采集院校（含官网地址与采集开关）。"""
    from sqlalchemy import text

    sql = (
        "SELECT s.id, s.name, s.official_url, "
        "       COALESCE(t.enabled, 1) AS enabled "
        "FROM kaoyan_schools s "
        "LEFT JOIN kaoyan_crawl_targets t ON t.school_id = s.id"
    )
    params: Dict[str, Any] = {}
    if school_ids:
        placeholders = ", ".join(f":sid{i}" for i in range(len(school_ids)))
        sql += f" WHERE s.id IN ({placeholders})"
        params = {f"sid{i}": sid for i, sid in enumerate(school_ids)}
    rows = session.execute(text(sql), params).fetchall()
    return [
        {
            "id": int(r[0]),
            "name": r[1],
            "official_url": r[2],
            "enabled": bool(r[3]) if r[3] is not None else True,
        }
        for r in rows
    ]


def _notice_targets(session, limit: int) -> List[Dict[str, Any]]:
    """从已有公告里取 URL 作为采集目标。"""
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT id, school_id, school_name, title, url FROM kaoyan_notices "
            "WHERE url IS NOT NULL AND url <> '' ORDER BY id DESC LIMIT :lim"
        ),
        {"lim": int(limit)},
    ).fetchall()
    return [
        {
            "id": int(r[0]),
            "school_id": r[1],
            "school_name": r[2],
            "title": r[3],
            "url": r[4],
        }
        for r in rows
    ]


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    from database import SessionLocal

    session = SessionLocal()
    try:
        # ---------------- 只看统计 ---------------- #
        if args.stats:
            try:
                queue = CrawlQueue(session)
            except _ModelsUnavailable as exc:
                print(json.dumps({"error": "models_unavailable", "detail": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 2
            print(json.dumps(queue.stats(), ensure_ascii=False, indent=2))
            return 0

        # ---------------- 准备队列 ---------------- #
        # dry-run 一律用内存队列：**什么都不写生产库**（连 crawl_jobs 都不写）。
        memory_queue = False
        if args.dry_run:
            memory_queue = True
            queue = CrawlQueue(store=MemoryJobStore())
        else:
            try:
                queue = CrawlQueue(session)
            except _ModelsUnavailable as exc:
                print(json.dumps(
                    {"error": "models_unavailable", "detail": str(exc),
                     "hint": "真实落库需要 models.CrawlJob/CrawlPage/CrawlDeadLetter "
                             "与 queue_pg.py 适配层；先用 --dry-run 试跑。"},
                    ensure_ascii=False, indent=2))
                return 2

        # ---------------- 播种任务 ---------------- #
        queued = 0
        seen = set()
        for school_id in args.school_id or []:
            for row in _school_rows(session, [school_id]):
                if not row["enabled"]:
                    continue
                url = (row["official_url"] or "").strip()
                if not url:
                    continue
                key = (f"school:{row['id']}", url)
                if key in seen:
                    continue
                seen.add(key)
                queue.enqueue(source_key=f"school:{row['id']}", url=url,
                              school_id=row["id"], job_type="notice")
                queued += 1

        if args.from_notices:
            for row in _notice_targets(session, max(args.limit * 5, args.limit)):
                url = (row["url"] or "").strip()
                if not url:
                    continue
                key = (f"notice:{row['id']}", url)
                if key in seen:
                    continue
                seen.add(key)
                queue.enqueue(source_key=f"notice:{row['id']}", url=url,
                              school_id=row["school_id"], job_type="notice")
                queued += 1

        for url in args.url or []:
            url = url.strip()
            if not url or ("url", url) in seen:
                continue
            seen.add(("url", url))
            queue.enqueue(source_key="manual", url=url, school_id=None, job_type="notice")
            queued += 1

        if not args.school_id and not args.from_notices and not args.url:
            print("[warn] 没有指定任何采集目标："
                  "用 --school-id / --from-notices / --url 至少给一个。", file=sys.stderr)
            return 1

        # ---------------- 跑一批 ---------------- #
        notice_writer = None
        page_writer = None
        page_index = None
        if args.dry_run:
            # dry-run：不写库，但用内存写入器统计"本来会写多少条"
            notice_writer = MemoryNoticeWriter()
            page_writer = NullPageWriter()
            page_index = MemoryPageIndex()
        else:
            from services.crawl.queue_pg import PgPageIndex, PgPageWriter

            notice_writer = PgNoticeWriter(session)
            page_writer = PgPageWriter(session)
            page_index = PgPageIndex(session)

        stats = run_once(
            session,
            limit=args.limit,
            respect_robots=args.respect_robots,
            write_pages=not args.dry_run,
            download_attachments=bool(args.attachments),
            queue=queue,
            page_index=page_index,
            page_writer=page_writer,
            notice_writer=notice_writer,
            fetcher=PoliteFetcher(),
            extract_fn=extract,
            classify_fn=classify_notice,
        )
        stats["queued"] = queued
        stats["dry_run"] = bool(args.dry_run)
        stats["memory_queue"] = memory_queue
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    finally:
        try:
            session.close()
        except Exception:  # pragma: no cover
            pass


if __name__ == "__main__":
    raise SystemExit(main())
