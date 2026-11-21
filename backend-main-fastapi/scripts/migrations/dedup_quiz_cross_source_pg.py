#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""存储层跨源去重合并（PostgreSQL · 11 文档 §3.2）。

判重键：归一化题干 + 科目 + 章节 + 年份（年份维度豁免合法跨年同题）。
保留优先级：真题(past_exam) > 教材(textbook) > 章节习题 > 模拟(mock_exam)
> 开源导入(external_import) > 其余；同优先级保留解析最全者，再按 id 升序。

流程：默认 dry-run 出合并报告 -> --apply 单事务：
  1. 备份 quiz_questions 全量 JSONL + 受影响关联行 JSONL；
  2. 关联表外键 question_id 迁移到保留题（paper_questions/question_images/
     question_knowledge_links/answer_records/error_records/misconceptions）；
  3. question_knowledge_links 按 (保留题, 知识点) 去重，question_images 按
     (保留题, image_hash) 去重；
  4. 删除被合并题；
  5. 生成回滚脚本（Python）与合并报告。
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import psycopg
from scripts._conn import dsn

BACKUP_DIR = Path(r"D:\研途\题库建设\backup")
REPORT_DIR = Path(r"D:\研途\gzdx_ky\docs\reports")
LOG = logging.getLogger("dedup_quiz_cross_source")

# 保留优先级（越小越优先）
SOURCE_PRIORITY = {
    "past_exam": 0,
    "textbook": 1,
    "chapter_exercise": 2,
    "mock_exam": 3,
    "external_import": 4,
    "ai_generated": 5,
    "user_created": 6,
}

FK_TABLES = [
    "answer_records",
    "error_records",
    "misconceptions",
    "paper_questions",
    "question_images",
    "question_knowledge_links",
]

_OCR = re.compile(r"[\ufffd\ufeff\ufffe\uffff]|[\ue000-\uf8ff]|[\U000f0000-\U0010ffff]")
_SIGN = re.compile(
    r"[\s\u3000]+|[\uff08\uff09()\u3010\u3011\[\]\uff5b\uff5d\u007b\u007d"
    r"\u3001\uff0c,\u3002.\uff0e.\uff1b;\uff1a://uff1f?!//uff01!"
    r"\u201e\uff02\u201c\u201d\"'\u2019\u2018`~\uff5e\u3014\u2015\uff0d\-_|/\\|\uff5c]+"
)


def canonical(text):
    """归一化题干：去 OCR 噪声、全角转半角、去空白与标点、lower。"""
    s = str(text or "")
    s = _OCR.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = _SIGN.sub("", s)
    return s.strip().lower()


def backup_table(conn, table, stamp, only_ids=None):
    """备份表全部行或指定 id 行到 JSONL，返回 (path, count)。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"{table}_{stamp}.jsonl"
    sql = f"SELECT * FROM {table}"
    params = ()
    if only_ids:
        sql += " WHERE id = ANY(%s::bigint[])"
        params = (sorted(only_ids),)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        n = 0
        with path.open("w", encoding="utf-8") as f:
            while True:
                rows = cur.fetchmany(1000)
                if not rows:
                    break
                for r in rows:
                    f.write(json.dumps(dict(zip(cols, r, strict=False)), ensure_ascii=False, default=str) + "\n")
                    n += 1
    return path, n


def build_groups(conn):
    """构建重复组并选出每组保留题。返回 (groups, summary)。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, subject, chapter, year, content, source_kind, "
            "COALESCE(analysis,'') AS analysis, COALESCE(answer,'') AS answer "
            "FROM quiz_questions ORDER BY id"
        )
        rows = cur.fetchall()
    groups = defaultdict(list)
    for r in rows:
        n = canonical(r[4])
        if len(n) < 8:
            continue
        key = (r[1], r[2], r[3], n)
        groups[key].append(r)
    dup = {k: v for k, v in groups.items() if len(v) > 1}
    decisions = []
    for key, grp in sorted(dup.items(), key=lambda x: -len(x[1])):
        ordered = sorted(
            grp,
            key=lambda r: (
                SOURCE_PRIORITY.get(r[5], 9),
                -len(r[6]),
                0 if r[7] else 1,
                r[0],
            ),
        )
        keep = ordered[0]
        merged = ordered[1:]
        decisions.append({"key": key, "keep": keep, "merged": merged})
    return decisions


