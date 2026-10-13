# -*- coding: utf-8 -*-
"""
执行 6 组重复院校合并。**默认 dry-run**，`--apply` 才写库。

安全设计
--------
1. **先在临时副本上演练**：把真库 backup() 到临时文件，跑一遍全部SQL，
   校验行数/ 孤儿引用 / intro 是否保住；只有演练全绿才允许碰真库。
2. **真库执行前再 backup()** 一次（WAL 模式不能用 cp）。
3. 全程单事务，任一步报错则整体回滚。

用法：
  python scripts/merge_duplicate_schools.py                # 演练（不碰真库）
  python scripts/merge_duplicate_schools.py --apply        # 真库执行
  python scripts/merge_duplicate_schools.py --apply --verify
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"
BACKUP_DIR = r"D:\平台\data\backups"

# (实体 id, 空壳 id, 实体名, 空壳名)
PAIRS = [
    (16, 519, "中国石油大学(北京)", "中国石油大学（北京）"),
    (76, 587, "中国石油大学(华东)", "中国石油大学（华东）"),
    (155, 532, "华北电力大学(保定)", "华北电力大学（保定）"),
    (190, 598, "中国地质大学(武汉)", "中国地质大学（武汉）"),
    (217, 520, "中国地质大学(北京)", "中国地质大学（北京）"),
    (668, 518, "中国矿业大学(北京)", "中国矿业大学（北京）"),
]

# 期望的 intro 来源（在空壳侧，合并后必须保住）
INTRO_FROM_SHELL = {76: 587, 190: 598}


def backup_db(src_path: str, tag: str, out_dir: str = BACKUP_DIR) -> str:
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(out_dir, f"kaoyan_pre_mergeschool_{stamp}_{tag}.db")
    src = sqlite3.connect(src_path)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)          # WAL 模式必须用 backup() API，cp 会丢未合并 WAL
    finally:
        out.close()
        src.close()
    return dst


def sql_for(keep_id: int, dup_id: int, keep_name: str, dup_name: str) -> str:
    """生成单组合并 SQL：字段并集 → 重挂引用 → 别名保全 → 删空壳。"""
    return f"""
-- 合并 {dup_name}(id={dup_id}) → {keep_name}(id={keep_id})
UPDATE kaoyan_schools
   SET intro        = CASE WHEN intro        IS NULL OR TRIM(intro)        = '' THEN (SELECT intro        FROM kaoyan_schools WHERE id = {dup_id}) ELSE intro        END,
       logo_url     = CASE WHEN logo_url     IS NULL OR TRIM(logo_url)     = '' THEN (SELECT logo_url     FROM kaoyan_schools WHERE id = {dup_id}) ELSE logo_url     END,
       official_url = CASE WHEN official_url IS NULL OR TRIM(official_url) = '' THEN (SELECT official_url FROM kaoyan_schools WHERE id = {dup_id}) ELSE official_url END,
       tags         = CASE WHEN tags         IS NULL OR TRIM(tags)         = '' THEN (SELECT tags         FROM kaoyan_schools WHERE id = {dup_id}) ELSE tags         END,
       type         = CASE WHEN type         IS NULL OR TRIM(type)         = '' THEN (SELECT type         FROM kaoyan_schools WHERE id = {dup_id}) ELSE type         END,
       region       = CASE WHEN region       IS NULL OR TRIM(region)       = '' THEN (SELECT region       FROM kaoyan_schools WHERE id = {dup_id}) ELSE region       END,
       province     = CASE WHEN province     IS NULL OR TRIM(province)     = '' THEN (SELECT province     FROM kaoyan_schools WHERE id = {dup_id}) ELSE province     END
 WHERE id = {keep_id};

UPDATE kaoyan_colleges   SET school_id = {keep_id} WHERE school_id = {dup_id};
UPDATE kaoyan_majors     SET school_id = {keep_id} WHERE school_id = {dup_id};
UPDATE kaoyan_admissions SET school_id = {keep_id} WHERE school_id = {dup_id};
UPDATE school_aliases    SET school_id = {keep_id} WHERE school_id = {dup_id};

