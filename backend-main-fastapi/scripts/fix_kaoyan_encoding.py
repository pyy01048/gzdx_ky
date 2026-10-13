# -*- coding: utf-8 -*-
"""考研库文本编码修复脚本（列类型感知）。

## 背景（真库只读探针实测，2026-10-13）

历史导入脚本把中文串先 ``json.dumps(..., ensure_ascii=True)`` 再写库。对**声明为
JSON 类型**的列（SQLAlchemy 会自动 ``json.loads``），这带来两种截然不同的后果：

1. **列内期望是数组**（``quiz_questions.options`` / ``subject_config.chapters``）
   → 存的是合法 JSON 数组，只是中文被转义成 ``\\uXXXX``。
   ORM 反序列化后仍是正确的 list[str]，功能不受影响，但**用原生 SQL 读时是乱码**，
   且会误导基于原始文本的正则/统计逻辑。

2. **列内期望是字符串**（``kaoyan_majors.exam_subjects``）
   → 存的是 ``json.dumps(纯文本)``，ORM 反序列化后得到的是 **str 而不是 list**。
   ``routers/kaoyan.py::analysis_dashboard`` 当年用 ``isinstance(subs, list)`` 守卫，
   于是**整段统计恒为空**（本次真正的缺陷根因）。

## 本脚本的口径（关键：按列类型分别处理，绝不把 JSON 列写成裸文本）

- **JSON 列**：目标值必须是合法 JSON。
  - 合法 JSON 字符串标量 → 还原转义后重新 ``json.dumps(ensure_ascii=False)``；
  - 合法 JSON 数组/对象 → 仅当含 ``\\uXXXX`` 时重排为不转义形式，否则原样不动；
  - **非法 JSON**（历史写坏，或被上一轮误写成裸文本）→ 还原转义后
    ``json.dumps(..., ensure_ascii=False)`` **包回合法 JSON**。
- **非 JSON 文本列**：直接写还原后的裸文本。

**幂等**：已合规的行再跑结果不变。**可回滚**：``--apply`` 前强制备份。

## 用法

    python scripts/fix_kaoyan_encoding.py --probe       # 只看污染面分布
    python scripts/fix_kaoyan_encoding.py               # dry-run（默认）
    python scripts/fix_kaoyan_encoding.py --apply       # 执行（自动备份）
    python scripts/fix_kaoyan_encoding.py --selftest    # 自检
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

DB_PATH = os.environ.get("KAOYAN_DB") or os.path.join(
    os.path.dirname(BACKEND), "database", "kaoyan.db"
)

_COMPACT = {"ensure_ascii": False, "separators": (",", ":")}


# --------------------------------------------------------------------------- #
# 文本还原
# --------------------------------------------------------------------------- #
def normalize_text(value):
    """还原「外层 JSON 字符串 / 未解码 \\uXXXX」形态；不命中则原样返回。幂等。"""
    if not isinstance(value, str) or not value:
        return value

    text = value
    for _ in range(2):
        s = text.strip()
        if len(s) < 2:
            break

        # 形态 1：外层是 JSON 字符串（带引号）
        if s[0] == '"' and s[-1] == '"':
            try:
                decoded = json.loads(s)
            except Exception:
                break
            if isinstance(decoded, str) and decoded != s:
                text = decoded
                continue
            break

        # 形态 2：裸 JSON 数组/对象且含 \uXXXX
        if s[0] in "[{" and "\\u" in s:
            try:
                decoded = json.loads(s)
            except Exception:
                break
            if isinstance(decoded, (list, dict)):
                out = json.dumps(decoded, **_COMPACT)
                if out != value:
                    return out
            break

        break

    return text


# --------------------------------------------------------------------------- #
# 列类型感知的目标值
# --------------------------------------------------------------------------- #
def desired_value(raw, is_json_col: bool):
    """给定当前存储值与列类型，返回合规目标值。"""
    if raw is None or raw == "":
        return raw

    if not is_json_col:
        return normalize_text(raw)

    try:
        parsed = json.loads(raw)
    except Exception:
        # 非法 JSON → 还原转义后包回合法 JSON 字符串
        return json.dumps(normalize_text(raw), ensure_ascii=False)

    if isinstance(parsed, str):
        fixed = normalize_text(parsed)
        return json.dumps(fixed, ensure_ascii=False)

    # 数组/对象：仅在含转义时重排（保持结构，只把转义还原成中文）
    if "\\u" in raw:
        return json.dumps(parsed, **_COMPACT)
    return raw


# --------------------------------------------------------------------------- #
# 目标清单
# --------------------------------------------------------------------------- #
TARGETS = [
    ("kaoyan_majors", "id", ["exam_subjects", "reference_books", "research_direction"]),
    ("kaoyan_schools", "id", ["name", "province", "level", "data_source"]),
    ("quiz_questions", "id", ["options", "content", "analysis"]),
    ("subject_config", "id", ["chapters"]),
    ("documents", "id", ["content", "title"]),
]


def _column_types(con, table) -> dict:
    try:
        return {r[1]: (r[2] or "").upper() for r in con.execute(f"pragma table_info({table})")}
    except sqlite3.Error:
        return {}


def _table_exists(con, table) -> bool:
    try:
        return con.execute(
            "select 1 from sqlite_master where type='table' and name=?", (table,)
        ).fetchone() is not None
    except sqlite3.Error:
        return False


def scan(con: sqlite3.Connection):
    """→ [(table, pk, col, kind, scanned, [(pk_val, before, after), ...])]"""
    findings = []
    for table, pk, cols in TARGETS:
        if not _table_exists(con, table):
            continue
        types = _column_types(con, table)
        for col in cols:
            is_json = "JSON" in types.get(col, "")
            kind = "JSON列" if is_json else "文本列"
            try:
                rows = con.execute(
                    f'select "{pk}", "{col}" from "{table}" '
                    f"where typeof(\"{col}\")='text' "
                    f"and \"{col}\" is not null and \"{col}\" != ''"
                ).fetchall()
            except sqlite3.Error:
                continue
            changed = []
            for pk_val, raw in rows:
                want = desired_value(raw, is_json)
                if want != raw:
                    changed.append((pk_val, raw, want))
            findings.append((table, pk, col, kind, len(rows), changed))
    return findings


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="考研库文本编码修复（列类型感知）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--selftest", action="store_true", help="只跑逻辑自检")
    ap.add_argument("--probe", action="store_true", help="只打印污染面，不改不写")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()

    if args.selftest:
        cases = [
            # (raw, is_json, want)
            ('"(302)\\u6570\\u5b66\\uff08\\u4e8c\\uff09 | (204)\\u82f1\\u8bed\\uff08\\u4e8c\\uff09"', True,
             '"(302)数学（二） | (204)英语（二）"'),
            # 已被写成裸文本的 JSON 列 → 必须包回合法 JSON
            ("(302)数学（二） | (204)英语（二）", True,
             '"(302)数学（二） | (204)英语（二）"'),
            # 已是合规 JSON 字符串 → 幂等
            ('"(302)数学（二） | (204)英语（二）"', True,
             '"(302)数学（二） | (204)英语（二）"'),
            # JSON 数组含转义 → 还原
            ('["\\u56feA","B"]', True, '["图A","B"]'),
            # JSON 数组已干净 → 不动
            ('["A","B"]', True, '["A","B"]'),
            # 非 JSON 列的裸文本 → 原样
            ("纯文本无转义", False, "纯文本无转义"),
            # 非 JSON 列的转义字符串 → 还原
            ('"\\u56feA"', False, "图A"),
        ]
        ok = 0
        for raw, is_json, want in cases:
            got = desired_value(raw, is_json)
            good = got == want
            ok += 1 if good else 0
            tag = f"JSON={is_json}"
            print(f"[{'OK ' if good else 'FAIL'}] ({tag}) {raw!r} -> {got!r}" + ("" if good else f"  want {want!r}"))
        print(f"selftest {ok}/{len(cases)}")
        return 0 if ok == len(cases) else 1

    if not os.path.exists(args.db):
        print(f"[ERROR] 数据库不存在: {args.db}")
        return 2

    if args.apply:
        from services.backup_service import create_backup

        print(f"[备份] {create_backup()}")

    con = sqlite3.connect(args.db, timeout=30)
    con.execute("pragma journal_mode=WAL")
    try:
        findings = scan(con)
        mode = "APPLY" if args.apply else ("PROBE" if args.probe else "DRY-RUN")
        print(f"\n===== {mode} @ {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====")

        total_updated = 0
        for table, pk, col, kind, scanned, changed in findings:
            if args.probe and not changed:
                continue
            print(f"\n-- {table}.{col} [{kind}]: 扫描 {scanned} 行，命中 {len(changed)} 行")
            if changed and not args.apply:
                for pk_val, before, after in changed[:3]:
                    print(f"   #{pk_val}")
                    print(f"     前: {before[:110]}")
                    print(f"     后: {after[:110]}")
                if len(changed) > 3:
                    print(f"   … 其余 {len(changed) - 3} 行同类")
            if changed and args.apply:
                con.executemany(
                    f'update "{table}" set "{col}"=? where "{pk}"=?',
                    [(after, pk_val) for pk_val, _, after in changed],
                )
                total_updated += len(changed)

        if args.apply:
            con.commit()
            print(f"\n[完成] 共更新 {total_updated} 行")
            print("\n---- 复核（apply 后重扫）----")
            left = 0
            for table, pk, col, kind, scanned, changed in scan(con):
                print(f"  {table}.{col} [{kind}]: 命中 {len(changed)} 行")
                left += len(changed)
            print(f"  残留合计 {left} 行" + ("（幂等达标）" if left == 0 else "（需复查）"))
        elif not args.probe:
            pend = sum(len(c) for *_, c in findings)
            print(f"\n[DRY-RUN] 未写库。拟更新合计 {pend} 行。加 --apply 执行。")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
