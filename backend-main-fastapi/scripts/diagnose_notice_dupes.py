"""kaoyan_notices 重复记录只读诊断脚本.

仅执行 SELECT, 不做任何写操作. 用于在执行不可逆清理前提供真实数据证据.

用法:
    python scripts/diagnose_notice_dupes.py [--full] [--out report.json]

参数:
    --full  打印全部重复组的完整构成 (默认只打印 top 30 组 + 统计汇总)
    --out   把完整结果写入 JSON 文件
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

DB_PATH = r"D:\平台\database\kaoyan.db"
TABLE = "kaoyan_notices"


def normalize_title(raw: str | None) -> str:
    """归一化通知标题.

    处理项: 全角转半角 / 首尾空白 / 去除括号内代码后缀 / 去除内部所有空白.
    与入库幂等逻辑 (services/kaoyan/notice_rules.yaml 同源实现) 保持一致.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    # 去除「(代码:10614)」「（代码：10614）」「[代码 10614]」这类括号代码后缀
    out_chars = []
    depth = 0
    buf = []
    for ch in text:
        if ch in "([（【":
            depth += 1
            buf.append(ch)
        elif ch in ")]）】":
            if depth > 0:
                depth -= 1
            buf.append(ch)
        else:
            buf.append(ch)
    stripped = "".join(buf)
    import re

    stripped = re.sub(r"[（(\[【]?\s*代\s*码\s*[:：]?\s*[0-9A-Za-z]{4,8}\s*[)）\]】]?", "", stripped)
    # 去除所有空白字符
    stripped = re.sub(r"\s+", "", stripped)
    return stripped.strip()


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_groups(conn: sqlite3.Connection) -> Dict[Tuple[Any, ...], List[sqlite3.Row]]:
    """按 (school_id, 原始标题) 分组, 只返回组内>1 的重复组."""
    rows = conn.execute(
        f"SELECT id, school_id, school_name, title, notice_type, publish_date, url, "
        f"source, fetched_at, importance_level, importance_score, deadline_date, "
        f"is_read, is_starred FROM {TABLE} ORDER BY id"
    ).fetchall()

    groups: Dict[Tuple[Any, ...], List[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        groups[(r["school_id"], r["title"])].append(r)
    return {k: v for k, v in groups.items() if len(v) > 1}


def classify(members: List[sqlite3.Row]) -> str:
    """判定一组重复记录的类型."""
    urls = {m["url"] for m in members}
    dates = {m["publish_date"] for m in members}
    norm_titles = {normalize_title(m["title"]) for m in members}
    if len(norm_titles) > 1:
        return "variant_title"  # (c) 标题有差异, 归一化后才相同
    if len(urls) == 1 and len(dates) == 1:
        return "exact"  # (a) 标题+URL+publish_date 全同
    if len(urls) > 1:
        return "url_diff"  # (b) 标题同 URL 不同
    return "other"


def fmt_row(m: sqlite3.Row) -> str:
    return (
        f"      id={m['id']:<6} url={str(m['url'])[:88]:<88} "
        f"pub={str(m['publish_date'])[:10]:<10} src={str(m['source'])[:14]:<14} "
        f"fetched={str(m['fetched_at'])[:19]:<19} lvl={str(m['importance_level']):<6} "
        f"read={m['is_read']} star={m['is_starred']}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    conn = connect(args.db)

    total = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    sum_read = conn.execute(f"SELECT COALESCE(SUM(is_read),0) FROM {TABLE}").fetchone()[0]
    sum_star = conn.execute(f"SELECT COALESCE(SUM(is_starred),0) FROM {TABLE}").fetchone()[0]
    print("=" * 110)
    print("kaoyan_notices 重复记录只读诊断")
    print("=" * 110)
    print(f"总记录数        : {total}")
    print(f"sum(is_read)    : {sum_read}")
    print(f"sum(is_starred) : {sum_star}")
    print(f"journal_mode    : {conn.execute('PRAGMA journal_mode').fetchone()[0]}")
    print()

    groups = fetch_groups(conn)
    print(f"重复组数(原始标题)     : {len(groups)}")
    print(f"涉及记录数             : {sum(len(v) for v in groups.values())}")
    print(f"冗余条数               : {sum(len(v) - 1 for v in groups.values())}")
    print()

    # ---- 归一化标题后的重复组 ----
    norm_groups: Dict[Tuple[Any, str], List[sqlite3.Row]] = defaultdict(list)
    for r in conn.execute(f"SELECT * FROM {TABLE} ORDER BY id"):
        norm_groups[(r["school_id"], normalize_title(r["title"]))].append(r)
    norm_groups = {k: v for k, v in norm_groups.items() if len(v) > 1}
    extra_groups = 0
    for k, v in norm_groups.items():
        raw_titles = {m["title"] for m in v}
        if len(raw_titles) > 1:
            extra_groups += 1
    print(f"归一化标题后重复组数   : {len(norm_groups)} (其中 {extra_groups} 组原始标题不一致, 属(c)类变体)")
    print(f"归一化后冗余条数       : {sum(len(v) - 1 for v in norm_groups.values())}")
    print()

    # ---- 分类统计 ----
    buckets: Dict[str, List[List[sqlite3.Row]]] = defaultdict(list)
    for k, members in norm_groups.items():
        buckets[classify(members)].append(members)

    print("-" * 110)
    print("分类统计 (按组数 / 涉及条数 / 冗余条数)")
    print("-" * 110)
    label = {
        "exact": "(a) 标题+URL+publish_date 全同  -> 纯重复",
        "url_diff": "(b) 标题同 URL 不同           -> 需判断是否真通知",
        "variant_title": "(c) 标题有差异, 归一化后同   -> 可考虑合并",
        "other": "(d) 其他 (URL同但日期不同等)",
    }
    for key in ["exact", "url_diff", "variant_title", "other"]:
        gs = buckets.get(key, [])
        if not gs:
            continue
        involved = sum(len(g) for g in gs)
        redundant = sum(len(g) - 1 for g in gs)
        print(f"{label[key]:<52} 组={len(gs):<4} 涉及={involved:<5} 冗余={redundant}")
    print()

    # ---- (b) 类逐组 url 证据 ----
    print("=" * 110)
    print("(b) 类：标题相同但 URL 不同 —— 全部逐组证据 (判断是否为不同年份/栏目的真通知)")
    print("=" * 110)
    for members in sorted(buckets.get("url_diff", []), key=len, reverse=True):
        school = members[0]["school_name"]
        print(f"\n  [{len(members)}条] {school} | {members[0]['title']}")
        for m in members:
            print(fmt_row(m))
        print(f"      -> 不同 url 数={len({m['url'] for m in members})}, "
              f"不同 publish_date 数={len({m['publish_date'] for m in members})}")
    print()

    # ---- (c) 类逐组证据 ----
    print("=" * 110)
    print("(c) 类：原始标题有差异, 归一化后相同")
    print("=" * 110)
    for members in sorted(buckets.get("variant_title", []), key=len, reverse=True):
        print(f"\n  [{len(members)}条] {members[0]['school_name']}")
        for t in sorted({m["title"] for m in members}):
            ids = [m["id"] for m in members if m["title"] == t]
            print(f"      标题: {t}   ids={ids}")
        print(f"      -> 不同 url 数={len({m['url'] for m in members})}, "
              f"不同 publish_date 数={len({m['publish_date'] for m in members})}")
    print()

    # ---- 西电专项 ----
    print("=" * 110)
    print("西电专项：392 条里有多少是重复堆出来的")
    print("=" * 110)
    xd = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE school_name LIKE '%西安电子科技%'"
    ).fetchone()[0]
    xd_groups = {k: v for k, v in norm_groups.items() if "西安电子科技" in v[0]["school_name"]}
    xd_dup_rows = sum(len(v) - 1 for v in xd_groups.values())
    print(f"西电总条数            : {xd}")
    print(f"西电重复组数          : {len(xd_groups)}")
    print(f"西电冗余条数          : {xd_dup_rows}")
    print(f"西电去重后应剩        : {xd - xd_dup_rows}")
    print(f"冗余占西电比例        : {xd_dup_rows / xd * 100:.1f}%")
    print()
    print("  西电各重复组 (>=5次) 及其 fetched_at 聚集情况:")
    for members in sorted(xd_groups.values(), key=len, reverse=True):
        if len(members) < 5:
            continue
        ts = Counter(str(m["fetched_at"])[:19] for m in members)
        print(f"\n  [{len(members)}条] {members[0]['title'][:60]}")
        print(f"      ids       : {[m['id'] for m in members]}")
        print(f"      url       : {sorted({str(m['url'])[:100] for m in members})}")
        print(f"      fetched_at: {dict(ts)}")
        print(f"      source    : {dict(Counter(str(m['source']) for m in members))}")
        print(f"      pub_date  : {dict(Counter(str(m['publish_date'])[:10] for m in members))}")
    print()

    print("  西电 fetched_at 时间戳聚集度 (全量):")
    xd_rows = conn.execute(
        f"SELECT fetched_at FROM {TABLE} WHERE school_name LIKE '%西安电子科技%'"
    ).fetchall()
    ts_counter = Counter(str(r["fetched_at"])[:19] for r in xd_rows)
    for ts, cnt in ts_counter.most_common(15):
        print(f"      {ts}  x{cnt}")
    print()

    # ---- 全库 fetched_at 聚集度 ----
    print("=" * 110)
    print("全库 fetched_at 时间戳 TOP15 (判断是否存在采集任务重复执行)")
    print("=" * 110)
    all_ts = Counter(
        str(r["fetched_at"])[:19]
        for r in conn.execute(f"SELECT fetched_at FROM {TABLE}").fetchall()
    )
    for ts, cnt in all_ts.most_common(15):
        print(f"      {ts}  x{cnt}")
    print()

    print("=" * 110)
    print("全库 source 分布")
    print("=" * 110)
    for s, cnt in conn.execute(
        f"SELECT COALESCE(source,'<NULL>'), COUNT(*) FROM {TABLE} GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(f"      {s:<30} {cnt}")
    print()

    print("=" * 110)
    print("全库重复组完整列表 (按重复次数降序)")
    print("=" * 110)
    ordered = sorted(norm_groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    show = ordered if args.full else ordered[:30]
    for idx, (key, members) in enumerate(show, 1):
        cls = classify(members)
        print(f"\n#{idx} [{len(members)}条][{cls}] {members[0]['school_name']} | {members[0]['title']}")
        print(f"     school_id={key[0]}  ids={[m['id'] for m in members]}")
        for m in members:
            print(fmt_row(m))
    if not args.full and len(ordered) > 30:
        print(f"\n  ...(仅显示前30组, 共{len(ordered)}组, 用 --full 查看全部)")

    if args.out:
        payload = {
            "total": total,
            "sum_read": sum_read,
            "sum_star": sum_star,
            "dup_groups": len(norm_groups),
            "dup_rows": sum(len(v) for v in norm_groups.values()),
            "redundant": sum(len(v) - 1 for v in norm_groups.values()),
            "by_class": {
                k: {
                    "groups": len(v),
                    "rows": sum(len(g) for g in v),
                    "redundant": sum(len(g) - 1 for g in v),
                }
                for k, v in buckets.items()
            },
            "groups": [
                {
                    "school_id": k[0],
                    "school_name": v[0]["school_name"],
                    "title": v[0]["title"],
                    "norm_title": k[1],
                    "class": classify(v),
                    "members": [
                        {
                            "id": m["id"],
                            "url": m["url"],
                            "publish_date": m["publish_date"],
                            "source": m["source"],
                            "fetched_at": m["fetched_at"],
                            "importance_level": m["importance_level"],
                            "is_read": m["is_read"],
                            "is_starred": m["is_starred"],
                        }
                        for m in v
                    ],
                }
                for k, v in ordered
            ],
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\n完整结果已写入: {args.out}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())