def summarize(decisions):
    by_subject = defaultdict(int)
    total_merge = 0
    for d in decisions:
        by_subject[d["key"][0] or "NULL"] += len(d["merged"])
        total_merge += len(d["merged"])
    return total_merge, dict(sorted(by_subject.items(), key=lambda x: -x[1]))


def preview(decisions, total_merge, by_subject):
    print("\n===== DRY-RUN 跨源去重合并预览 =====")
    print(
        f"重复组数: {len(decisions)} | 涉及题数: {sum(len(d['merged']) + 1 for d in decisions)} | 需合并行: {total_merge}"
    )
    print("\n按科目（需合并行数）：")
    for s, c in by_subject.items():
        print(f"  {s:30s} {c}")
    print("\n前 12 组明细（保留题 -> 被合并题）：")
    for d in decisions[:12]:
        k, keep, merged = d["key"], d["keep"], d["merged"]
        keep_label = f"{k[0]}/{str(k[1])[:12]}/{k[2]}/{k[3][:20]}"
        print(f"  [keep {keep[0]} src={keep[5]}] {keep_label}")
        for m in merged:
            print(f"      - 合并 {m[0]} src={m[5]} analysis_len={len(m[6])}")
    print("\n（dry-run，未写库；确认后加 --apply）")


def apply(conn, decisions):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    # 1. 备份 quiz_questions 全量 + 6 张关联表全量
    q_backup, q_cnt = backup_table(conn, "quiz_questions", stamp)
    LOG.info("已备份 quiz_questions 全量 %d 行 -> %s", q_cnt, q_backup)
    for t in FK_TABLES:
        path, n = backup_table(conn, t, stamp)
        LOG.info("已备份 %s 全量 %d 行 -> %s", t, n, path)

    # 2. 迁移外键：被合并题 -> 保留题
    mapping = [(m[0], d["keep"][0]) for d in decisions for m in d["merged"]]
    merged_ids = [m[0] for d in decisions for m in d["merged"]]
    migrated = defaultdict(int)
    with conn.cursor() as cur:
        # 通用表（无 (question_id, ...) 唯一约束）直接 UPDATE
        for t in ("answer_records", "error_records", "misconceptions", "paper_questions", "question_images"):
            cur.executemany(
                f"UPDATE {t} SET question_id = %s WHERE question_id = %s",
                mapping,
            )
            migrated[t] = cur.rowcount

        # question_knowledge_links 有 (question_id, knowledge_point_id) 唯一约束：
        # 先复制合并题的知识点链接到保留题（冲突即跳过），再删除合并题的链接。
        cur.execute(
            "SELECT id, question_id, knowledge_point_id, role, weight, is_verified, created_at FROM question_knowledge_links WHERE question_id = ANY(%s::bigint[])",
            (merged_ids,),
        )
        links = cur.fetchall()
        dst_map = {src: dst for src, dst in mapping}
        inserted = 0
        for _lid, src, kp, role, weight, verified, created in links:
            dst = dst_map.get(src)
            if dst is None:
                continue
            cur.execute(
                "INSERT INTO question_knowledge_links "
                "(question_id, knowledge_point_id, role, weight, is_verified, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (question_id, knowledge_point_id) DO NOTHING",
                (dst, kp, role, weight, verified, created),
            )
            inserted += cur.rowcount
        migrated["question_knowledge_links"] = inserted
        cur.execute("DELETE FROM question_knowledge_links WHERE question_id = ANY(%s::bigint[])", (merged_ids,))
        dedup_kp = cur.rowcount

        # 3. question_images 迁移后去重
        cur.execute(
            "DELETE FROM question_images a USING question_images b "
            "WHERE a.id > b.id AND a.question_id = b.question_id "
            "AND a.image_hash = b.image_hash"
        )
        dedup_img = cur.rowcount

        # 4. 删除被合并题（外键已迁移，无孤儿）
        cur.execute("DELETE FROM quiz_questions WHERE id = ANY(%s::bigint[])", (merged_ids,))
        deleted = cur.rowcount
    conn.commit()
    return dict(
        q_backup=q_backup,
        q_cnt=q_cnt,
        migrated=dict(migrated),
        dedup_stats={"question_knowledge_links": dedup_kp, "question_images": dedup_img},
        deleted=deleted,
        mapping=mapping,
        stamp=stamp,
    )


