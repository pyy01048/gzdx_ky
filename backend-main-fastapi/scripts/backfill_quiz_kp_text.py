# -*- coding: utf-8 -*-
"""题目知识点回填：从题干文本匹配同科目知识点，写 knowledge_point 文本 + 关联表（PG，幂等）。

### 背景（2026-10-20 实测）
- `quiz_questions` 386 道，`knowledge_point` 文本为空 328 道（仅 58 道有值）
- `question_knowledge_links` 425 条 / 覆盖 166 道，即 220 道未关联
- 题目全部 `source_kind=external_import`，`origin_document_id`/`source_page` 为空，
  无法回溯原书页码（做图片映射的前提不存在，故本脚本只做文本级匹配）

### 匹配策略
1. 按科目对齐：题目的 subject 与知识点的 subject 归一化后一致
2. 知识点名必须在题干里**完整出现**（长度≥2 字，避免单字误匹配）
3. 多个命中取**最长名称**（"戴维南定理"优先于"定理"）
4. 同一题只写一个主知识点（role='primary'），避免关联表膨胀
5. 命中的名称写回 `quiz_questions.knowledge_point`；同时补 `question_knowledge_links`

不命中的题**不强行挂**（宁缺勿错），只统计出来供人工处理。

用法：
    python scripts/backfill_quiz_kp_text.py --dry-run
    python scripts/backfill_quiz_kp_text.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402


def norm_subject(s: str | None) -> str:
    t = re.sub(r"[\s　]+", "", (s or ""))
    # 常见别名归一
    alias = {
        "数字电子": "数字电子技术", "数电": "数字电子技术",
        "模拟电子": "模拟电子技术", "模电": "模拟电子技术",
        "电路分析": "电路", "高等数学": "数学", "高数": "数学",
        "线性代数": "数学", "概率论": "数学",
    }
    return alias.get(t, t)


#: 这些词作为「知识点名」太泛，题干里必然出现，挂上去就是假关联。
#: 实测 dry-run 里「运放/函数/连续」把大批题错误挂接，故一律不匹配。
STOP_NAMES = {
    "函数", "连续", "极限", "概率", "矩阵", "向量", "导数", "积分", "级数",
    "电路", "电压", "电流", "电阻", "功率", "逻辑", "门电路", "触发器",
    "运放", "放大", "反馈", "信号", "系统", "分析", "计算", "方法",
    "定理", "定义", "概念", "原理", "应用", "问题", "条件", "性质",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="题目知识点文本回填")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-name-len", type=int, default=3)
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    with psycopg.connect(pg_database_url(), autocommit=False) as pg, pg.cursor() as cur:
        # 知识点按科目分组，按名称长度降序（最长优先）
        cur.execute("SELECT id, name, subject, chapter FROM knowledge_points WHERE btrim(coalesce(name,''))<>''")
        kps = cur.fetchall()
        by_subject: dict[str, list[tuple[int, str, str | None]]] = defaultdict(list)
        for kid, name, subj, chap in kps:
            by_subject[norm_subject(subj)].append((kid, name.strip(), chap))
        for v in by_subject.values():
            v.sort(key=lambda x: len(x[1]), reverse=True)
        print(f"知识点：{len(kps)} 条，覆盖 {len(by_subject)} 个归一化学科")

        cur.execute("""
            SELECT id, subject, coalesce(content,''), coalesce(chapter,'')
            FROM quiz_questions
            WHERE btrim(coalesce(knowledge_point,''))=''
        """)
        rows = cur.fetchall()
        print(f"待回填题目：{len(rows)}")

        hits: list[tuple[int, int, str]] = []     # (question_id, kp_id, kp_name)
        unmatched: list[int] = []
        for qid, subj, content, chap in rows:
            pool = by_subject.get(norm_subject(subj), [])
            matched = None
            for kid, name, _kchap in pool:
                if len(name) < args.min_name_len:
                    continue
                if name in STOP_NAMES:
                    continue
                if name in content:
                    matched = (kid, name)
                    break
            if matched:
                hits.append((qid, matched[0], matched[1]))
            else:
                unmatched.append(qid)

        print(f"可匹配：{len(hits)} 道（{len(hits)/max(1,len(rows)):.1%}）；"
              f"未匹配：{len(unmatched)} 道")

        if args.dry_run:
            for qid, kid, name in hits[:10]:
                print(f"  q{qid} → {name}")
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        # 写回题目文本
        cur.executemany(
            "UPDATE quiz_questions SET knowledge_point=%s, updated_at=now() WHERE id=%s",
            [(name, qid) for qid, _kid, name in hits],
        )
        # 补关联表（幂等：先删同题同知识点的旧记录再插）
        for qid, kid, _name in hits:
            cur.execute(
                "DELETE FROM question_knowledge_links WHERE question_id=%s AND knowledge_point_id=%s",
                (qid, kid),
            )
            cur.execute(
                "INSERT INTO question_knowledge_links (question_id, knowledge_point_id, role, weight, is_verified)"
                " VALUES (%s, %s, 'primary', 1.0, false)",
                (qid, kid),
            )
        pg.commit()

        cur.execute("SELECT count(*) FILTER (WHERE btrim(coalesce(knowledge_point,''))<>''), count(*) FROM quiz_questions")
        filled, total = cur.fetchone()
        cur.execute("SELECT count(DISTINCT question_id) FROM question_knowledge_links")
        linked = cur.fetchone()[0]
        print(f"\n[OK] 知识点文本：{filled}/{total}")
        print(f"[OK] 已关联题目：{linked}/{total}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
