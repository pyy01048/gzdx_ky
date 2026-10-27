# -*- coding: utf-8 -*-
"""临时诊断：题库分类逐科目混淆 + 覆盖/精度分解。"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from services.quiz_classifier_v2 import classify_batch_v2


def main():
    db = SessionLocal()
    try:
        gold = json.load(open("scripts/data/quiz_classify_silver.json", encoding="utf-8"))
        qs = [{"content": g["content"], "options": g.get("options")} for g in gold]
        decs = classify_batch_v2(qs, db=db, use_llm=False)

        stats = collections.defaultdict(
            lambda: {"n": 0, "ok": 0, "auto": 0, "auto_ok": 0, "pred": collections.Counter()}
        )
        for g, d in zip(gold, decs):
            s = stats[g["subject"]]
            s["n"] += 1
            s["pred"][d.subject.value] += 1
            if d.subject.value == g["subject"]:
                s["ok"] += 1
            if d.auto_accept:
                s["auto"] += 1
                if d.subject.value == g["subject"]:
                    s["auto_ok"] += 1

        print(f"{'subject':<22}{'n':>4}{'acc':>7}{'auto':>6}{'autoPrec':>9}")
        tot = totok = ta = tao = 0
        for subj in sorted(stats, key=lambda x: -stats[x]["n"]):
            s = stats[subj]
            acc = s["ok"] / s["n"]
            ap = s["auto_ok"] / s["auto"] if s["auto"] else float("nan")
            print(f"{subj:<22}{s['n']:>4}{acc:>7.2f}{s['auto']:>6}{ap:>9.2f}")
            tot += s["n"]; totok += s["ok"]; ta += s["auto"]; tao += s["auto_ok"]
        print(f"{'TOTAL':<22}{tot:>4}{totok/tot:>7.2f}{ta:>6}{tao/ta if ta else 0:>9.2f}")
        print()
        for subj in sorted(stats, key=lambda x: -stats[x]["n"]):
            s = stats[subj]
            top = ", ".join(f"{k}={v}" for k, v in s["pred"].most_common(4))
            print(f"  {subj}: pred[{top}]")
    finally:
        db.close()


if __name__ == "__main__":
    main()
