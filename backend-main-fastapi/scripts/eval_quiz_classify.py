# -*- coding: utf-8 -*-
"""题库自动分类精度评测（v2 可信闸门）。

目标：用标注金集实测「字段级准确率」与「自动入库精度 / 覆盖率」，并扫描阈值，
定位 99% 精度在哪儿落地——而不是拍脑袋。

金集来源（两种，自动择一/合并）：
  1. 手写 gold（scripts/data/quiz_classify_gold.json）：[{content, options,
     subject, question_type}]，人工/AI 精标，真值最可信。
  2. 银标 gold（自动构建）：从 quiz_questions 中取「科目 = 库内标签，且题干独立命中
     ≥2 个该科关键词」的题目——双重确认，高精（近似真值）。用于大规模校准。

指标：
  - subject_acc / type_acc：整体字段准确率（含自动入库与待复核的全部题）。
  - 自动入库精度（auto_prec）：v2 判定 auto_accept 的那批里，科目+题型都判对的占比
    —— 这是「自动入库那批的准确率」，阈值直接保证它逼近 99%。
  - 覆盖率（coverage）：auto_accept 题占全集比例。精度↑通常覆盖率↓，二选一权衡。

用法：
    python scripts/eval_quiz_classify.py                 # 用银标金集评测
    python scripts/eval_quiz_classify.py --gold scripts/data/quiz_classify_gold.json
    python scripts/eval_quiz_classify.py --per-subject 40 --no-llm
    python scripts/eval_quiz_classify.py --sweep          # 扫描阈值表
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SILVER_PATH = os.path.join(DATA_DIR, "quiz_classify_silver.json")
GOLD_PATH = os.path.join(DATA_DIR, "quiz_classify_gold.json")


# --------------------------------------------------------------------------- #
# 金集构建
# --------------------------------------------------------------------------- #
def _load_gold_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return raw if isinstance(raw, list) else []


def build_silver_gold(db, per_subject: int = 30) -> list:
    """银标金集：库内标签 + 题干独立 ≥2 关键词双重确认（高精近似真值）。"""
    from models import QuizQuestion
    from services.quiz_autoclassify import _SUBJECT_RULES

    rule_map = {s: set(kws) for s, kws in _SUBJECT_RULES}
    gold = []
    seen = set()
    for subject, kws in _SUBJECT_RULES:
        rows = (
            db.query(QuizQuestion)
            .filter(QuizQuestion.subject == subject)
            .filter(QuizQuestion.is_junk.is_(False) | QuizQuestion.is_junk.is_(None))
            .filter(QuizQuestion.is_available.is_(True) | QuizQuestion.is_available.is_(None))
            .limit(per_subject * 4)
            .all()
        )
        cnt = 0
        for r in rows:
            content = (r.content or "").strip()
            if not content or content in seen:
                continue
            # 独立确认：题干命中该科关键词，且不被他科明显抢走（信任库内标签）
            hits = sum(1 for kw in kws if kw in content)
            other = max((sum(1 for okw in okws if okw in content)
                         for os_, okws in rule_map.items() if os_ != subject), default=0)
            if other > hits + 1:
                continue
            seen.add(content)
            gold.append({
                "content": content,
                "options": r.options if isinstance(r.options, list) else None,
                "subject": subject,
                "question_type": r.question_type or "single",
            })
            cnt += 1
            if cnt >= per_subject:
                break
    return gold


# --------------------------------------------------------------------------- #
# 评测
# --------------------------------------------------------------------------- #
def evaluate(gold: list, db, use_llm: bool) -> dict:
    from services.quiz_classifier_v2 import classify_batch_v2

    questions = [{"content": g["content"], "options": g.get("options")} for g in gold]
    decisions = classify_batch_v2(questions, db=db, use_llm=use_llm)

    subj_correct = type_correct = both_correct = 0
    auto = auto_correct = 0
    for g, dec in zip(gold, decisions):
        pred_subj = dec.subject.value
        pred_type = dec.question_type.value
        gold_subj = g.get("subject") or ""
        gold_type = g.get("question_type") or ""
        if pred_subj == gold_subj:
            subj_correct += 1
        if pred_type == gold_type:
            type_correct += 1
        if pred_subj == gold_subj and pred_type == gold_type:
            both_correct += 1
        if dec.auto_accept:
            auto += 1
            if pred_subj == gold_subj and pred_type == gold_type:
                auto_correct += 1

    n = len(gold)
    return {
        "n": n,
        "subject_acc": subj_correct / n if n else 0.0,
        "type_acc": type_correct / n if n else 0.0,
        "both_acc": both_correct / n if n else 0.0,
        "auto_accept": auto,
        "coverage": auto / n if n else 0.0,
        "auto_prec": auto_correct / auto if auto else 0.0,
        "decisions": decisions,
    }


def sweep(gold: list, db, use_llm: bool) -> list:
    """不重跑 LLM，直接复用已算出的字段置信度扫不同阈值。"""
    from services.quiz_classifier_v2 import classify_batch_v2

    questions = [{"content": g["content"], "options": g.get("options")} for g in gold]
    decisions = classify_batch_v2(questions, db=db, use_llm=use_llm)
    rows = []
    for s_th in (0.80, 0.85, 0.90, 0.95):
        for t_th in (0.80, 0.85, 0.90):
            auto = auto_ok = 0
            for g, dec in zip(gold, decisions):
                if (dec.subject.value and dec.subject.confidence >= s_th
                        and dec.question_type.confidence >= t_th):
                    auto += 1
                    if dec.subject.value == (g.get("subject") or "") \
                            and dec.question_type.value == (g.get("question_type") or ""):
                        auto_ok += 1
            n = len(gold)
            rows.append({
                "subject_th": s_th, "type_th": t_th,
                "coverage": auto / n if n else 0.0,
                "auto_prec": auto_ok / auto if auto else float("nan"),
                "auto_n": auto,
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="题库自动分类精度评测（v2）")
    ap.add_argument("--gold", default="", help="手写 gold json 路径（优先）")
    ap.add_argument("--per-subject", type=int, default=30, help="银标每科采样上限")
    ap.add_argument("--no-llm", action="store_true", help="关闭 LLM 兜底")
    ap.add_argument("--sweep", action="store_true", help="扫描阈值表")
    ap.add_argument("--rebuild-silver", action="store_true", help="强制重建银标金集")
    args = ap.parse_args()

    from database import SessionLocal

    db = SessionLocal()
    try:
        # 金集
        gold = _load_gold_json(args.gold) if args.gold else []
        if not gold and os.path.exists(GOLD_PATH):
            gold = _load_gold_json(GOLD_PATH)
        if not gold or args.rebuild_silver:
            print("[gold] 银标金集自动构建中…")
            gold = build_silver_gold(db, per_subject=args.per_subject)
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SILVER_PATH, "w", encoding="utf-8") as f:
                json.dump(gold, f, ensure_ascii=False, indent=1)
            print(f"[gold] 银标写入 {SILVER_PATH}（{len(gold)} 条）")
        if not gold:
            print("❌ 无金集可用（手写 gold 或银标构建失败）")
            return 1

        use_llm = not args.no_llm
        print(f"[eval] 金集 {len(gold)} 条，use_llm={use_llm}\n")

        r = evaluate(gold, db, use_llm)
        print("【字段级准确率（自动入库 + 待复核 全量）】")
        print(f"  科目准确率   : {r['subject_acc']:.3f}")
        print(f"  题型准确率   : {r['type_acc']:.3f}")
        print(f"  科目+题型    : {r['both_acc']:.3f}")
        print(f"  自动入库覆盖率: {r['coverage']:.3f}（{r['auto_accept']}/{r['n']}）")
        print(f"  ★ 自动入库精度: {r['auto_prec']:.3f}（这批是阈值保证的高精集）\n")

        if args.sweep:
            print("【阈值扫描：定位 99% 精度落点】")
            print(f"{'科目阈值':>8}{'题型阈值':>8}{'覆盖率':>9}{'自动精度':>10}{'自动数':>8}")
            for row in sweep(gold, db, use_llm):
                aps = f"{row['auto_prec']:.3f}" if row["auto_n"] else "  n/a"
                print(f"{row['subject_th']:>8}{row['type_th']:>8}"
                      f"{row['coverage']:>9.1%}{aps:>10}{row['auto_n']:>8}")

        # 自动入库但未判对的（精度漏网）抽样，便于修正
        misses = [
            (g["content"][:40], dec.subject.value, g.get("subject"),
             dec.subject.confidence)
            for g, dec in zip(gold, r["decisions"])
            if dec.auto_accept and dec.subject.value != (g.get("subject") or "")
        ]
        if misses:
            print(f"\n[漏网] 自动入库但科目判错 {len(misses)} 例（前 10）：")
            for c, pred, gold_s, conf in misses[:10]:
                print(f"  pred={pred}({conf:.2f}) gold={gold_s} | {c}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
