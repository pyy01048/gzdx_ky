"""把已有的评测报告 JSON 回填进 eval_runs（趋势页第一次上线就有历史点）。

幂等：同一 report_path 已入库就跳过。用法：python scripts/backfill_eval_runs.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

PATTERNS = (
    os.path.join("temp", "eval_qa_*.json"),
    os.path.join("temp", "eval_A_*.json"),
    os.path.join("temp", "eval_B_*.json"),
    os.path.join("exports", "eval_qa_result.json"),
)


def main() -> int:
    from database import SessionLocal
    from models import EvalRun
    from services.eval_store import file_fingerprint, record_eval_run

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = SessionLocal()
    try:
        known = {r.report_path for r in db.query(EvalRun.report_path).all() if r.report_path}
        files = sorted({os.path.join(base, p) for pat in PATTERNS
                        for p in glob.glob(os.path.join(base, pat))})
        added = 0
        for path in files:
            if path in known:
                print(f"跳过（已入库）：{os.path.basename(path)}")
                continue
            try:
                report = json.load(open(path, encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"跳过（读不了）：{os.path.basename(path)} {e}")
                continue
            models = report.get("models") or {}
            if not models:
                print(f"跳过（不是评测报告）：{os.path.basename(path)}")
                continue
            arms, unseen = [], []
            for tag, v in models.items():
                arms.append(str(tag).split("·")[0])
                u = (v or {}).get("unseen") or {}
                if u.get("n"):
                    unseen.append(float(u["accuracy"]))
            overall = [float(v.get("accuracy", 0)) for v in models.values() if v]
            primary = max(unseen) if unseen else (max(overall) if overall else None)
            run_id = record_eval_run(
                "qa", arm=",".join(sorted(set(arms))), metrics=report,
                primary_metric=primary, n_samples=report.get("cases"),
                fingerprint=file_fingerprint(path), report_path=path,
                notes=("历史报告回填；主指标=" +
                       ("未见题 accuracy" if unseen else "全量 accuracy（当时未做 holdout）")),
                db=db,
            )
            print(f"入库 eval_runs #{run_id} ← {os.path.basename(path)}"
                  f"（primary={primary}）")
            added += 1
        print(f"新增 {added} 条，历史 {len(known)} 条已在库")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
