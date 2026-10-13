# -*- coding: utf-8 -*-
"""chunk 分类评估闭环（docx/14 阶段 B）。所有词表/权重改动必须过这份报表。

两种模式：
1) 抽样出题（给人工标注）：
    python scripts/chunk_classify_eval.py --seed 250 --out scripts/data/chunk_eval_seed.json
   按学科分层抽样，块文本 + 当前三路预测一并给出，人只填 label_l1 / label_l3。
2) 判分（标注完成后）：
    python scripts/chunk_classify_eval.py --grade scripts/data/chunk_eval_seed.json [--llm]
    python scripts/chunk_classify_eval.py --grade --db        # 用 annotation_samples 表
   输出整体 accuracy、macro-F1、分科 P/R/F1、低置信占比、三路一致率、
   误分类混淆 Top 对。

判分口径：路1+路2 必跑；--llm 时才花模型调用（评估融合全配置）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

MIN_CHARS = 150


def sample_seed(db, n: int, out_path: str) -> int:
    """按学科分层随机抽 chunk，导出标注模板。"""
    from models import Document, KnowledgeChunk
    from services.chunk_classifier import keyword_scores, load_prototypes, subject_candidates

    cands = set(subject_candidates())
    by_subject: dict = defaultdict(list)
    docs = {d.id: d for d in db.query(Document).all()}
    for c in db.query(KnowledgeChunk).filter(KnowledgeChunk.text.isnot(None)).yield_per(500):
        t = c.text or ""
        if len(t) < MIN_CHARS or c.document_id not in docs:
            continue
        subj, confident = keyword_scores(docs[c.document_id].file_name, t)
        key = subj if (subj in cands and confident) else "未定"
        by_subject[key].append(c.id)

    rng = random.Random(42)
    pool = [v for vals in by_subject.values() for v in vals]
    rng.shuffle(pool)
    picked = pool[: n * 2]
    chosen: list = []
    per = max(1, n // max(len([k for k in by_subject if k != "未定"]), 1))
    quota = {k: per for k in by_subject}
    for cid in picked:
        c = db.get(KnowledgeChunk, cid)
        if c is None:
            continue
        doc = docs.get(c.document_id)
        key = keyword_scores(doc.file_name, c.text)[0] or "未定"
        if quota.get(key, 0) <= 0 and len(chosen) >= n:
            continue
        if quota.get(key, 1) <= 0:
            continue
        quota[key] = quota.get(key, 0) - 1
        chosen.append({
            "chunk_id": c.id,
            "doc_name": (doc.file_name or "")[:60],
            "text": (c.text or "")[:600],
            "pred_l1": c.subject,
            "pred_l3": c.l3_content_type,
            "label_l1": "",   # ← 人工填
            "label_l3": "",   # ← 人工填
        })
        if len(chosen) >= n:
            break
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(chosen, f, ensure_ascii=False, indent=1)
    print(f"✅ 标注模板 {len(chosen)} 条 → {out_path}")
    print("   填写 label_l1（必填，候选学科见 taxonomy）与 label_l3 后，跑 --grade 判分。")
    return 0


def _prf(golds: list, preds: list, labels: list):
    tp = defaultdict(int); fp = defaultdict(int); fn = defaultdict(int)
    for g, p in zip(golds, preds):
        if p == g:
            tp[g] += 1
        else:
            fp[p] += 1; fn[g] += 1
    rows, f1s = [], []
    for lb in labels:
        prec = tp[lb] / (tp[lb] + fp[lb]) if (tp[lb] + fp[lb]) else 0.0
        rec = tp[lb] / (tp[lb] + fn[lb]) if (tp[lb] + fn[lb]) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        rows.append((lb, prec, rec, f1, tp[lb] + fn[lb]))
        if tp[lb] + fn[lb]:          # macro 只算出现过的科
            f1s.append(f1)
    return rows, (sum(f1s) / len(f1s) if f1s else 0.0)


def grade(db, source: str, use_llm: bool) -> int:
    from services import chunk_classifier as cc
    from services.chunk_classifier import keyword_scores, load_prototypes, vector_scores, encode_texts

    if source == "--db":
        from models import AnnotationSample
        items = [
            {"chunk_id": a.chunk_id, "text": a.chunk_text, "label_l1": a.label_l1}
            for a in db.query(AnnotationSample).filter(
                AnnotationSample.label_l1.isnot(None), AnnotationSample.label_l1 != "")
        ]
    else:
        with open(source, encoding="utf-8") as f:
            raw = json.load(f)
        # 兼容两种落盘格式：--seed 的扁平数组，和判分回填后的 {"items": [...]}
        rows = raw["items"] if isinstance(raw, dict) and "items" in raw else raw
        items = [x for x in rows if (x.get("label_l1") or "").strip()]
    if not items:
        print("没有带人工标签的样本，先 --seed 抽样标注")
        return 1

    protos = load_prototypes(db)
    texts = [x["text"] for x in items]
    emb = encode_texts(texts) if protos else None

    golds, preds, confs = [], [], []
    agree_vec_kw = agree_total = 0
    for i, x in enumerate(items):
        vec_dist = vector_scores(None if emb is None else emb[i], protos)
        kw_subj, kw_w = keyword_scores(x.get("doc_name", ""), x["text"])
        lab = cc.ChunkLabel(l3_content_type=cc.l3_rules(x["text"]))
        cc.fuse(lab, kw_subj, kw_w, vec_dist, None)
        vec_top = max(vec_dist, key=lambda s: vec_dist[s]) if vec_dist else ""
        if vec_top and kw_subj:
            agree_total += 1
            agree_vec_kw += int(vec_top == kw_subj)
        if use_llm and cc.needs_llm(lab, kw_subj, vec_top):
            out = cc.llm_classify(x.get("doc_name", ""), x["text"], i)
            if out:
                lab2 = cc.ChunkLabel(l3_content_type=cc.l3_rules(x["text"]))
                cc.fuse(lab2, kw_subj, kw_w, vec_dist, out)
                if lab2.subject:
                    lab = lab2
        golds.append(cc._normalize_subject(x["label_l1"]) or x["label_l1"])
        preds.append(lab.subject or "")
        confs.append(lab.confidence)
        x["pred_l1"] = lab.subject
        x["pred_conf"] = lab.confidence

    n_items = len(golds)
    acc = sum(g == p for g, p in zip(golds, preds)) / n_items
    labels = sorted(set(golds) | set(preds))
    rows, macro_f1 = _prf(golds, preds, labels)
    low = sum(1 for c in confs if c < cc.CONF_THRESHOLD) / n_items

    # 域外样本（人工标 '其他'：医学/法学/管综等非候选学科）单独计口径，
    # 否则整体 accuracy 会被分类器无权命中的类别压低。
    out_idx = [i for i, x in enumerate(items) if (x["label_l1"] or "").strip() == "其他"]
    out_hit = sum(1 for i in out_idx if preds[i] == "其他")
    core_idx = [i for i in range(n_items) if i not in set(out_idx)]
    core_acc = (sum(1 for i in core_idx if golds[i] == preds[i]) / core_idx.__len__()
                if core_idx else 0.0)

    arm = "三" if use_llm else "二"
    print(f"样本 {n_items}（域内 {len(core_idx)} / 域外其他 {len(out_idx)}）  | 路: {arm}")
    print(f"  Accuracy(全口径)   {acc:.3f}  | Macro-F1 {macro_f1:.3f}")
    print(f"  Accuracy(仅域内科目) {core_acc:.3f}  | 域外正确弃权率 {out_hit}/{len(out_idx)}")
    print(f"低置信占比(<{cc.CONF_THRESHOLD}) {low:.1%}  | 向量×关键词头名一致率 "
          f"{(agree_vec_kw / agree_total if agree_total else 0):.1%}")
    print(f"{'学科':<14}{'P':>7}{'R':>7}{'F1':>7}{'支撑':>5}")
    for lb, p, r, f1, sup in sorted(rows, key=lambda t: -t[3]):
        if sup:
            print(f"{lb:<14}{p:>7.2f}{r:>7.2f}{f1:>7.2f}{sup:>5}")
    conf_pairs = Counter(
        (g, p) for g, p in zip(golds, preds) if g != p and p
    ).most_common(10)
    if conf_pairs:
        print("混淆 Top：")
        for (g, p), n in conf_pairs:
            print(f"  {g} → 误判为 {p}: {n}")
    else:
        print("无误分类（或全部低置信未判）")

    dump = ""
    if source != "--db":
        dump = os.path.join(os.path.dirname(os.path.abspath(source)),
                            "chunk_eval_graded.json")
        with open(dump, "w", encoding="utf-8") as f:
            json.dump({"arm": arm, "accuracy": round(acc, 4),
                       "accuracy_in_taxonomy": round(core_acc, 4),
                       "macro_f1": round(macro_f1, 4),
                       "low_conf_rate": round(low, 4), "items": items}, f,
                      ensure_ascii=False, indent=1)
        print(f"逐条预测已写入 {dump}")

    # 入库 eval_runs：趋势页读这张表，metrics 保持上面打印用的同一口径
    try:
        from services.eval_store import record_eval_run, text_fingerprint

        report = {
            "n_items": n_items, "n_in_taxonomy": len(core_idx),
            "n_out_of_domain": len(out_idx),
            "accuracy_all": round(acc, 4), "accuracy_in_taxonomy": round(core_acc, 4),
            "macro_f1": round(macro_f1, 4), "low_conf_rate": round(low, 4),
            "vector_keyword_agreement": (round(agree_vec_kw / agree_total, 4)
                                         if agree_total else None),
            "out_of_domain_abstain": f"{out_hit}/{len(out_idx)}",
            "per_subject": {lb: {"precision": round(p, 4), "recall": round(r, 4),
                                 "f1": round(f1, 4), "support": sup}
                            for lb, p, r, f1, sup in rows if sup},
            "confusion_top": [{"gold": g, "pred": p, "n": n} for (g, p), n in conf_pairs],
        }
        run_id = record_eval_run(
            "recognition", arm=f"路{arm}", metrics=report, primary_metric=core_acc,
            n_samples=n_items,
            fingerprint=text_fingerprint([str(x["chunk_id"]) for x in items]),
            report_path=dump,
            notes=f"主指标=域内科目 accuracy({core_acc:.3f})；域外正确弃权 {out_hit}/{len(out_idx)}",
            db=db,
        )
        print(f"入库：eval_runs #{run_id}" if run_id else "eval_runs 入库失败（报告已打印）")
    except Exception as e:  # noqa: BLE001
        print(f"eval_runs 入库异常（忽略）: {e}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="chunk 分类评估闭环")
    ap.add_argument("--seed", type=int, help="抽 N 条生成标注模板")
    ap.add_argument("--out", default=os.path.join("scripts", "data", "chunk_eval_seed.json"))
    ap.add_argument("--grade", nargs="?", const="--db", help="判分：标注 JSON 路径，或 --grade 不带值用 annotation_samples 表")
    ap.add_argument("--llm", action="store_true", help="判分时启用路3")
    args = ap.parse_args()

    from database import SessionLocal
    from database import Base, engine
    Base.metadata.create_all(bind=engine)  # annotation_samples 幂等补建
    db = SessionLocal()
    try:
        if args.seed:
            return sample_seed(db, args.seed, args.out)
        if args.grade:
            return grade(db, args.grade, args.llm)
        ap.print_help()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
