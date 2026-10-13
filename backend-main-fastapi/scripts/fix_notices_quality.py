# -*- coding: utf-8 -*-
"""kaoyan_notices 数据质量修复：日期回填 + 栏目名噪声清理。

背景（2026-10-12 实测）:
  采集写库后 1153 条公告中 845 条 publish_date 为空，其中：
  * 约 49 条日期藏在标题前缀/尾部（如 "03.27/2025 xxx"、"06 2026.09 xxx"、"xxx 05.22/2024"）；
  * 约 69 条标题本身就是导航栏目名（"硕士报名"/"复试信息"/"招生宣传"…≤4 字且无日期，
    URL 全部是栏目列表页）——不是公告，应删除。

两个动作（可单独执行）:
  --fix-dates   从标题前缀/尾部提取日期回填 publish_date，并把日期片段从标题剥离。
                无法确定年份的（如裸 "05.22"）不动——不伪造。
  --clean-noise 删除 `trim(title) 长度≤4 且 publish_date 为空` 的行（实测全为栏目名）。

通用:
  默认 dry-run 预览；--apply 才写库；
  备份用 sqlite backup API（真库为 WAL 模式，shutil.copy 会丢未合并数据）；
  审计日志 tools/datasource/notices_quality_audit.json。

用法:
  python scripts/fix_notices_quality.py                          # 预览两个动作
  python scripts/fix_notices_quality.py --fix-dates --apply      # 只回填日期
  python scripts/fix_notices_quality.py --clean-noise --apply    # 只清噪声
  python scripts/fix_notices_quality.py --fix-dates --clean-noise --apply
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = r"D:\平台\database\kaoyan.db"
AUDIT = Path(r"D:\平台\tools\datasource\notices_quality_audit.json")

# 日期模式（按优先级；均锚定在标题前缀，尾部模式单独处理）
PREFIX_PATTERNS = [
    # "03.27/2025 xxx" → 2025-03-27
    (re.compile(r"^\s*(\d{1,2})[.月]\s*(\d{1,2})\s*[/／]\s*(\d{4})\s*"), "mdy"),
    # "2026.09 xxx" / "2026年9月 xxx" → 2026-09（日缺省置 01）
    (re.compile(r"^\s*(\d{4})\s*[.年]\s*(\d{1,2})\s*月?\s*"), "ym"),
    # "06 2026.09 xxx"（序号 + 年.月）→ 2026-09
    (re.compile(r"^\s*\d{1,3}\s+(\d{4})\s*[.年]\s*(\d{1,2})\s*月?\s*"), "nym"),
    # "2026-10-09 xxx" / "2026/10/9 xxx" → 完整
    (re.compile(r"^\s*(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?\s*"), "ymd"),
]
# 尾部模式："xxx 05.22/2024" → 2024-05-22
SUFFIX_PATTERN = re.compile(r"[\s\-—]*(\d{1,2})[.月]\s*(\d{1,2})\s*[/／]\s*(\d{4})\s*$")


def _valid_ymd(y: int, m: int, d: int) -> bool:
    return 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31


def extract_date(title: str):
    """返回 (ISO日期或None, 剥离日期后的干净标题)。只在能确定完整日期时返回。"""
    t = (title or "").strip()
    for pat, kind in PREFIX_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        g = m.groups()
        if kind == "mdy":  # MM.DD/YYYY
            mm, dd, yy = int(g[0]), int(g[1]), int(g[2])
        elif kind == "ym":  # YYYY.MM（日缺省 01）
            yy, mm, dd = int(g[0]), int(g[1]), 1
        elif kind == "nym":  # 序号 YYYY.MM
            yy, mm, dd = int(g[0]), int(g[1]), 1
        else:  # ymd
            yy, mm, dd = int(g[0]), int(g[1]), int(g[2])
        if not _valid_ymd(yy, mm, dd):
            continue
        clean = t[m.end():].strip(" 　-—|·")
        return f"{yy:04d}-{mm:02d}-{dd:02d}", (clean or t)
    # 尾部："xxx 05.22/2024"
    m = SUFFIX_PATTERN.search(t)
    if m:
        mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_ymd(yy, mm, dd):
            clean = t[: m.start()].strip(" 　-—|·")
            return f"{yy:04d}-{mm:02d}-{dd:02d}", (clean or t)
    return None, t


def main():
    ap = argparse.ArgumentParser(description="kaoyan_notices 日期回填 + 噪声清理")
    ap.add_argument("--fix-dates", action="store_true", help="从标题提取日期回填 publish_date")
    ap.add_argument("--clean-noise", action="store_true", help="删除栏目名噪声行（标题≤4字且无日期）")
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = ap.parse_args()
    if not (args.fix_dates or args.clean_noise):
        ap.error("至少指定 --fix-dates 或 --clean-noise 之一")

    if args.apply:
        # WAL 模式：必须用 backup API，shutil.copy 会丢未合并数据
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = rf"D:\平台\database\kaoyan.db.bak_notices_q_{stamp}"
        src = sqlite3.connect(DB)
        dst = sqlite3.connect(bak)
        src.backup(dst)
        dst.close()
        print(f"已备份（backup API）→ {bak}")
    else:
        src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    cur = src.cursor()
    audit = {"time": datetime.now(timezone.utc).isoformat(), "apply": args.apply,
             "date_fixes": [], "noise_deleted": []}

    # ---------- 动作 1：日期回填 ----------
    if args.fix_dates:
        rows = cur.execute(
            "SELECT id, title FROM kaoyan_notices WHERE publish_date IS NULL OR publish_date=''"
        ).fetchall()
        hits = []
        for rid, title in rows:
            iso, clean = extract_date(title)
            if iso:
                hits.append((rid, title, iso, clean))
        print(f"[fix-dates] 可回填 {len(hits)}/{len(rows)} 条")
        for rid, title, iso, clean in hits[:10]:
            print(f"   #{rid} {title[:40]!r} → {iso} | 净标题: {clean[:36]!r}")
        if args.apply:
            for rid, _t, iso, clean in hits:
                cur.execute(
                    "UPDATE kaoyan_notices SET publish_date=?, title=? WHERE id=?",
                    (iso, clean, rid),
                )
            audit["date_fixes"] = [{"id": r, "iso": i, "title": t} for r, t, i, _c in hits]
            print(f"[fix-dates] 已写 {len(hits)} 条")

    # ---------- 动作 2：噪声清理 ----------
    if args.clean_noise:
        rows = cur.execute(
            "SELECT id, school_name, title, url FROM kaoyan_notices "
            "WHERE length(trim(title))<=4 AND (publish_date IS NULL OR publish_date='')"
        ).fetchall()
        print(f"[clean-noise] 栏目名噪声 {len(rows)} 条（标题≤4字且无日期）")
        for rid, sch, title, _u in rows[:10]:
            print(f"   #{rid} [{sch}] {title!r}")
        if args.apply:
            audit["noise_deleted"] = [{"id": r[0], "school": r[1], "title": r[2]} for r in rows]
            for rid, *_ in rows:
                cur.execute("DELETE FROM kaoyan_notices WHERE id=?", (rid,))
            print(f"[clean-noise] 已删除 {len(rows)} 条")

    if args.apply:
        src.commit()
        AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")
        tot = cur.execute("SELECT COUNT(*) FROM kaoyan_notices").fetchone()[0]
        sch = cur.execute("SELECT COUNT(DISTINCT school_id) FROM kaoyan_notices").fetchone()[0]
        nodate = cur.execute(
            "SELECT COUNT(*) FROM kaoyan_notices WHERE publish_date IS NULL OR publish_date=''"
        ).fetchone()[0]
        print(f"\n完成：notices 总数 {tot}（{sch} 所）；无日期剩余 {nodate}（{nodate*100//max(tot,1)}%）")
        print(f"审计 → {AUDIT}")
    else:
        print("\n[DRY-RUN] 未写库。加 --apply 执行（建议先 --fix-dates 后 --clean-noise 分两批）。")
    src.close()


if __name__ == "__main__":
    main()
