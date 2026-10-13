# -*- coding: utf-8 -*-
"""documents 表科目字段错配修复（M1-1d，2026-10）。

背景：M1-1c 修了 `quiz_questions.subject`，但**题库导入继承 `documents.subject`**——
若不同步修文档，重新入库会再次引入同样的错配（"政治"栏混入模电内容）。

本脚本修复 `documents` 表中**证据明确**的错标：
  * 《【电子技术基础】国家职业资格培训》系列（.txt/.pdf）→ `模拟电子技术`
    （该教材主体是模电半导体内容，实测 3 个文档共 781 道题全为模电）。

安全设计：
  * 默认 dry-run；--apply 先 sqlite backup；
  * 幂等新增列 `subject_source`（原值记 `original`、被修者记 `corrected_source_rule`）；
  * 审计日志 `tools/datasource/document_subject_fix_audit.json`（可回滚）。

⚠️ 不做的事：**不改动真正的政治真题文档**（2018–2026 考研政治真题、答题卡等），
也不动历史学/法硕/管综等"非政治真题被标政治"的文档（另一类问题，需单独评估）。

用法：
    python scripts/fix_document_subject.py            # 预览
    python scripts/fix_document_subject.py --apply     # 写库（先备份）
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
DB_PATH = os.environ.get("DATABASE_PATH", "").strip() or os.path.join(
    os.path.dirname(BASE_DIR), "database", "kaoyan.db"
)
REPO_ROOT = os.path.dirname(BASE_DIR)
AUDIT_JSON = os.path.join(REPO_ROOT, "tools", "datasource",
                          "document_subject_fix_audit.json")

#: 精确修复规则（按 file_name 模式匹配）
DOC_RULES: list[dict] = [
    {
        "name": "电子技术基础·国职培训 → 模电",
        "file_like": "%【电子技术基础】国家职业资格培训%",
        "from_subject": "政治",
        "to_subject": "模拟电子技术",
        "subject_source": "corrected_source_rule",
    },
]


def _has_column(cur: sqlite3.Cursor) -> bool:
    cols = {r[1] for r in cur.execute("PRAGMA table_info(documents)")}
    return "subject_source" in cols


def _ensure_column(cur: sqlite3.Cursor) -> None:
    """幂等新增 subject_source 列（仅 --apply 时调用）。"""
    if not _has_column(cur):
        cur.execute("ALTER TABLE documents ADD COLUMN subject_source VARCHAR(32)")


def _collect(cur: sqlite3.Cursor) -> list[dict]:
    """按规则收集待修文档（不写库）。"""
    out: list[dict] = []
    for rule in DOC_RULES:
        rows = cur.execute(
            "SELECT id, file_name, subject FROM documents "
            "WHERE file_name LIKE ? AND subject = ?",
            (rule["file_like"], rule["from_subject"]),
        ).fetchall()
        for did, fname, old in rows:
            out.append({
                "id": did,
                "file_name": fname,
                "old_subject": old,
                "new_subject": rule["to_subject"],
                "subject_source": rule["subject_source"],
                "rule": rule["name"],
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="documents 表科目错配修复")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认预览）")
    ap.add_argument("--sample", type=int, default=10, help="预览样例条数")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    col_exists = _has_column(cur)
    candidates = _collect(cur)
    fixed_ids = {r[0] for r in cur.execute(
        "SELECT id FROM documents WHERE subject_source = 'corrected_source_rule'")} \
        if col_exists else set()
    effective = [d for d in candidates if d["id"] not in fixed_ids]

    print(f"数据库: {DB_PATH}")
    print(f"待修文档（规则命中）：{len(candidates)} 条；"
          f"已修过跳过 {len(candidates) - len(effective)}；本次实际 {len(effective)}")
    print(f"subject_source 列：{'已存在' if col_exists else '待 --apply 时创建'}\n")

    # 全库 documents 科目分布（前 → 预估后）
    before = {r[0]: r[1] for r in cur.execute(
        "SELECT subject, COUNT(*) FROM documents GROUP BY subject")}
    after = dict(before)
    for d in effective:
        after[d["old_subject"]] = after.get(d["old_subject"], 0) - 1
        after[d["new_subject"]] = after.get(d["new_subject"], 0) + 1
    print("== documents 科目分布（当前 → 预计修后）==")
    for k in sorted(before, key=lambda x: -before[x]):
        print(f"  {k:<20} {before[k]:>5}  →  {after.get(k, 0):>5}")

    if args.sample > 0 and effective:
        print(f"\n----- 待修样例（前 {args.sample} 条）-----")
        for d in effective[: args.sample]:
            print(f"  DOC{d['id']}  {d['old_subject']} → {d['new_subject']}  「{d['file_name']}」")

    if not args.apply:
        print("\n[DRY-RUN] 未写库。确认后加 --apply 执行（会自动备份）。")
        con.close()
        return 0

    # ---- 备份 ----
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_docsubjectfix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    print(f"\n已备份 → {bak}")

    _ensure_column(cur)
    con.commit()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    audit: list[dict] = []
    for d in effective:
        row = cur.execute("SELECT subject FROM documents WHERE id = ?", (d["id"],)).fetchone()
        if not row:
            continue
        old = row[0]
        if old == d["new_subject"]:
            continue
        cur.execute(
            "UPDATE documents SET subject = ?, subject_source = ? WHERE id = ?",
            (d["new_subject"], d["subject_source"], d["id"]))
        audit.append({
            "document_id": d["id"],
            "file_name": d["file_name"],
            "old_subject": old,
            "new_subject": d["new_subject"],
            "subject_source": d["subject_source"],
            "rule": d["rule"],
            "fixed_at": now,
        })
    con.commit()

    # 未改动文档补 original（幂等：只补 NULL）
    cur.execute("UPDATE documents SET subject_source = 'original' WHERE subject_source IS NULL")
    con.commit()

    # 审计落盘（追加批次）
    prev = {}
    if os.path.exists(AUDIT_JSON):
        try:
            with open(AUDIT_JSON, encoding="utf-8") as f:
                prev = json.load(f)
        except Exception:
            prev = {}
    batches = prev.get("batches", []) if isinstance(prev, dict) else []
    batches.append({
        "applied_at": now,
        "db_path": DB_PATH,
        "backup": bak,
        "fixed_count": len(audit),
        "entries": audit,
    })
    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump({"batches": batches}, f, ensure_ascii=False, indent=2)

    after_now = {r[0]: r[1] for r in cur.execute(
        "SELECT subject, COUNT(*) FROM documents GROUP BY subject")}
    print("\n===== documents 修复完成 =====")
    print(f"本批修复 {len(audit)} 条")
    print(f"documents 科目分布后：政治 {after_now.get('政治', 0)}、"
          f"模电 {after_now.get('模拟电子技术', 0)}")
    print(f"审计日志 → {AUDIT_JSON}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
