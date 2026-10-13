# -*- coding: utf-8 -*-
"""quiz_questions 科目字段错配修复（M1-1c，2026-10）。

消费 M1-1b 诊断产物 `tools/datasource/question_subject_mismatch.json`，
对**高置信、非数模边界的科目错配**做批量修复。

安全设计：
  * **只读清单驱动**：不重跑匹配，直接读诊断 JSON，保证与已审阅结果一致；
  * **默认 dry-run**：不加 `--apply` 只预览，不碰数据库；
  * **自动备份**：--apply 时先用 sqlite backup API 备份真库（WAL 安全）；
  * **幂等**：新增列 `subject_source`（幂等 ALTER），原值记 `original`、
    被修者记 `corrected_rule`；重复运行不会重复改（已 `corrected_rule` 的跳过）；
  * **可回滚**：审计日志 `tools/datasource/subject_fix_audit.json` 记录
    question_id / 原值 / 新值 / 证据词 / 时间 / 批次；
  * **不越权**：默认只修「政治→电子」等高置信非边界项；「模电↔数电」这类
    数模边界题只标 `pending_review`，不自动改；跨域项（模电→数学、英语→政治）
    同样默认不改。

用法：
    python scripts/fix_question_subject.py                     # dry-run（默认）
    python scripts/fix_question_subject.py --include-cross-domain
    python scripts/fix_question_subject.py --apply             # 写库（先备份）
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
MISMATCH_JSON = os.path.join(REPO_ROOT, "tools", "datasource",
                             "question_subject_mismatch.json")
AUDIT_JSON = os.path.join(REPO_ROOT, "tools", "datasource",
                          "subject_fix_audit.json")

ELEC = {"模拟电子技术", "数字电子技术"}


def _load_mismatches() -> list[dict]:
    if not os.path.exists(MISMATCH_JSON):
        raise FileNotFoundError(
            f"未找到诊断清单 {MISMATCH_JSON}，请先运行 diagnose_question_subject.py"
        )
    with open(MISMATCH_JSON, encoding="utf-8") as f:
        return json.load(f).get("mismatches", [])


def _classify(m: dict, include_cross_domain: bool) -> str:
    """把一条错配分为 'fix'（自动修）/ 'pending'（仅标记待核）。

    自动修（高置信、非边界）：
      - 「政治 → 模电/数电」：政治栏混入电子内容，证据极强（本轮主体 381 条）。
      - 「其他 → 模电/数电」：同理。
    仅标待核（不自动改）：
      - 「模电 ↔ 数电」：数模边界题（555/触发器/RC振荡等），需人工抽验。
      - 「408 ↔ 电子」：408 计算机组成/存储 与 数电 共享"寄存器/RAM/进制"等词，
        实测存在**假阳性**（如 Q8890 计算机组成题被误判为数电）→ 一律待核。
      - 跨域项（模电→数学、英语→政治等）：默认待核；--include-cross-domain 才修。

    注：「专业课 → 408」清晰，可修。
    """
    a, b = m["current_subject"], m["suggested_subject"]
    if a in ELEC and b in ELEC:
        return "pending"          # 数模边界，人工抽验
    if a == "计算机学科专业基础408" or b == "计算机学科专业基础408":
        # 408 与电子的词重叠度高，假阳性风险大 → 不自动改
        if a == "专业课":
            return "fix"          # 专业课→408 清晰
        return "pending"
    if b in ELEC:
        return "fix"              # 政治/其他 → 电子：证据充分
    # 其余跨域项
    return "fix" if include_cross_domain else "pending"


def _has_column(cur: sqlite3.Cursor) -> bool:
    cols = {r[1] for r in cur.execute("PRAGMA table_info(quiz_questions)")}
    return "subject_source" in cols


def _ensure_column(cur: sqlite3.Cursor) -> None:
    """幂等新增 subject_source 列（仅在 --apply 时调用，dry-run 不改 schema）。"""
    if not _has_column(cur):
        cur.execute("ALTER TABLE quiz_questions ADD COLUMN subject_source VARCHAR(20)")


#: A 组精确规则：某类 source 的题**整批**属于某科目（比关键词判据可靠）。
#  实测：`subject='政治'` 且 source 含《电子技术基础国家职业资格培训》的 781 题
#  全是模电半导体内容（PN结/二极管/半导体器件）。
SOURCE_RULES: list[dict] = [
    {
        "name": "电子技术基础(国职培训)→模电",
        "match_subject": "政治",
        "source_like": "%电子技术基础%国家职业资格培训%",
        "new_subject": "模拟电子技术",
        "subject_source": "corrected_source_rule",
    },
]


def _apply_source_rules(cur: sqlite3.Cursor) -> list[dict]:
    """执行 A 组精确 source 规则，返回待修条目（不写库，仅收集）。"""
    out: list[dict] = []
    for rule in SOURCE_RULES:
        rows = cur.execute(
            "SELECT id, subject, source FROM quiz_questions "
            "WHERE subject = ? AND source LIKE ?",
            (rule["match_subject"], rule["source_like"]),
        ).fetchall()
        for qid, old, src in rows:
            out.append({
                "id": qid,
                "current_subject": old,
                "suggested_subject": rule["new_subject"],
                "evidence_hits": [f"source匹配:{rule['name']}"],
                "scores": {},
                "chapter": None,
                "snippet": (src or "")[:90],
                "subject_source": rule["subject_source"],
            })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="quiz_questions 科目字段错配修复")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认仅预览）")
    ap.add_argument("--include-cross-domain", action="store_true",
                    help="一并修跨域项（如 模电→数学、英语→政治）；默认只标待核")
    ap.add_argument("--no-source-rules", action="store_true",
                    help="禁用 A 组 source 精确规则（默认启用）")
    ap.add_argument("--sample", type=int, default=10, help="预览样例条数")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    # ---- A 组：source 精确规则（高置信）----
    a_group = [] if args.no_source_rules else _apply_source_rules(cur)
    a_ids = {m["id"] for m in a_group}

    # ---- B 组：关键词诊断清单（排除 A 组已覆盖的）----
    mismatches = _load_mismatches()
    to_fix: list[dict] = []
    pending: list[dict] = []
    for m in mismatches:
        if m["id"] in a_ids:
            continue  # A 组已覆盖，避免重复/冲突
        kind = _classify(m, args.include_cross_domain)
        if kind == "fix":
            m = dict(m)
            m["subject_source"] = "corrected_keyword"
            to_fix.append(m)
        else:
            pending.append(m)

    # A∪B 并集
    union_fix = a_group + to_fix

    # 现行 subject_source 状态（dry-run 只读探测，不改 schema）
    col_exists = _has_column(cur)
    fixed_ids = {r[0] for r in cur.execute(
        "SELECT id FROM quiz_questions WHERE subject_source IN "
        "('corrected_rule','corrected_keyword','corrected_source_rule')")} \
        if col_exists else set()
    effective = [m for m in union_fix if m["id"] not in fixed_ids]

    print(f"数据库: {DB_PATH}")
    print(f"A 组 source 精确规则：命中 {len(a_group)} 条")
    print(f"B 组 关键词诊断（fix）：{len(to_fix)} 条")
    print(f"A∪B 并集：{len(union_fix)} 条（已修过跳过 {len(union_fix) - len(effective)}，"
          f"本次实际 {len(effective)}）")
    print(f"仅标记待核 (pending_review)：{len(pending)} 条")
    print(f"subject_source 列：{'已存在' if col_exists else '待 --apply 时创建'}\n")

    # ---- 修复前后科目分布（仅针对拟修集合）----
    before = {}
    after = {}
    for m in effective:
        before[m["current_subject"]] = before.get(m["current_subject"], 0) + 1
        after[m["suggested_subject"]] = after.get(m["suggested_subject"], 0) + 1
    print("== 拟修集合：科目分布（前 → 后）==")
    all_keys = sorted(set(before) | set(after))
    for k in all_keys:
        print(f"  {k:<16} {before.get(k, 0):>4}  →  {after.get(k, 0):>4}")

    # ---- 全库科目分布（修前 → 预估修后）----
    full_before = {r[0]: r[1] for r in cur.execute(
        "SELECT subject, COUNT(*) FROM quiz_questions GROUP BY subject")}
    full_after = dict(full_before)
    for m in effective:
        full_after[m["current_subject"]] = full_after.get(m["current_subject"], 0) - 1
        full_after[m["suggested_subject"]] = full_after.get(m["suggested_subject"], 0) + 1
    print("\n== 全库科目分布（当前 → 预计修后）==")
    for k in sorted(full_before, key=lambda x: -full_before[x]):
        print(f"  {k:<20} {full_before[k]:>5}  →  {full_after.get(k, 0):>5}")

    # ---- 样例 ----
    if args.sample > 0 and effective:
        print(f"\n----- 修复样例（前 {args.sample} 条）-----")
        for m in effective[: args.sample]:
            print(f"  Q{m['id']}  {m['current_subject']} → {m['suggested_subject']}"
                  f"  证据：{ '、'.join(m['evidence_hits'][:4]) }")
            print(f"      「{m['snippet'][:70]}」")

    if not args.apply:
        print("\n[DRY-RUN] 未写库。确认后加 --apply 执行（会自动备份）。")
        con.close()
        return 0

    # ---- 备份 ----
    bak_dir = os.path.join(BASE_DIR, "data", "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(
        bak_dir, f"kaoyan_pre_subjectfix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    with sqlite3.connect(bak) as dest:
        con.backup(dest)
    print(f"\n已备份 → {bak}")

    # 幂等建列（备份之后）
    _ensure_column(cur)
    con.commit()

    # ---- 写库 ----
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    audit: list[dict] = []
    by_source: dict[str, int] = {}
    # 先从数据库取真实原值（不信任 JSON 的快照）
    for m in effective:
        row = cur.execute("SELECT subject FROM quiz_questions WHERE id = ?",
                          (m["id"],)).fetchone()
        if not row:
            continue
        old = row[0]
        new = m["suggested_subject"]
        if old == new:
            continue
        src_tag = m.get("subject_source", "corrected_keyword")
        cur.execute(
            "UPDATE quiz_questions SET subject = ?, subject_source = ? WHERE id = ?",
            (new, src_tag, m["id"]))
        by_source[src_tag] = by_source.get(src_tag, 0) + 1
        audit.append({
            "question_id": m["id"],
            "old_subject": old,
            "new_subject": new,
            "subject_source": src_tag,
            "evidence_hits": m["evidence_hits"],
            "scores": m.get("scores", {}),
            "chapter": m.get("chapter"),
            "fixed_at": now,
        })
    con.commit()

    # 仅为「未改动」的题补 subject_source='original'（幂等：只补 NULL）
    cur.execute(
        "UPDATE quiz_questions SET subject_source = 'original' WHERE subject_source IS NULL")
    con.commit()

    # ---- 审计落盘（追加模式，保留历史批次）----
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
        "pending_review_count": len(pending),
        "pending_review_ids": [m["id"] for m in pending],
        "entries": audit,
    })
    with open(AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump({"batches": batches}, f, ensure_ascii=False, indent=2)

    # ---- 结果核对 ----
    fixed_now = cur.execute(
        "SELECT COUNT(*) FROM quiz_questions WHERE subject_source LIKE 'corrected_%'"
    ).fetchone()[0]
    full_after = {r[0]: r[1] for r in cur.execute(
        "SELECT subject, COUNT(*) FROM quiz_questions GROUP BY subject")}
    print("\n===== 修复完成 =====")
    print(f"本批修复 {len(audit)} 条；按依据：{by_source}")
    print(f"全库 subject_source LIKE 'corrected_%' 共 {fixed_now} 条")
    print(f"待人工审核(pending_review) {len(pending)} 条（见审计日志）")
    print("\n== 修复后完整科目分布 ==")
    for k in sorted(full_after, key=lambda x: -full_after[x]):
        print(f"  {k:<20} {full_after[k]:>5}")
    print(f"\n审计日志 → {AUDIT_JSON}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
