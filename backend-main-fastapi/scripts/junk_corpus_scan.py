"""全库 chunk 垃圾块体检：每条 junk 规则在全量 61091 块上的命中规模与误伤风险。

147 人工样本只能定方向，规模口径必须看全库（纯 CPU 正则，不碰 GPU）。
用法：python scripts/junk_corpus_scan.py
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    from database import SessionLocal
    from models import KnowledgeChunk
    from services.chunk_classifier import JUNK_ABSTAIN_REASONS, junk_reason

    db = SessionLocal()
    try:
        rows = db.query(KnowledgeChunk.id, KnowledgeChunk.subject,
                        KnowledgeChunk.text).yield_per(2000)
        total = 0
        by_reason = collections.Counter()
        by_reason_subject = collections.defaultdict(collections.Counter)
        lens = collections.defaultdict(list)
        for rid, subj, text in rows:
            total += 1
            r = junk_reason(text or "")
            if not r:
                continue
            by_reason[r] += 1
            by_reason_subject[r][subj or "<null>"] += 1
            lens[r].append(len(text or ""))
        print(f"全库 chunk {total} 条")
        print(f"{'规则':<16}{'命中':>7}{'占比':>8}{'均长度':>8}   最常见学科(top4)")
        for r, n in by_reason.most_common():
            top = ", ".join(f"{s}:{c}" for s, c in by_reason_subject[r].most_common(4))
            avg = sum(lens[r]) / len(lens[r])
            print(f"{r:<16}{n:>7}{n/total:>8.2%}{avg:>8.0f}   {top}")
        print(f"\n合计命中 {sum(by_reason.values())} 条 "
              f"({sum(by_reason.values())/total:.2%})")

        from services.eval_store import record_eval_run, text_fingerprint

        metrics = {
            "total_chunks": total,
            "by_reason": {r: n for r, n in by_reason.most_common()},
            "abstain_reasons": list(JUNK_ABSTAIN_REASONS),
            "abstain_hits": sum(n for r, n in by_reason.items()
                                if r in JUNK_ABSTAIN_REASONS),
            "top_subjects_by_reason": {
                r: dict(by_reason_subject[r].most_common(6)) for r in by_reason
            },
        }
        run_id = record_eval_run(
            "corpus_probe", arm="junk_rules", metrics=metrics,
            primary_metric=round(metrics["abstain_hits"] / max(total, 1), 6),
            n_samples=total,
            fingerprint=text_fingerprint([f"{r}:{n}" for r, n in by_reason.most_common()]),
            notes="primary=弃权规则命中占比；mojibake/repeat 只统计不弃权（实测弃权误伤域内块）",
            db=db,
        )
        print(f"入库：eval_runs #{run_id}" if run_id else "eval_runs 入库失败")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
