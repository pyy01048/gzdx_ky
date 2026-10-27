# -*- coding: utf-8 -*-
"""回填 kaoyan_schools.official_url —— 用采集器的研究生院官网映射表写入真实 URL。

背景：
  真库 kaoyan_schools 现有 583 所，official_url 多为研招网 schId 纯数字（如 "368495"）
  或研招网 sch 页（https://yz.chsi.com.cn/sch/xxx.jhtml），并非学校真实官网。
  采集器 services/kaoyan/spider_notices.py 的 ENGINEERING_NOTICE_URLS 维护了
  经联网核验的研究生院官网入口。

写入规则（幂等 + 保守）：
  1. 仅当 official_url 为空 或 为纯数字(schId) 或 为研招网 sch 页时，才写入真实官网 URL；
  2. 已有真实官网 URL（非研招网、非纯数字）不覆盖；
  3. 目标 URL 与现值相同时跳过（幂等）。

用法：
  python scripts/backfill_school_official_url.py            # dry-run（默认，不写库）
  python scripts/backfill_school_official_url.py --apply    # 先备份真库再写
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# 真库路径（勿用 backend-main-fastapi/data/kaoyan.db 诱饵库）
DB = r"D:\平台\database\kaoyan.db"

# 复用的官网映射表（采集器单一数据源，避免两处维护漂移）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.kaoyan.spider_notices import ENGINEERING_NOTICE_URLS  # noqa: E402

# 视为「非真实官网、可覆盖」的占位值特征
_YT_SCH_RE = re.compile(r"^https?://yz\.chsi\.com\.cn/", re.I)   # 研招网 sch 页
_PURE_NUM_RE = re.compile(r"^\d+$")                               # 纯数字 schId


def is_placeholder(value) -> bool:
    """判断 official_url 现值是否为「占位/非真实官网」（可被覆盖）。"""
    if value is None:
        return True
    v = str(value).strip()
    if v == "":
        return True
    if _PURE_NUM_RE.match(v):
        return True
    if _YT_SCH_RE.match(v):
        return True
    return False


def normalize(url: str) -> str:
    """统一为 https 绝对 URL，去尾部冗余。"""
    u = (url or "").strip()
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    return u


def main() -> None:
    apply = "--apply" in sys.argv
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    rows = cur.execute(
        "SELECT id, name, official_url FROM kaoyan_schools"
    ).fetchall()
    by_name = {r[1]: r for r in rows}

    plan = []          # (sid, name, old, new)
    missing = []       # 在映射表但库中无此院校名
    skipped_kept = []  # 已有真实官网，保留不动
    for name, url in ENGINEERING_NOTICE_URLS.items():
        target = normalize(url)
        row = by_name.get(name)
        if row is None:
            missing.append(name)
            continue
        sid, _n, old = row
        if not is_placeholder(old):
            skipped_kept.append((name, old))
            continue
        if normalize(str(old)) == target:
            continue  # 幂等：值相同
        plan.append((sid, name, old, target))

    print(f"映射表院校数: {len(ENGINEERING_NOTICE_URLS)}")
    print(f"库中院校总数: {len(rows)}")
    print(f"计划写入: {len(plan)} 所")
    print(f"已有真实官网(保留): {len(skipped_kept)} 所")
    print(f"映射表有但库中无此名: {len(missing)} 所 -> {missing}")
    print("\n写入样本(前 12):")
    for sid, name, old, new in plan[:12]:
        print(f"  [{sid}] {name:16s} {old!r:28s} -> {new}")

    if not apply:
        print("\n[DRY-RUN] 未写库。加 --apply 执行（会先备份真库）。")
        con.close()
        return

    # 备份真库
    bak = f"{DB}.bak_official_url_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(DB, bak)
    print(f"\n已备份真库 → {bak}")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    for sid, name, _old, new in plan:
        cur.execute(
            "UPDATE kaoyan_schools SET official_url=?, updated_at=? WHERE id=?",
            (new, ts, sid),
        )
    con.commit()

    # 复核
    n_http = cur.execute(
        "SELECT COUNT(*) FROM kaoyan_schools WHERE official_url LIKE 'http%'"
    ).fetchone()[0]
    n_num = cur.execute(
        "SELECT COUNT(*) FROM kaoyan_schools "
        "WHERE official_url GLOB '[0-9]*' AND official_url NOT LIKE '%http%'"
    ).fetchone()[0]
    n_null = cur.execute(
        "SELECT COUNT(*) FROM kaoyan_schools "
        "WHERE official_url IS NULL OR official_url=''"
    ).fetchone()[0]
    print(f"完成。official_url 分布: http*={n_http}, 纯数字={n_num}, 空={n_null}")
    con.close()


if __name__ == "__main__":
    main()
