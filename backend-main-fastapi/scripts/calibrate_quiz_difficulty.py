# -*- coding: utf-8 -*-
"""题库难度校准：按题型/选项数/题干长度/有无解析给 1-5 级难度（PG，幂等）。

### 背景
体检报告 2026-10-19：「386 题几乎都标难度 3」——固定难度让「按难度筛选」
和「自适应推题」全部失效。

### 启发式（无答题历史时的合理起点；将来有 study_events 可换 Elo/IRT）
基础分 2：
  +1  多选 / 填空 / 判断
  +2  计算 / 证明 / 画图 / 简答
  +1  题干 ≥ 200 字 或 含公式符号（=、∫、∑、√、^）
  -1  有解析且 ≥ 20 字（有解析说明是教学题，偏基础）
  -1  选项 ≥ 4 且题干 < 60 字（典型课本单选，偏简单）
结果夹到 1..5。

### 用法
    python scripts/calibrate_quiz_difficulty.py --dry-run
    python scripts/calibrate_quiz_difficulty.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

HARD_TYPES = {"calc", "proof", "draw", "essay"}
MED_TYPES = {"multiple", "fill", "blank", "judge"}
FORMULA_MARKS = ("=", "∫", "∑", "√", "^", "≈", "≤", "≥", "π")

#: 判断题答案词
JUDGE_WORDS = {"对", "错", "正确", "错误", "√", "×", "T", "F", "true", "false"}
_LETTERS = re.compile(r"^[A-HＡ-Ｈ]{1,6}$")


def infer_type(answer: str | None, content: str) -> str | None:
    """从答案与题干推断题型；判不出返回 None（保持原值）。

    实测 386 题 question_type 全是 `single`——抽取阶段根本没识别题型，
    导致「按题型筛选」和难度计算都失真。这里用答案形态反推：
      单个字母 → single；多个字母 → multiple；判断词 → judge；
      有下划线空位 → fill；长文本答案 → essay / short_answer。
    """
    a = (answer or "").strip()
    c = content or ""
    if not a:
        return None

    au = a.upper().replace(" ", "")
    if _LETTERS.match(au):
        return "multiple" if len(au) > 1 else "single"
    if a in JUDGE_WORDS or a.lower() in JUDGE_WORDS:
        return "judge"
    if "____" in c or "＿＿" in c or "（ ）" in c and len(a) <= 6:
        return "fill"
    if len(a) >= 80:
        return "essay"
    if len(a) >= 20:
        return "short_answer"
    return None


def calc_difficulty(qtype: str | None, content: str, options, analysis: str | None) -> int:
    """基础分 3（中等），再按题型与题干特征增减。

    第一版把「有解析」当减分项，结果 386 题里 382 道全落到 1 级——
    因为课本题几乎都带解析，减分项成了全员命中，反而彻底失去区分度。
    解析只说明「有教学价值」，与难度无关，故不再参与计算。
    """
    score = 3
    t = (qtype or "").lower()
    if t in HARD_TYPES:
        score += 2
    elif t in MED_TYPES:
        score += 1

    text = content or ""
    if len(text) >= 200 or sum(text.count(m) for m in FORMULA_MARKS) >= 3:
        score += 1

    # 短题干 + 四选项 = 课本典型单选，偏基础；但最多只降一级，避免全员触底
    n_opts = len(options) if isinstance(options, (list, tuple)) else 0
    if n_opts >= 4 and len(text) < 60:
        score -= 1

    return max(1, min(5, score))


def main() -> int:
    ap = argparse.ArgumentParser(description="题库难度校准")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error("必须指定 --dry-run 或 --apply")

    with psycopg.connect(pg_database_url(), autocommit=False) as pg, pg.cursor() as cur:
        cur.execute("""
            SELECT id, question_type::text, coalesce(content,''), options,
                   coalesce(analysis,''), difficulty, coalesce(answer,'')
            FROM quiz_questions
        """)
        rows = cur.fetchall()
        print(f"题目总数：{len(rows)}")

        updates: list[tuple[int, str, int]] = []
        dist_before = Counter(r[5] for r in rows)
        dist_after = Counter()
        type_before = Counter(r[1] for r in rows)
        type_after = Counter()
        for qid, qtype, content, options, analysis, old, answer in rows:
            new_type = infer_type(answer, content) or qtype
            d = calc_difficulty(new_type, content, options, analysis)
            dist_after[d] += 1
            type_after[new_type] += 1
            if d != old or new_type != qtype:
                updates.append((d, new_type, qid))

        print(f"修前题型：{dict(type_before)}")
        print(f"修后题型：{dict(type_after)}")
        print(f"修前难度分布：{dict(sorted(dist_before.items()))}")
        print(f"修后难度分布：{dict(sorted(dist_after.items()))}")
        print(f"需要变更：{len(updates)} 道")

        if args.dry_run:
            for d, t, qid in updates[:10]:
                print(f"  q{qid} → {t} / 难度 {d}")
            print("\n[DRY-RUN] 未写库；加 --apply 执行。")
            return 0

        cur.executemany(
            "UPDATE quiz_questions SET difficulty=%s, question_type=%s, updated_at=now() WHERE id=%s",
            updates,
        )
        pg.commit()
        print(f"\n[OK] 已更新 {len(updates)} 道题的难度")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