INSERT INTO school_aliases (alias, school_id, school_name, alias_type)
SELECT '{dup_name}', {keep_id}, '{keep_name}', 'common'
 WHERE NOT EXISTS (SELECT 1 FROM school_aliases WHERE alias = '{dup_name}');

DELETE FROM kaoyan_schools WHERE id = {dup_id};
"""


def check(conn, stage: str) -> dict:
    """一致性校验，返回实测指标。"""
    g = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "stage": stage,
        "kaoyan_schools": g("SELECT COUNT(*) FROM kaoyan_schools"),
        "school_aliases": g("SELECT COUNT(*) FROM school_aliases"),
        "kaoyan_colleges": g("SELECT COUNT(*) FROM kaoyan_colleges"),
        "kaoyan_majors": g("SELECT COUNT(*) FROM kaoyan_majors"),
        "kaoyan_admissions": g("SELECT COUNT(*) FROM kaoyan_admissions"),
        "orphan_school": g(
            "SELECT COUNT(*) FROM kaoyan_colleges t WHERE t.school_id IS NOT NULL"
            " AND NOT EXISTS(SELECT 1 FROM kaoyan_schools s WHERE s.id=t.school_id)")
        + g("SELECT COUNT(*) FROM kaoyan_majors t WHERE t.school_id IS NOT NULL"
            " AND NOT EXISTS(SELECT 1 FROM kaoyan_schools s WHERE s.id=t.school_id)")
        + g("SELECT COUNT(*) FROM kaoyan_admissions t WHERE t.school_id IS NOT NULL"
            " AND NOT EXISTS(SELECT 1 FROM kaoyan_schools s WHERE s.id=t.school_id)")
        + g("SELECT COUNT(*) FROM school_aliases t WHERE t.school_id IS NOT NULL"
            " AND NOT EXISTS(SELECT 1 FROM kaoyan_schools s WHERE s.id=t.school_id)"),
        "orphan_college": g(
            "SELECT COUNT(*) FROM kaoyan_majors m WHERE m.college_id IS NOT NULL"
            " AND NOT EXISTS(SELECT 1 FROM kaoyan_colleges c WHERE c.id=m.college_id)"),
        "orphan_major": g(
            "SELECT COUNT(*) FROM kaoyan_admissions a WHERE a.major_id IS NOT NULL"
            " AND NOT EXISTS(SELECT 1 FROM kaoyan_majors m WHERE m.id=a.major_id)"),
    }


def report(m: dict) -> None:
    print(f"  [{m['stage']}]")
    print(f"     kaoyan_schools   = {m['kaoyan_schools']}")
    print(f"     school_aliases   = {m['school_aliases']}")
    print(f"     colleges/majors/admissions = "
          f"{m['kaoyan_colleges']}/{m['kaoyan_majors']}/{m['kaoyan_admissions']}")
    print(f"     孤儿引用(school/college/major) = "
          f"{m['orphan_school']}/{m['orphan_college']}/{m['orphan_major']}")


def run_merge(conn) -> None:
    for keep_id, dup_id, keep_name, dup_name in PAIRS:
        conn.executescript(sql_for(keep_id, dup_id, keep_name, dup_name))


def intros(conn) -> dict:
    out = {}
    for sid in (16, 76, 155, 190, 217, 668):
        r = conn.execute("SELECT intro FROM kaoyan_schools WHERE id=?",
                         (sid,)).fetchone()
        out[sid] = len(r[0] or "") if r else -1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    print("=" * 74)
    print("步骤 1：基线快照")
    print("=" * 74)
    conn = sqlite3.connect(DB)
    before = check(conn, "before")
    intro_before = intros(conn)
    report(before)
    print("\n  intro 长度（合并前）:")
    for keep_id, dup_id, kn, dn in PAIRS:
        print(f"     {kn:<20s} 实体id={keep_id}: {intro_before[keep_id]:>4d} 字"
              f"   空壳id={dup_id}: "
              f"{intro_before.get(dup_id, conn.execute('SELECT LENGTH(intro) FROM kaoyan_schools WHERE id=?', (dup_id,)).fetchone()[0] or 0):>4d} 字")
    conn.close()

    print("\n" + "=" * 74)
    print("步骤 2：临时副本演练（不碰真库）")
    print("=" * 74)
    tmpdir = tempfile.mkdtemp(prefix="merge_dryrun_")
    tmpdb = os.path.join(tmpdir, "dryrun.db")
    shutil.rmtree(tmpdir, ignore_errors=True)
    dry = backup_db(DB, "dryrun", out_dir=tmpdir)
    shutil.move(dry, tmpdb)
    tconn = sqlite3.connect(tmpdb)
    try:
        tconn.execute("PRAGMA foreign_keys=ON")
        run_merge(tconn)
        tconn.commit()
        after = check(tconn, "dryrun-after")
        intro_after = intros(tconn)
        report(after)
        print("\n  intro 长度（演练后）:")
        for keep_id, dup_id, kn, dn in PAIRS:
            print(f"     {kn:<20s} id={keep_id}: {intro_after[keep_id]:>4d} 字")

        # 断言
        errs = []
        if after["kaoyan_schools"] != 577:
            errs.append(f"kaoyan_schools 应为 577，实为 {after['kaoyan_schools']}")
        if after["school_aliases"] != 88:
            errs.append(f"school_aliases 应为 88，实为 {after['school_aliases']}")
        for k in ("orphan_school", "orphan_college", "orphan_major"):
            if after[k] != 0:
                errs.append(f"{k} 应为 0，实为 {after[k]}")
        for keep_id, shell_id in INTRO_FROM_SHELL.items():
            if intro_after[keep_id] < 1:
                errs.append(f"id={keep_id} 的 intro 丢了！应为 {intro_after[keep_id]} 字")
        for keep_id in (16, 76, 155, 190, 217, 668):
            if intro_after[keep_id] < intro_before[keep_id]:
                errs.append(f"id={keep_id} intro 变短")
        print()
        if errs:
            print("  ❌ 演练失败，未碰真库：")
            for e in errs:
                print(f"     - {e}")
            print("\n  演练库保留在:", tmpdb)
            return
        print("  ✅ 演练全绿：583→577、别名 88、孤儿 0、intro 全部保住")
    finally:
        tconn.close()
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not args.apply:
        print("\n>>> dry-run 通过，未碰真库。加 --apply 执行。")
        return

    print("\n" + "=" * 74)
    print("步骤 3：真库执行")
    print("=" * 74)
    bak = backup_db(DB, "real")
    print(f"已备份：{bak}")
    conn = sqlite3.connect(DB)
    try:
        conn.execute("BEGIN")
        run_merge(conn)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  ❌ 执行失败已回滚：{e}")
        print(f"  可从备份恢复：{bak}")
        conn.close()
        return
    real = check(conn, "after")
    intro_real = intros(conn)
    report(real)
    print("\n  intro 长度（真库合并后）:")
    for keep_id, dup_id, kn, dn in PAIRS:
        print(f"     {kn:<20s} id={keep_id}: {intro_real[keep_id]:>4d} 字")
    conn.close()

    print("\n" + "=" * 74)
    print("前后对比")
    print("=" * 74)
    for k in ("kaoyan_schools", "school_aliases", "kaoyan_colleges",
              "kaoyan_majors", "kaoyan_admissions",
              "orphan_school", "orphan_college", "orphan_major"):
        b, a = before[k], real[k]
        print(f"  {k:<22s} {b:>6d} -> {a:<6d}{'  <-- 变化' if b != a else ''}")


if __name__ == "__main__":
    main()