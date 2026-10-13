# -*- coding: utf-8 -*-
"""official_url 数字 schid 修正（dry-run 默认，--apply 才写库）。

问题
----
``kaoyan_schools.official_url`` 有 103 所存的是**纯数字研招网 schid**
（如 ``'367938'``），不是 URL。前端渲染成链接点不开，用户无法从院校页
跳转到研招网页面手动补导通知。

判据（保守，只修确定的）
------------------------
仅当 ``official_url`` 满足以下全部条件才修：
1. 非空；
2. 去空白后**纯数字**（``^\\d+$``）；
3. 不以 ``http`` 开头。

满足则改写为 ``https://yz.chsi.com.cn/sch/{schid}.jhtml``。

**不修**：已是 http(s) URL 的、空/NULL 的、含字母或其它字符的
（如 ``'2807891911'`` 是纯数字会修；``'abc123'`` 不修）。

用法
----
    python scripts/fix_official_url_schid.py            # dry-run，只报数+抽样
    python scripts/fix_official_url_schid.py --apply    # 写库（先 backup()）

纪律
----
* 备份一律走 SQLite ``backup()`` API，**禁止 cp / copy2**（WAL 模式会丢数据）。
* 只改 ``kaoyan_schools.official_url`` 一列，不碰其它表/列。
* 幂等：已修正过的行二次运行不会再次命中（改写后不再是纯数字）。
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"

#: 纯数字 schid 判据。
SCHID_RE = re.compile(r"^\d+$")

CHSI_URL = "https://yz.chsi.com.cn/sch/{schid}.jhtml"


def backup_db(tag: str) -> str:
    """SQLite WAL 模式下必须用 backup() API；cp 会丢未合并的 WAL 数据。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_schidfix_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def scan(conn: sqlite3.Connection) -> list[tuple]:
    """返回待修正行 (id, name, level, province, old_url, new_url, notice_cnt)。"""
    rows = conn.execute(
        "SELECT s.id, s.name, s.level, s.province, s.official_url, "
        "       (SELECT COUNT(*) FROM kaoyan_notices n WHERE n.school_id = s.id) "
        "FROM kaoyan_schools s "
        "WHERE s.official_url IS NOT NULL AND TRIM(s.official_url) <> '' "
        "ORDER BY s.id"
    ).fetchall()
    out = []
    for sid, name, level, prov, url, ncnt in rows:
        u = str(url).strip()
        if SCHID_RE.match(u) and not u.lower().startswith("http"):
            out.append((sid, name, level, prov, url, CHSI_URL.format(schid=u), ncnt))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = ap.parse_args()

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True) if not args.apply else sqlite3.connect(DB)
    try:
        targets = scan(conn)
        print("=" * 74)
        print("official_url 数字 schid 修正")
        print("=" * 74)
        print(f"  待修正行数: {len(targets)}")

        # 分层统计
        by_level: dict[str, int] = {}
        for r in targets:
            by_level[str(r[2] or "NULL")] = by_level.get(str(r[2] or "NULL"), 0) + 1
        print("  按 level 分布:", dict(sorted(by_level.items(), key=lambda kv: -kv[1])))

        # 名校单独列（直接影响用户补导）
        elite = [r for r in targets if r[2] in ("985", "211", "双一流")]
        print(f"  其中名校(985/211/双一流): {len(elite)} 所")
        for r in elite:
            print(f"    {r[2]:6s} {r[1][:16]:18s} {r[3] or '-':4s} "
                  f"通知={r[6]:<3d} '{r[4]}' -> {r[5]}")

        # 零通知 + 修正后可点开 = 用户可立即补导
        newly_usable = [r for r in targets if r[6] == 0]
        print(f"  其中零通知（修正后用户可立即补导）: {len(newly_usable)} 所")

        print()
        print("  抽样 12 条（含 6 所名校）:")
        for r in (elite + [x for x in targets if x not in elite])[:12]:
            print(f"    id={r[0]:<5} {str(r[2] or 'NULL'):6s} {r[1][:16]:18s} "
                  f"'{r[4]}' -> {r[5]}")

        if not args.apply:
            print()
            print("[dry-run] 未写库。加 --apply 执行。")
            return 0

        print()
        print("=" * 74)
        print("写库")
        print("=" * 74)
        print("已备份:", backup_db("real"))
        n = 0
        for sid, name, level, prov, old, new, _ncnt in targets:
            cur = conn.execute(
                "UPDATE kaoyan_schools SET official_url = ? WHERE id = ? AND official_url = ?",
                (new, sid, old),
            )
            n += cur.rowcount
        conn.commit()
        print(f"  已修正 {n} 行")
        left = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_schools WHERE official_url IS NOT NULL "
            "AND TRIM(official_url) <> '' AND official_url GLOB '[0-9]*' "
            "AND official_url NOT LIKE 'http%'"
        ).fetchone()[0]
        print(f"  残留纯数字 schid: {left}")
        nonempty_after = conn.execute(
            "SELECT COUNT(*) FROM kaoyan_schools "
            "WHERE official_url IS NOT NULL AND TRIM(official_url) <> ''"
        ).fetchone()[0]
        print(f"  当前 official_url 非空总数: {nonempty_after}（修正前 201，应不变）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
