# -*- coding: utf-8 -*-
"""kaoyan_notices.publish_date 回填 + 标题日期前缀剥离。

背景：
  2026-10-12 实测采集中发现部分高校（如上海交大）列表页把日期拼在锚文本
  开头（「03.27/2025 标题」「06 2026.09 标题」），解析器未拆出 →
  publish_date 为空且标题带数字前缀。
  本脚本用 services.kaoyan.spider_notices.extract_title_date_prefix
  对存量数据回填（同一函数，未来采集与存量清洗逻辑一致，避免口径漂移）。

判据（不伪造）：
  仅当标题前缀能确定完整年月日时才写 publish_date 并剥离前缀；
  年份无法确定 → 保持原样（publish_date 仍为空、标题不动）。

安全性：
  - 幂等：已处理的行重跑结果不变；
  - 默认 dry-run；--apply 才写库；
  - 备份用 sqlite3 连接级 backup API（真库为 WAL 模式，shutil.copy 会丢
    未 checkpoint 的 WAL 数据）；
  - 审计日志：逐行修改前后写入 CSV（与库同目录）。

用法：
  python scripts/fix_notices_date.py            # dry-run
  python scripts/fix_notices_date.py --apply    # 备份+写库+审计日志
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.kaoyan.spider_notices import extract_title_date_prefix  # noqa: E402

DB = r"D:\平台\database\kaoyan.db"


def backup_wal_safe(src_path: str) -> str:
    """WAL 安全备份：用 sqlite3 backup API（非 shutil.copy）。"""
    dst = f"{src_path}.bak_notices_date_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    src = sqlite3.connect(src_path)
    dst_con = sqlite3.connect(dst)
    with dst_con:
        src.backup(dst_con)
    dst_con.close()
    src.close()
    return dst


def phase_b_refetch(cur, dry: bool) -> tuple[int, int]:
    """Phase B：按校重抓列表页，解析日期后按标题匹配回填存量无日期行。

    背景：西电/清华等站日期是拆开的日期块（<div>17</div><div>2026-09</div>），
    旧解析器未提取。解析器已修复（_DAY_YM_RE），此处对存量数据重抓回填。
    仅更新能精确匹配标题的行；匹配不到的保持 NULL（不伪造）。
    返回 (更新行数, 仍无日期行数)。
    """
    from services.kaoyan.spider_notices import (
        _collect_notices, _fetch, ENGINEERING_NOTICE_URLS, KNOWN_SECTION_URLS,
    )
    import re as _re

    # 待回填的校与行
    rows = cur.execute(
        "SELECT id, school_name, title FROM kaoyan_notices "
        "WHERE publish_date IS NULL OR publish_date=''"
    ).fetchall()
    if not rows:
        return 0, 0
    by_school: dict[str, list] = {}
    for rid, sch, title in rows:
        by_school.setdefault(sch, []).append((rid, (title or "").strip()))

    n_upd = 0
    for sch, items in by_school.items():
        urls = []
        if sch in ENGINEERING_NOTICE_URLS:
            urls.append(ENGINEERING_NOTICE_URLS[sch])
        urls.extend(KNOWN_SECTION_URLS.get(sch, []))
        # 建标题→日期映射（只收有日期的解析结果；标题归一化去空白）
        t2d: dict[str, str] = {}
        for u in urls:
            m = _re.match(r"https?://([^/]+)", u)
            if not m:
                continue
            html = _fetch(u)
            if not html:
                continue
            for lk in _collect_notices(m.group(1), u, html, school=sch):
                if lk.get("publish_date") and lk.get("title"):
                    t2d.setdefault(_re.sub(r"\s+", "", lk["title"]), lk["publish_date"])
        if not t2d:
            continue
        for rid, title in items:
            d = t2d.get(_re.sub(r"\s+", "", title))
            if d:
                if not dry:
                    cur.execute(
                        "UPDATE kaoyan_notices SET publish_date=? WHERE id=? AND "
                        "(publish_date IS NULL OR publish_date='')",
                        (d, rid),
                    )
                n_upd += 1
    still = cur.execute(
        "SELECT COUNT(*) FROM kaoyan_notices WHERE publish_date IS NULL OR publish_date=''"
    ).fetchone()[0] if not dry else None
    return n_upd, (still if still is not None else -1)


def main() -> None:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    rows = cur.execute(
        "SELECT id, title, publish_date FROM kaoyan_notices"
    ).fetchall()

    plan = []      # (id, old_title, new_title, old_date, new_date)
    for rid, title, pdate in rows:
        new_date, new_title = extract_title_date_prefix(title or "")
        has_date = bool(pdate)
        if new_date and not has_date:
            plan.append((rid, title, new_title, pdate, new_date))
        elif new_date and has_date and new_title != title:
            # 已有日期但标题仍带前缀 → 只清洗标题，日期不动（不覆盖人工/更可靠来源）
            plan.append((rid, title, new_title, pdate, pdate))

    print(f"总行数: {len(rows)}")
    print(f"Phase A 计划更新: {len(plan)} 行（标题前缀日期，无网络）")

    # Phase B dry-run 统计（重抓网络，仅统计不写库）
    print("Phase B（重抓列表页按标题回填）统计中，请稍候…")
    b_upd, _ = phase_b_refetch(cur, dry=True)
    print(f"Phase B 可回填: {b_upd} 行")
    est_no_date = max(0, sum(1 for r in rows if not r[2]) - len(plan) - b_upd)
    est_total = len(rows)
    print(f"预估回填后 publish_date 非空率: {(est_total - est_no_date) / est_total * 100:.1f}%")

    # 格式命中统计
    from collections import Counter
    fmt = Counter()
    for _rid, _t, _nt, _od, nd in plan:
        if nd != _od:
            fmt[nd[:7]] += 1  # YYYY-MM
    print("补日期分布(YYYY-MM):", dict(sorted(fmt.items())[:12]), "…" if len(fmt) > 12 else "")

    print("\n样本(前 10):")
    for rid, ot, nt, od, nd in plan[:10]:
        print(f"  [{rid}] {ot[:44]!r}")
        print(f"      -> date={od!r}=>{nd!r}  title={nt[:44]!r}")

    if not apply:
        print("\n[DRY-RUN] 未写库。加 --apply 执行（先 WAL 安全备份 + 审计日志）。")
        con.close()
        return

    bak = backup_wal_safe(DB)
    print(f"\n已备份(WAL-safe) → {bak}")

    audit = Path(DB).parent / f"notices_date_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with open(audit, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "old_title", "new_title", "old_publish_date", "new_publish_date"])
        for row in plan:
            w.writerow(row)

    n_date = 0
    for rid, _ot, nt, _od, nd in plan:
        if nd != _od:
            cur.execute(
                "UPDATE kaoyan_notices SET title=?, publish_date=? WHERE id=?",
                (nt, nd, rid),
            )
            n_date += 1
        else:
            cur.execute("UPDATE kaoyan_notices SET title=? WHERE id=?", (nt, rid))
    con.commit()

    total = cur.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
    no_date = cur.execute(
        "SELECT COUNT(*) FROM kaoyan_notices WHERE publish_date IS NULL OR publish_date=''"
    ).fetchone()[0]
    print(f"完成。补日期 {n_date} 行；仅剥前缀 {len(plan) - n_date} 行。")
    print(f"notices 总 {total}，publish_date 非空率 {(total - no_date) / total * 100:.1f}%"
          f"（空 {no_date}）")
    print(f"审计日志 → {audit}")
    con.close()


if __name__ == "__main__":
    main()
