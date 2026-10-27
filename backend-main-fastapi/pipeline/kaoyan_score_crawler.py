# -*- coding: utf-8 -*-
"""掌上考研（kaoyan.cn）院校历年复试分数线采集。

接口（公开，无需登录）::

    POST https://api.kaoyan.cn/pc/school/schoolScore
    body {"school_id": "43", "year": 2025, "degree_type": ""}
    resp {"code": "0000", "data": [{id, depart_name, code, name, total,
          politics, english, special_one, special_two, note, year,
          degree_type, diff_total, special_remark}]}

degree_type: 1=专业型硕士，2=学术型硕士。
diff_total 为「院线总分 - 国家线」，故 national_line = total - diff_total。

写入 kaoyan_scorelines：special_one→math_line、special_two→major_line
（沿用既有数值列，展示层按「专业课一/专业课二」标注），source='kaoyan.cn'。

用法::

    python pipeline/kaoyan_score_crawler.py --dry-run --limit 3
    python pipeline/kaoyan_score_crawler.py --school-name 清华大学
    python pipeline/kaoyan_score_crawler.py --years 2022,2023,2024,2025,2026
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal  # noqa: E402
from models import KaoyanCollectionRun, KaoyanMajor, KaoyanSchool, KaoyanScoreLine  # noqa: E402
from utils.timeutil import naive_utc_iso  # noqa: E402

SCORE_API = "https://api.kaoyan.cn/pc/school/schoolScore"
CODE_JSON = "https://static.kaoyan.cn/json/school/code.json"
SOURCE = "kaoyan.cn"
LINE_TYPE = "院线"
DEGREE = {1: "专业型", 2: "学术型"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Origin": "https://www.kaoyan.cn",
    "Referer": "https://www.kaoyan.cn/",
    "Content-Type": "application/json",
}


def _norm_name(name: str) -> str:
    return (name or "").strip().replace("（", "(").replace("）", ")").replace(" ", "").replace("　", "")


def fetch_school_map(session: requests.Session) -> Dict[str, Tuple[int, str]]:
    r = session.get(CODE_JSON, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != "0000":
        raise RuntimeError(f"code.json 返回异常: {payload.get('code')}")
    out: Dict[str, Tuple[int, str]] = {}
    for code9, v in (payload.get("data") or {}).items():
        name = v.get("n")
        if name and v.get("id") is not None:
            out.setdefault(_norm_name(name), (int(v["id"]), code9))
    return out


def _to_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _to_str(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def normalize_row(raw: dict, school_id: int, year: int) -> Optional[dict]:
    total = _to_int(raw.get("total"))
    if total is None:
        return None
    diff = _to_int(raw.get("diff_total"))
    return {
        "school_id": school_id,
        "year": _to_int(raw.get("year")) or year,
        "total_line": total,
        "politics_line": _to_int(raw.get("politics")),
        "english_line": _to_int(raw.get("english")),
        "math_line": _to_int(raw.get("special_one")),
        "major_line": _to_int(raw.get("special_two")),
        "national_line": (total - diff) if diff is not None else None,
        "line_type": LINE_TYPE,
        "source": SOURCE,
        "major_code": _to_str(raw.get("code")),
        "major_name": _to_str(raw.get("name")),
        "depart_name": _to_str(raw.get("depart_name")),
        "degree_type": DEGREE.get(_to_int(raw.get("degree_type"))),
        "note": _to_str(raw.get("note")),
        "special_remark": _to_str(raw.get("special_remark")),
        "diff_total": diff,
        "source_id": _to_str(raw.get("id")),
    }


def fetch_year(session: requests.Session, kaoyan_id: int, year: int,
               retries: int = 3) -> List[dict]:
    body = {"school_id": str(kaoyan_id), "year": year, "degree_type": ""}
    last_err = None
    for attempt in range(retries):
        try:
            r = session.post(SCORE_API, json=body, timeout=40)
            r.raise_for_status()
            payload = r.json()
            if payload.get("code") != "0000":
                raise RuntimeError(f"code={payload.get('code')} msg={payload.get('message')}")
            data = payload.get("data") or []
            if not isinstance(data, list):
                raise RuntimeError(f"data 不是列表: {type(data).__name__}")
            return data
        except Exception as exc:  # noqa: BLE001 —— 单年失败重试后继续下一所
            last_err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"year={year} 失败: {last_err}")


def major_id_map(db, school_id: int) -> Dict[str, int]:
    """专业代码 → major_id，仅保留唯一匹配（同码多学院时无法一一对应）。"""
    rows = db.query(KaoyanMajor.id, KaoyanMajor.code).filter(
        KaoyanMajor.school_id == school_id).all()
    seen: Dict[str, List[int]] = {}
    for mid, code in rows:
        if code:
            seen.setdefault(code.strip(), []).append(mid)
    return {c: ids[0] for c, ids in seen.items() if len(ids) == 1}


def write_year(db, school_id: int, year: int, rows: List[dict],
               mid_map: Dict[str, int]) -> Tuple[int, int]:
    """整年替换：先取到数据再删旧行，避免请求失败时清空历史数据。"""
    code_count = Counter(r["major_code"] for r in rows if r.get("major_code"))
    for r in rows:
        code = r.get("major_code")
        # uq_scoreline(school_id, major_id, year, line_type) 要求同码唯一才能挂 major_id
        r["major_id"] = mid_map.get(code) if code and code_count[code] == 1 else None

    existed = db.execute(text(
        "SELECT count(*) FROM kaoyan_scorelines WHERE school_id=:s AND year=:y AND source=:src"
    ), {"s": school_id, "y": year, "src": SOURCE}).scalar() or 0

    db.execute(text(
        "DELETE FROM kaoyan_scorelines WHERE school_id=:s AND year=:y AND source=:src"
    ), {"s": school_id, "y": year, "src": SOURCE})

    cols = [
        "school_id", "major_id", "year", "total_line", "politics_line", "english_line",
        "math_line", "major_line", "national_line", "line_type", "source",
        "major_code", "major_name", "depart_name", "degree_type", "note",
        "special_remark", "diff_total", "source_id",
    ]
    if rows:
        db.execute(text(
            "INSERT INTO kaoyan_scorelines (" + ", ".join(cols) + ") VALUES ("
            + ", ".join(f":{c}" for c in cols) + ")"
        ), rows)
    return existed, len(rows)


def pick_schools(db, args) -> List[KaoyanSchool]:
    q = db.query(KaoyanSchool)
    if args.school_id:
        q = q.filter(KaoyanSchool.id.in_(args.school_id))
    if args.school_name:
        picked = []
        for name in args.school_name:
            s = db.query(KaoyanSchool).filter(KaoyanSchool.name == name).first()
            if s:
                picked.append(s)
            else:
                print(f"[SKIP] 库内无院校：{name}")
        return picked
    schools = q.order_by(KaoyanSchool.id).all()
    return schools[: args.limit] if args.limit else schools


def run(args) -> int:
    years = [int(y) for y in args.years.split(",") if y.strip()]
    db = SessionLocal()
    session = requests.Session()
    session.headers.update(_HEADERS)

    try:
        name_map = fetch_school_map(session)
        print(f"[MAP] 掌上考研院校 {len(name_map)} 所（按名称去重后）")

        schools = pick_schools(db, args)
        targets = []
        for s in schools:
            hit = name_map.get(_norm_name(s.name))
            if not hit:
                continue
            targets.append((s, hit[0]))
        if args.skip_existing:
            done = {
                sid for (sid,) in db.query(KaoyanScoreLine.school_id)
                .filter(KaoyanScoreLine.source == SOURCE).distinct()
            }
            before = len(targets)
            targets = [(s, kid) for s, kid in targets if s.id not in done]
            print(f"[SKIP] 已有数据的院校 {before - len(targets)} 所，跳过续采")
        print(f"[TARGET] 待采院校 {len(targets)} / 候选 {len(schools)}，年份 {years}")

        if args.dry_run:
            for s, kid in targets[:10]:
                print(f"  {s.id}\t{s.name}\tkaoyan_id={kid}")
            print(f"[DRY-RUN] 预计请求 {len(targets) * len(years)} 次")
            if targets and args.limit:
                probe = fetch_year(session, targets[0][1], years[0])
                print(f"[DRY-RUN] {targets[0][0].name} {years[0]} 行数 {len(probe)}")
                if probe:
                    print(json.dumps(probe[0], ensure_ascii=False)[:500])
            return 0

        started = naive_utc_iso()
        stats = {
            "schools_matched": len(targets),
            "school_years": 0,
            "rows_in": 0,
            "rows_replaced": 0,
            "empty": 0,
            "failed": [],
            "requests": 0,
        }
        for i, (school, kid) in enumerate(targets, 1):
            mid_map = major_id_map(db, school.id)
            school_rows = 0
            for year in years:
                if args.max_requests and stats["requests"] >= args.max_requests:
                    print(f"[STOP] 请求预算 {args.max_requests} 用尽，已采 {i - 1} 所")
                    _record_run(db, started, stats, "partial")
                    return 3
                try:
                    raw_rows = fetch_year(session, kid, year)
                    stats["requests"] += 1
                except Exception as exc:  # noqa: BLE001
                    stats["failed"].append({"school": school.name, "year": year, "error": str(exc)[:200]})
                    continue
                rows = [r for r in (normalize_row(raw, school.id, year) for raw in raw_rows) if r]
                if not rows:
                    stats["empty"] += 1
                    continue
                existed, written = write_year(db, school.id, year, rows, mid_map)
                db.commit()
                stats["school_years"] += 1
                stats["rows_in"] += written
                stats["rows_replaced"] += existed
                school_rows += written
                time.sleep(random.uniform(args.delay * 0.7, args.delay * 1.3))
            print(f"[{i}/{len(targets)}] {school.name}: {school_rows} 行")
            if i % 25 == 0:
                db.add(KaoyanCollectionRun(
                    source="kaoyan_cn_scores", scope="scorelines", item_type="scorelines",
                    row_count=stats["rows_in"], status="partial",
                    detail={"started_at": started, "progress": f"{i}/{len(targets)}",
                            "requests": stats["requests"]},
                ))
                db.commit()

        status = "success" if not stats["failed"] else "partial"
        _record_run(db, started, stats, status, finished=True)
        print(f"[DONE] 院校 {len(targets)}，写入 {stats['rows_in']} 行"
              f"（覆盖旧行 {stats['rows_replaced']}），空年份 {stats['empty']}，"
              f"失败 {len(stats['failed'])}，请求 {stats['requests']}")
        return 0 if not stats["failed"] else 1
    finally:
        db.close()


def _record_run(db, started: str, stats: dict, status: str, finished: bool = False) -> None:
    detail = {
        "started_at": started,
        "finished_at": naive_utc_iso() if finished else None,
        "schools_matched": stats["schools_matched"],
        "school_years": stats["school_years"],
        "rows": stats["rows_in"],
        "rows_replaced": stats["rows_replaced"],
        "empty_years": stats["empty"],
        "failed": stats["failed"][:50],
        "requests": stats["requests"],
    }
    db.add(KaoyanCollectionRun(
        source="kaoyan_cn_scores", scope="scorelines", item_type="scorelines",
        row_count=stats["rows_in"], status=status, detail=detail,
    ))
    db.commit()


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="掌上考研历年复试分数线采集")
    ap.add_argument("--years", default="2022,2023,2024,2025,2026")
    ap.add_argument("--school-id", type=int, action="append", help="仅采指定库内院校 id，可重复")
    ap.add_argument("--school-name", action="append", help="仅采指定院校名，可重复")
    ap.add_argument("--limit", type=int, default=0, help="最多采多少所（0=全部匹配）")
    ap.add_argument("--delay", type=float, default=0.6, help="请求间隔基准秒数")
    ap.add_argument("--max-requests", type=int, default=6000)
    ap.add_argument("--skip-existing", action="store_true", help="跳过已含 kaoyan.cn 分数线的院校（续采）")
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
