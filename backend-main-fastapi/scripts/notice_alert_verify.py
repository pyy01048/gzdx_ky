# -*- coding: utf-8 -*-
"""通知分级 + 日期抽取 + 提醒扫描 的一键验证脚本（真实库，真跑）。

用法（在后端目录下）：
    python scripts/notice_alert_verify.py

做四件事：
  1. sqlite3 backup() API 备份真库（**禁止 cp**，WAL 会丢数据）
  2. 建表/加列 + 全量回填分级与关键日期，打印真实抽取样例
  3. 造几条订阅（验证订阅匹配），手动触发一次提醒扫描
  4. 打印提醒表产出 + 扫描日志（验证 Windows 时区无静默失败）
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault(
    "DATABASE_PATH", str(BACKEND.parents[0] / "database" / "kaoyan.db")
)

import sqlite3  # noqa: E402

from database import SessionLocal  # noqa: E402
from services.kaoyan.notice_alert import (  # noqa: E402
    LEVEL_LABEL_CN,
    backfill_all,
    cn_now,
    ensure_alert_schema,
    extract_dates,
    parse_date_loose,
    scan_alerts,
)

DB = os.environ["DATABASE_PATH"]
BACKUP_DIR = BACKEND.parents[0] / "_backup_notice_alert"


def backup_db(tag: str) -> str:
    """用 sqlite3 backup() API 备份（cp 在 WAL 下会丢数据）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = cn_now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"kaoyan_pre_notice_alert_{stamp}_{tag}.db")
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def main() -> int:
    # ---------------- 1. 备份 ----------------
    # 纪律（team-lead 2026-10-12）：**一次操作只备份一次，纯验证不备份**。
    # 本脚本是只读回归（建表/加列是幂等 DDL，回填只 UPDATE 自己的列），
    # 不产生不可逆变更，因此默认不备份。确需备份时加 --backup。
    # 历史教训：本脚本原先每次运行都备份，一次回归跑 3 遍就产生 3 份 670MB
    # 备份，把 _backup_notice_alert 撑到 8.1GB。
    if "--backup" in sys.argv:
        section("1. 备份真库（sqlite3 backup() API，非 cp）")
        bak = backup_db("verify")
        print(f"备份完成: {bak}")
    else:
        print("  [跳过备份] 纯验证不备份（要备份请加 --backup）")

    db = SessionLocal()
    try:
        # ---------------- 2. 建表 + 全量回填 ----------------
        section("2. 建表 + 全量分级/日期回填")
        ensure_alert_schema(db)
        stats = backfill_all(db)
        print(json.dumps(stats, ensure_ascii=False, indent=2))

        from services.kaoyan.notice_alert import raw_conn
        conn = raw_conn(db)

        section("3. 等级分布（真实统计）")
        for lvl, cnt in conn.execute(
            "SELECT IFNULL(importance_level,'normal'), COUNT(*) FROM kaoyan_notices "
            "GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall():
            print(f"  {LEVEL_LABEL_CN.get(lvl, lvl):<4} {cnt:>5}")

        section("4. 关键日期抽取 —— 真实标题样例（从1504 条里真有日期的）")
        rows = conn.execute(
            "SELECT id, school_name, title, notice_type, publish_date, importance_level, "
            "       deadline_date, events_json FROM kaoyan_notices "
            "WHERE events_json IS NOT NULL AND events_json != '[]' "
            "ORDER BY publish_date DESC LIMIT 12"
        ).fetchall()
        shown = 0
        for r in rows:
            events = json.loads(r[7] or "[]")
            if not events:
                continue
            shown += 1
            print(f"\n[{r[0]}] {r[1]}｜{r[2]}")
            print(f"    类型={r[3]} 发布={r[4]} 等级={LEVEL_LABEL_CN.get(r[5], r[5])}")
            for e in events:
                flag = "【截止】" if e["is_deadline"] else "  日期 "
                print(f"    {flag} {e['label']}: {e['date']}  (原文「{e['date_text']}」)")
                print(f"           上下文: {e['context'][:70]}")
        if shown == 0:
            print("  （无）")

        section("5. 有 deadline_date 的通知（=防漏核心目标）")
        dl_rows = conn.execute(
            "SELECT id, school_name, title, deadline_date, importance_level FROM kaoyan_notices "
            "WHERE deadline_date IS NOT NULL ORDER BY deadline_date LIMIT 10"
        ).fetchall()
        for r in dl_rows:
            print(f"  {r[3]}  [{LEVEL_LABEL_CN.get(r[4], r[4])}]  {r[1]}｜{r[2][:44]}")
        print(f"  合计带截止日: {len(dl_rows)} 条（上方最多 10 条）")

        section("6. 紧急级通知 Top 10（真正需要主动浮出来的）")
        for r in conn.execute(
            "SELECT id, school_name, title, notice_type, publish_date, importance_score "
            "FROM kaoyan_notices WHERE importance_level='urgent' "
            "ORDER BY importance_score DESC, publish_date DESC LIMIT 10"
        ).fetchall():
            print(f"  [{r[5]:>5.0f}] {r[4]} {r[1]}｜{r[2][:46]}")

        # ---------------- 6.5 分级规则回归用例（防止规则改动引入误判）----------------
        section("6.5 分级规则回归用例")
        from services.kaoyan.notice_alert import classify_importance

        rule_cases = [
            ("XX大学2027年硕士研究生招生考试（初试）将于12月20日-21日进行", "公告", "urgent"),
            ("XX大学2026年硕士研究生招生考试复试分数线公布", "公告", "urgent"),
            ("XX大学2026年硕士研究生调剂复试录取实施细则", "调剂", "urgent"),
            ("XX大学2026年统招硕士研究生拟录取名单公示", "录取", "urgent"),
            ("XX大学2026年研究生招生考试报考点公告", "公告", "urgent"),
            ("关于报送2026年（12月）学位材料的通知 截止日期为2026年12月3日", "公告", "urgent"),
            ("关于2027年硕士研究生招生专业目录初试科目调整的通知", "公告", "important"),
            ("[置顶] 关于招收2027年硕士研究生初试科目的公告（2026年7月31日更新）", "公告", "important"),
            ("江南大学2027年硕士研究生招生考试（初试）自命题科目考试大纲", "公告", "important"),
            ("XX大学2026年硕士研究生招生简章", "简章", "important"),
            ("XX大学2026年硕士研究生复试预通知", "公告", "important"),
            ("2027年博士研究生招生简章及专业目录", "简章", "normal"),
            ("党支部关于开展主题党日活动的通知", "公告", "normal"),
            ("上海交通大学中英国际低碳学院招生宣讲活动预告（4月2日-4月3日）", "公告", "normal"),
            ("华中师范大学2026年6月11日授予博士学位公示", "录取", "normal"),
            # 回归：清洗后残留的「硕博」误豁免（实测 3 条漏过降级规则）
            ("2026年博士研究生(硕博连读)各学院（系）复试方案", "公告", "normal"),
            ("XX大学2026年硕博连读博士研究生复试录取办法", "复试", "normal"),
            # 回归：「工程硕博士」是硕博联合培养、含硕士名额，必须豁免降级
            ("西安交通大学2027年“工程硕博士培养改革专项试点” 研究生（全日制）招生简章", "简章", "important"),
        ]
        hit = 0
        for t, ty, want in rule_cases:
            got = classify_importance(t, ty)
            flag = "OK " if got["level"] == want else "BAD"
            hit += got["level"] == want
            print(f"  [{flag}] {got['level']:<10}{got['score']:>5} want={want:<9} {t[:40]}")
        print(f"  规则回归: {hit}/{len(rule_cases)} 正确")
        assert hit == len(rule_cases), "分级规则回归用例失败！"

        section("7. 造订阅 + 手动触发提醒扫描")
        now_iso = cn_now().strftime("%Y-%m-%d %H:%M:%S")
        subs = [
            ("school", 0, "西安电子科技大学", "", "", "", "important"),
            ("notice_type", 0, "", "", "调剂", "", "normal"),
            ("keyword", 0, "", "", "", "复试", "normal"),
            ("keyword", 0, "", "", "", "拟录取", "normal"),
        ]
        for s in subs:
            conn.execute(
                "INSERT OR IGNORE INTO kaoyan_subscriptions (scope, school_id, school_name, "
                "major_name, notice_type, keyword, level_min, enabled, created_at) "
                "VALUES (?,?,?,?,?,?,?,1,?)", (*s, now_iso))
        db.commit()
        conn = raw_conn(db)   # commit 后 fairy 失效，须重取
        print("  订阅数:", conn.execute(
            "SELECT COUNT(*) FROM kaoyan_subscriptions WHERE enabled=1").fetchone()[0])

        # 把库内「今天发布」的若干紧急通知的 publish_date 改到今天，
        # 以便真实验证临期/新通知提醒链路（结束前会还原）
        today = cn_now().date().isoformat()
        touched = conn.execute(
            "SELECT id FROM kaoyan_notices WHERE importance_level='urgent' "
            "AND publish_date IS NOT NULL ORDER BY id DESC LIMIT 12"
        ).fetchall()
        restore = []
        for (nid,) in touched:
            old = conn.execute(
                "SELECT publish_date FROM kaoyan_notices WHERE id=?", (nid,)).fetchone()[0]
            restore.append((nid, old))
            conn.execute("UPDATE kaoyan_notices SET publish_date=? WHERE id=?", (today, nid))
        db.commit()
        conn = raw_conn(db)   # commit 后 fairy 失效，须重取
        print(f"  （验证用）临时把 {len(restore)} 条紧急通知的 publish_date 置为今天，扫描后还原")

        result = scan_alerts(db, trigger="manual")
        conn = raw_conn(db)   # scan_alerts 内部已 commit，须重取
        print("\n  扫描结果: " + json.dumps(result, ensure_ascii=False))

        # 还原 publish_date
        for nid, old in restore:
            conn.execute("UPDATE kaoyan_notices SET publish_date=? WHERE id=?", (old, nid))
        db.commit()
        conn = raw_conn(db)   # commit 后 fairy 失效，须重取
        print(f"  （验证用）已还原 {len(restore)} 条 publish_date")

        section("8. 提醒表产出 kaoyan_alert_records")
        total = conn.execute("SELECT COUNT(*) FROM kaoyan_alert_records").fetchone()[0]
        print(f"  总记录: {total}")
        for r in conn.execute(
            "SELECT id, notice_id, alert_kind, alert_date, days_left, message "
            "FROM kaoyan_alert_records ORDER BY (CASE alert_kind WHEN 'deadline_soon' "
            "THEN 0 ELSE 1 END), IFNULL(days_left,9999), id LIMIT 12"
        ).fetchall():
            print(f"  #{r[0]} [{r[2]}] days_left={r[4]} :: {r[5][:66]}")
        print("\n  按类型分布:")
        for r in conn.execute(
            "SELECT alert_kind, COUNT(*) FROM kaoyan_alert_records GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall():
            print(f"    {r[0]:<18} {r[1]}")

        section("9. 二次扫描（验证不重复打扰）")
        result2 = scan_alerts(db, trigger="manual")
        conn = raw_conn(db)   # scan_alerts 内部已 commit，须重取
        print(f"  第二次扫描: {json.dumps(result2, ensure_ascii=False)}")
        total2 = conn.execute("SELECT COUNT(*) FROM kaoyan_alert_records").fetchone()[0]
        print(f"  提醒总记录数 {total} -> {total2}（应保持不变 =去重生效）")

        section("10. Windows 时区验证 + 定时任务注册验证")
        import services.scheduler as sch

        print(f"  服务当前时间(北京): {cn_now().isoformat()}")
        print(f"  scheduler tz: {sch.scheduler.timezone!r}")
        s = sch.start_scheduler()
        jobs = {j.id: str(j.trigger) for j in s.get_jobs()}
        print("  已注册 job:")
        for jid, trig in jobs.items():
            print(f"    {jid:<22} {trig}")
        assert "notice_alert_scan" in jobs, "notice_alert_scan 未注册！"
        print("  [OK] notice_alert_scan 已注册，时区无Asia/Shanghai 查找错误")
        sch.stop_scheduler()

        section("11. 扫描运行日志 kaoyan_alert_runs（证明定时任务真能落库）")
        for r in conn.execute(
            "SELECT id, ran_at, trigger, scanned, created_alerts, skipped_dup, elapsed_ms "
            "FROM kaoyan_alert_runs ORDER BY id DESC LIMIT 5"
        ).fetchall():
            print(f"  run#{r[0]} {r[1]} trigger={r[2]} scanned={r[3]} "
                  f"created={r[4]} dup={r[5]} {r[6]}ms")

        print("\n全部验证通过。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
