# -*- coding: utf-8 -*-
"""教材目录导入：textbooks_seed.json → PostgreSQL textbook 三表。

流程
----
1. 校验 seed 数据（书名/作者/阶段合法性）；
2. 解析 subject_code → subjects.id（缺失则报错，不静默跳过）；
3. 写入 textbooks，再按 schools 名单解析 → textbook_schools（院校名匹配
   kaoyan_schools，支持别名表）；
4. 回填 textbooks.school_count；
5. 输出导入报告（含未匹配院校清单，便于人工核对）。

红线
----
* 院校匹配不上**不猜**：记入报告 unmatched_schools，不硬塞 ID。
* 幂等：按 (title, edition, publisher) 去重，重复导入不产生重复行。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

SEED = BASE_DIR / "pipeline" / "textbooks_seed.json"
REPORT = BASE_DIR.parent / "data" / "textbook_import_report.json"

#: seed 里沿用的旧学科 code；线上 subjects.code 是导入后生成的 custom_*，
#: 因此除了 code，还要按中文名兜底解析，避免整本教材挂不上 subject_id。
LEGACY_SUBJECT_CODES = {
    "signals_systems": "信号与系统",
    "analog_electronics": "模拟电子技术",
    "digital_electronics": "数字电子技术",
}

#: 目录里出现的「非具体院校」写法，不参与院校关联
NON_SCHOOL_TOKENS = ("全国通用", "部分院校", "次主流", "最主流")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="教材目录导入 PG")
    p.add_argument("--database-url", default=None,
                   help="缺省走 pipeline.config.pg_database_url()：DATABASE_URL > .env 的 PG_* 分项")
    p.add_argument("--seed", default=str(SEED))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
    report: dict = {"books_inserted": 0, "books_skipped": 0,
                    "links_inserted": 0, "unmatched_schools": [],
                    "unmatched_subject_codes": [], "by_category": {}}

    with psycopg.connect(args.database_url or pg_database_url()) as pg:
        with pg.cursor() as cur:
            # 科目 code → id
            cur.execute("SELECT id, code, name FROM subjects")
            subj_rows = cur.fetchall()
            subj = {code: (sid, name) for sid, code, name in subj_rows}
            subj_by_name = {name: (sid, name) for sid, _code, name in subj_rows}
            # 院校名 + 别名 → id
            cur.execute("SELECT id, name FROM kaoyan_schools")
            school = {name: sid for sid, name in cur.fetchall()}
            cur.execute("SELECT alias, school_id FROM school_aliases")
            for alias, sid in cur.fetchall():
                school.setdefault(alias, sid)

        for cat in seed["categories"]:
            cat_stat = {"books": 0, "links": 0}
            # 类目级默认 subject_code（如「电路、模电、数电」按书单独指定）
            default_sc = cat.get("subject_code")
            for b in cat["books"]:
                sc = b.get("subject_code") or default_sc
                sid = None
                if sc:
                    if sc in subj:
                        sid = subj[sc][0]
                    elif LEGACY_SUBJECT_CODES.get(sc) in subj_by_name:
                        sid = subj_by_name[LEGACY_SUBJECT_CODES[sc]][0]
                    else:
                        report["unmatched_subject_codes"].append({"code": sc, "title": b["title"]})
                stages = [b["stage"]] if b["stage"] != "初试+复试" else ["初试", "复试"]
                if args.dry_run:
                    cat_stat["books"] += 1
                    continue
                with pg.cursor() as cur:
                    cur.execute(
                        """INSERT INTO textbooks
                             (title, subtitle, edition, authors, publisher, isbn,
                              subject_id, exam_stages, role, note, source, confidence, sort_order)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s::exam_stage[],%s,%s,%s,%s,%s)
                           ON CONFLICT DO NOTHING
                           RETURNING id""",
                        (b["title"], b.get("subtitle"), b.get("edition"), b["authors"],
                         b.get("publisher"), b.get("isbn"), sid,
                         "{" + ",".join(stages) + "}",
                         "main", b.get("note"), "manual_catalog",
                         "high" if "官方" in (b.get("scope") or "") else "medium",
                         cat_stat["books"]),
                    )
                    row = cur.fetchone()
                    if row is None:
                        # 已存在，取回 id（幂等）
                        cur.execute(
                            "SELECT id FROM textbooks WHERE title=%s AND COALESCE(edition,'')=%s "
                            "AND COALESCE(publisher,'')=%s",
                            (b["title"], b.get("edition") or "", b.get("publisher") or ""),
                        )
                        r2 = cur.fetchone()
                        if r2 is None:
                            report["books_skipped"] += 1
                            continue
                        bid = r2[0]
                        report["books_skipped"] += 1
                    else:
                        bid = row[0]
                        report["books_inserted"] += 1
                    cat_stat["books"] += 1
                    # 院校关联
                    for sname in b.get("schools", []):
                        if any(t in sname for t in NON_SCHOOL_TOKENS):
                            continue
                        sid_school = school.get(sname)
                        if sid_school is None:
                            report["unmatched_schools"].append(
                                {"school": sname, "textbook": b["title"]})
                            continue
                        for st in stages:
                            cur.execute(
                                """INSERT INTO textbook_schools
                                     (textbook_id, school_id, usage_note, exam_stage, is_official)
                                   VALUES (%s,%s,%s,%s::exam_stage,%s)
                                   ON CONFLICT DO NOTHING""",
                                (bid, sid_school, b.get("scope"), st,
                                 "指定" in (b.get("scope") or "") or "专用" in (b.get("scope") or "")),
                            )
                            report["links_inserted"] += 1
                            cat_stat["links"] += 1
                pg.commit()
            report["by_category"][cat["name"]] = cat_stat

        if not args.dry_run:
            # 回填使用广度
            with pg.cursor() as cur:
                cur.execute(
                    "UPDATE textbooks t SET school_count = "
                    "(SELECT COUNT(DISTINCT school_id) FROM textbook_schools s WHERE s.textbook_id=t.id)"
                )
            pg.commit()

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n报告：{REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
