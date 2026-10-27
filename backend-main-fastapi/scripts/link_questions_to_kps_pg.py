# -*- coding: utf-8 -*-
"""把题库题目关联到知识点（PG，规则匹配，幂等）。

背景：
- knowledge_points 已有 1678 个（按学科分布：数学 1208 / 电路 280 / 数电 123 ...）
- question_knowledge_links 为 0，导致知识图谱点进去没有题、题目也没有知识点
- quiz_questions.knowledge_point 基本为空

策略（保守，只写关联，不改题干/答案）：
1. 同 subject 优先；没有同科知识点时退回全库，但要求知识点名 >= 5 字。
2. 知识点全名出现在题干/答案中才建立关联；知识点名 < 4 字不单独匹配（防泛名）。
3. 每题最多 3 条关联，按命中名称长度降序。
4. 只写 question_knowledge_links；回填 quiz_questions.knowledge_point / chapter
   （仅在原值为空时写，不覆盖人工数据）。
5. 幂等：已存在的 (question_id, knowledge_point_id) 跳过。

用法：
    python scripts/link_questions_to_kps_pg.py --dry-run
    python scripts/link_questions_to_kps_pg.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

MAX_LINKS = 3
MIN_NAME_LEN = 4
MIN_NAME_LEN_NO_SUBJECT = 5


CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def chapter_key(text: str | None) -> str:
    """把『第1章 电路模型』『第一章』『1.2 节』统一成章节号 key。"""
    t = norm(text)
    if not t:
        return ""
    m = re.search(r"第?([0-9一二三四五六七八九十]+)章", t)
    if m:
        raw = m.group(1)
        return str(int(raw)) if raw.isdigit() else str(CN_NUM.get(raw, raw))
    m = re.match(r"^(\d+)(?:\.\d+)*", t)
    return str(int(m.group(1))) if m else ""


def norm(text: str | None) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[，。、；：！？（）()【】\[\]《》<>“”\"'·…—\-]", "", t)
    return t.lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    with psycopg.connect(pg_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, subject, chapter, chapter_id
                FROM knowledge_points
                WHERE name IS NOT NULL AND btrim(name) <> ''
            """)
            kps = [
                {
                    "id": r[0], "name": r[1], "norm": norm(r[1]),
                    "subject": r[2] or "", "chapter": r[3],
                    "chapter_id": r[4],
                }
                for r in cur.fetchall()
            ]
            by_subject = defaultdict(list)
            by_subject_chapter = defaultdict(list)
            for kp in kps:
                if len(kp["norm"]) >= MIN_NAME_LEN:
                    by_subject[kp["subject"]].append(kp)
                ch = chapter_key(kp.get("chapter"))
                if ch:
                    by_subject_chapter[(kp["subject"], ch)].append(kp)

            cur.execute("""
                SELECT id, subject, chapter, knowledge_point, content, answer
                FROM quiz_questions
                WHERE COALESCE(is_junk, false) = false
            """)
            questions = cur.fetchall()

        planned = []
        for qid, subject, chapter, kp_text, content, answer in questions:
            blob = norm(content) + "\n" + norm(answer)
            candidates = by_subject.get(subject or "", [])
            if not candidates:
                candidates = [kp for kp in kps if len(kp["norm"]) >= MIN_NAME_LEN_NO_SUBJECT]

            hits = []
            for kp in candidates:
                name = kp["norm"]
                if len(name) < MIN_NAME_LEN:
                    continue
                if name in blob:
                    hits.append((len(name), kp))
            hits.sort(key=lambda x: (-x[0], x[1]["id"]))
            exact = bool(hits)
            picked = []
            seen = set()
            for _, kp in hits:
                if kp["id"] in seen:
                    continue
                seen.add(kp["id"])
                picked.append(kp)
                if len(picked) >= MAX_LINKS:
                    break
            # 章节级兜底：题干章节可靠时，挂同科同章的 2 个知识点。
            # 只挂 secondary/低权重，避免把“章节相关”伪装成“精确考点”。
            if not picked and chapter:
                ch = chapter_key(chapter)
                pool = by_subject_chapter.get((subject or "", ch), [])
                for kp in pool[:2]:
                    picked.append(kp)
            if picked:
                planned.append((qid, subject, chapter, kp_text, picked, exact))

        print(f"可匹配题目 {len(planned)}/{len(questions)}；知识点 {len(kps)}")
        for qid, subject, chapter, kp_text, picked, exact in planned[:12]:
            print(f"  q#{qid} [{subject}] -> " +
                  ", ".join(f"{k['name']}({k['id']})" for k in picked))

        if not apply:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        inserted = 0
        updated_q = 0
        with conn.cursor() as cur:
            for qid, subject, chapter, kp_text, picked, exact in planned:
                top = picked[0]
                for idx, kp in enumerate(picked):
                    role = "primary" if (exact and idx == 0) else "secondary"
                    weight = 1.0 if (exact and idx == 0) else 0.6
                    cur.execute("""
                        INSERT INTO question_knowledge_links
                          (question_id, knowledge_point_id, role, weight, is_verified)
                        VALUES (%s, %s, %s, %s, false)
                        ON CONFLICT (question_id, knowledge_point_id) DO NOTHING
                    """, (qid, kp["id"], role, weight))
                    inserted += cur.rowcount
                cur.execute("""
                    UPDATE quiz_questions
                       SET knowledge_point = COALESCE(NULLIF(knowledge_point, ''), %s),
                           chapter = COALESCE(NULLIF(chapter, ''), %s)
                     WHERE id = %s
                """, (top["name"] if exact else None, top["chapter"], qid))
                updated_q += cur.rowcount
            # 回填 question_count，供知识图谱显示“关联题量”
            cur.execute("""
                UPDATE knowledge_points k
                   SET question_count = COALESCE(x.n, 0)
                  FROM (SELECT knowledge_point_id, COUNT(*) AS n
                          FROM question_knowledge_links GROUP BY 1) x
                 WHERE k.id = x.knowledge_point_id
            """)
        conn.commit()
        print(f"完成：新增关联 {inserted} 条，回填题目 {updated_q} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