def write_rollback_script(stamp, deleted_ids):
    """生成回滚脚本：从备份 JSONL 恢复被删除题与关联行 question_id。"""
    path = REPORT_DIR / f"rollback_dedup_quiz_{stamp}.py"
    code = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""去重合并回滚脚本（由 dedup_quiz_cross_source_pg.py 生成）。

从 JSONL 备份恢复：被删除的 quiz_questions 行 + 6 张关联表的 question_id。
用法：python {path.name}
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(r"D:\\研途\\gzdx_ky\\backend-main-fastapi")))
from scripts._conn import dsn
import psycopg

BACKUP_DIR = Path(r"D:\\研途\\题库建设\\backup")
DELETED = {deleted_ids}
FK_TABLES = {FK_TABLES!r}
conn = psycopg.connect(dsn(), connect_timeout=10)
cur = conn.cursor()

with (BACKUP_DIR / "quiz_questions_{stamp}.jsonl").open(encoding="utf-8") as f:
    rows = [json.loads(line) for line in f if json.loads(line)["id"] in DELETED]
for r in rows:
    cols = ", ".join(r.keys())
    cur.execute(f"INSERT INTO quiz_questions ({{cols}}) VALUES ({{','.join(['%s']*len(r))}}) ON CONFLICT (id) DO NOTHING",
                tuple(r.values()))
print("恢复 quiz_questions 被删除行:", len(rows))

for t in FK_TABLES:
    path = BACKUP_DIR / f"{{t}}_{stamp}.jsonl"
    if not path.exists():
        continue
    with path.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    for r in rows:
        cols = ", ".join(r.keys())
        cur.execute(f"INSERT INTO {{t}} ({{cols}}) VALUES ({{','.join(['%s']*len(r))}}) ON CONFLICT (id) DO UPDATE SET question_id = EXCLUDED.question_id",
                    tuple(r.values()))
    print("恢复", t, "行数:", len(rows))
conn.commit()
conn.close()
print("回滚完成")
'''
    path.write_text(code, encoding="utf-8")
    return path


def write_report(stamp, decisions, total_merge, by_subject, result):
    path = REPORT_DIR / f"dedup-cross-source-{stamp}.md"
    lines = [
        f"# 跨源去重合并报告（{datetime.now().strftime('%Y-%m-%d')}）",
        "",
        "- 判重键：归一化题干 + 科目 + 章节 + 年份（年份豁免合法跨年同题）",
        f"- 重复组数：{len(decisions)} ｜ 需合并行：{total_merge}",
        f"- 备份：`{result['q_backup']}`",
        f"- 回滚脚本：`{REPORT_DIR / f'rollback_dedup_quiz_{stamp}.py'}`",
        "",
        "## 按科目（需合并行）",
        "",
        "| 科目 | 需合并行 |",
        "|---|---|",
    ]
    for s, c in by_subject.items():
        lines.append(f"| {s} | {c} |")
    lines += ["", "## 关联行迁移", "", "| 表 | 迁移行数 |", "|---|---|"]
    for t, c in result["migrated"].items():
        lines.append(f"| {t} | {c} |")
    lines += [
        "",
        "## 关联行去重（迁移后）",
        "",
        "| 表 | 删除重复行 |",
        "|---|---|",
    ]
    for t, c in result["dedup_stats"].items():
        lines.append(f"| {t} | {c} |")
    lines += [
        "",
        f"## 删除题数：{result['deleted']}",
        "",
        "## 保留策略",
        "",
        "保留优先级：真题(past_exam) > 教材(textbook) > 章节习题 > 模拟(mock_exam) > 开源导入 > 其余；同优先级取解析最全者，再按 id 升序。",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="存储层跨源去重合并")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    args = ap.parse_args()

    conn = psycopg.connect(dsn(), connect_timeout=10)
    try:
        decisions = build_groups(conn)
        total_merge, by_subject = summarize(decisions)
        if not args.apply:
            preview(decisions, total_merge, by_subject)
            return 0
        result = apply(conn, decisions)
        deleted_ids = sorted(m[0] for d in decisions for m in d["merged"])
        rb = write_rollback_script(result["stamp"], deleted_ids)
        rp = write_report(result["stamp"], decisions, total_merge, by_subject, result)
        print("\n===== 合并完成 =====")
        print(f"删除被合并题: {result['deleted']} 行")
        print(f"备份: {result['q_backup']}")
        print(f"回滚脚本: {rb}")
        print(f"报告: {rp}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(main())
