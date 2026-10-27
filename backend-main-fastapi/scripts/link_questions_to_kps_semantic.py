# -*- coding: utf-8 -*-
"""语义版：题目 → 知识点关联（PG + 本地 bge-small-zh-v1.5）。

比纯字符串匹配覆盖率高：题干与知识点释义做向量相似度，同科目内取 Top3。
只写 question_knowledge_links 与空字段；不改题干/答案；幂等。

用法：
    python scripts/link_questions_to_kps_semantic.py --dry-run
    python scripts/link_questions_to_kps_semantic.py --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402
from services.embedding_service import generate_local_embeddings  # noqa: E402

THRESHOLD = 0.70
MAX_LINKS = 1
MARGIN = 0.04
MAX_TEXT = 600


def vec(texts: list[str]) -> np.ndarray:
    arr = np.asarray(generate_local_embeddings(texts), dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    with psycopg.connect(pg_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, subject, chapter, chapter_id, description
                FROM knowledge_points
                WHERE name IS NOT NULL AND btrim(name) <> ''
            """)
            kps = [
                {
                    "id": r[0], "name": r[1], "subject": r[2] or "",
                    "chapter": r[3], "chapter_id": r[4],
                    "text": f"{r[1]}。{r[5] or ''}。{r[3] or ''}"[:MAX_TEXT],
                }
                for r in cur.fetchall()
            ]
            cur.execute("""
                SELECT q.id, q.subject, q.chapter, q.content, q.answer
                FROM quiz_questions q
                WHERE COALESCE(q.is_junk, false) = false
                  AND NOT EXISTS (
                      SELECT 1 FROM question_knowledge_links l
                       WHERE l.question_id = q.id
                  )
            """)
            questions = cur.fetchall()

        print(f"编码知识点 {len(kps)} 条…")
        kp_vecs = vec([k["text"] for k in kps])
        print(f"编码题目 {len(questions)} 条…")
        q_vecs = vec([((r[3] or "") + " " + (r[4] or ""))[:MAX_TEXT] for r in questions])

        by_subject = defaultdict(list)
        for i, kp in enumerate(kps):
            by_subject[kp["subject"]].append(i)

        planned = []
        for qi, row in enumerate(questions):
            qid, subject, chapter, _content, _answer = row
            idxs = by_subject.get(subject or "") or list(range(len(kps)))
            if not idxs:
                continue
            scores = kp_vecs[idxs] @ q_vecs[qi]
            order = np.argsort(-scores)
            picked = []
            for pos in order[:MAX_LINKS]:
                score = float(scores[pos])
                if score < args.threshold:
                    break
                if len(order) > 1:
                    second = float(scores[order[1]])
                    if score - second < MARGIN:
                        break
                picked.append((kps[idxs[pos]], score))
            if picked:
                planned.append((qid, subject, chapter, picked))

        print(f"可关联题目 {len(planned)}/{len(questions)}")
        for qid, subject, chapter, picked in planned[:15]:
            print(f"  q#{qid} [{subject}] -> " +
                  ", ".join(f"{k['name']}({s:.3f})" for k, s in picked))

        if not apply:
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        inserted = 0
        updated_q = 0
        with conn.cursor() as cur:
            for qid, subject, chapter, picked in planned:
                top = picked[0][0]
                for i, (kp, score) in enumerate(picked):
                    cur.execute("""
                        INSERT INTO question_knowledge_links
                          (question_id, knowledge_point_id, role, weight, is_verified)
                        VALUES (%s, %s, %s, %s, false)
                        ON CONFLICT (question_id, knowledge_point_id) DO NOTHING
                    """, (qid, kp["id"], "primary" if i == 0 else "secondary", score))
                    inserted += cur.rowcount
                cur.execute("""
                    UPDATE quiz_questions
                       SET knowledge_point = COALESCE(NULLIF(knowledge_point, ''), %s),
                           chapter = COALESCE(NULLIF(chapter, ''), %s)
                     WHERE id = %s
                """, (top["name"], top["chapter"], qid))
                updated_q += cur.rowcount
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
