"""学科打标策略实测：弃权(junk/置信/域外相似度门限) × 检索过滤口径(硬相等/置信门控)。

用 147 条人工判分样本（scripts/data/chunk_eval_graded.json）在 CPU 上复现
classify_document 的每块证据（路1 bge 质心 + 路2 关键词，路3 LLM 需要 GPU，跳过），
再按不同策略计算两个检索口径指标：

  域内可检索率 = 真实学科的池子里能看到该块的比例（漏检的补集）
  池精确率     = 某学科池子里真正属于该学科的比例（污染的反面）

用法：python scripts/recognition_policy_eval.py
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "chunk_eval_graded.json")
TH = 0.40
SCOPES = ("数字电子技术", "模拟电子技术", "数学", "英语", "政治", "计算机学科专业基础408")


def features(db):
    """逐块复现证据：向量原始余弦 + softmax 分布 + 关键词 + junk 命中 + 融合结果。"""
    from services import chunk_classifier as cc
    from services.chunk_classifier import encode_texts, keyword_scores, load_prototypes

    items = json.load(open(GOLD, encoding="utf-8"))["items"]
    protos = load_prototypes(db)
    emb = encode_texts([i["text"] for i in items])
    if emb is None:
        raise SystemExit("bge 不可用，路1 无法复现")

    out = []
    for i, x in enumerate(items):
        q = cc._l2norm(np.asarray(emb[i], dtype=np.float32))
        sims = {s: float(np.dot(q, cc._l2norm(p))) for s, p in protos.items()}
        vec_dist = cc.vector_scores(emb[i], protos)
        kw_subj, kw_w = keyword_scores(x.get("doc_name", ""), x["text"])
        lab = cc.ChunkLabel(l3_content_type=cc.l3_rules(x["text"]))
        cc.fuse(lab, kw_subj, kw_w, vec_dist, None)
        ranked = sorted(lab.votes.items(), key=lambda kv: -kv[1])
        pua = sum(1 for ch in x["text"][:600] if "\ue000" <= ch <= "\uf8ff")
        out.append({
            "gold": cc._normalize_subject(x["label_l1"]) or x["label_l1"],
            "text": x["text"],
            "sub": lab.subject,
            "alt": ranked[1][0] if len(ranked) > 1 else "",
            "conf": lab.confidence,
            "src": lab.source,
            "kw": kw_subj,
            "kw_w": kw_w,
            "top_sim": max(sims.values()) if sims else 0.0,
            "gold_sim": sims.get(x["label_l1"], -1.0),
            "votes": lab.votes,
            "sims": sims,
            "junk": cc.junk_reason(x["text"]),
            "pua_share": pua / max(len(x["text"][:600]), 1),
        })
    return out



def stamp(f, *, junk=None, use_alt=False, sim_floor=0.0):
    """按策略决定写入的 (subject, alt_subject)。

    弃权/相似度门限命中时 **alt 一并置空**：弃权语义是"不猜学科"，生产里对应
    alt 列同样不写，否则放宽过滤会把已判弃权的块重新捞回学科池。
    """
    if junk and junk(f):
        return "其他", ""
    if sim_floor and f["top_sim"] < sim_floor:
        return "其他", ""
    return f["sub"], (f["alt"] if use_alt else "")


def score(fs, policy):
    """口径一致地算三项检索指标。

    **池成员条件必须等于检索放行条件**：生产过滤是 `subject = S OR alt_subject = S`，
    所以 use_alt=True 时 alt 命中的块同样进入池子，precision 分母必须一起放宽。
    历史版本只放宽 recall 的分母（precision 仍按 top-1 组池），于是「第二志愿放行」
    看上去零精度代价（0.883→0.883）；按生产语义实测是 0.862→0.667，F1 −10.6pt。
    这条口径差异本身就是 bug，别再按旧数字立项。
    """
    use_alt = bool(policy.get("use_alt"))
    exposures = 0
    correct = 0
    idom = idom_hit = 0
    od = od_pollute = 0
    for f in fs:
        sub, alt = stamp(f, **{**policy, "use_alt": use_alt})
        # 该块会出现在哪些学科池里（同一块占两个池 = 两次曝光）
        pools = [sub] if sub in SCOPES else []
        if alt and alt in SCOPES and alt != sub:
            pools.append(alt)
        exposures += len(pools)
        correct += sum(1 for s in pools if s == f["gold"])
        if f["gold"] in SCOPES:
            idom += 1
            idom_hit += int(f["gold"] in pools)
        else:
            od += 1
            od_pollute += int(len(pools) > 0)
    prec = correct / exposures if exposures else 0.0
    rec = idom_hit / idom if idom else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"prec": prec, "rec": rec, "f1": f1, "exposures": exposures,
            "cov": exposures / len(fs), "pollute": od_pollute / od if od else 0.0}


def junk_variants(cc):
    """几种弃权规则的误伤/命中，先确认规则本身能不能上生产。"""
    def strict_pdf(f):
        return f["junk"] in ("pdf_operator",)

    def macro(f):
        return f["junk"] in ("pdf_operator", "compile_noise")

    def ratio(f):
        # PUA 私用区字符（PDF 符号字体残留）占比高，或 macro/pdf，或 20+ 重复字符
        return f["pua_share"] >= 0.10 or macro(f) or f["junk"] == "repeat"

    def ratio_loose(f):
        return f["pua_share"] >= 0.05 or macro(f) or f["junk"] == "repeat"

    return {"pdf_only": strict_pdf, "macro": macro,
            "pua>=10%": ratio, "pua>=5%": ratio_loose}



def report(db, fs):
    import numpy as _np
    from services import chunk_classifier as cc

    idom = [f for f in fs if f["gold"] in SCOPES]
    od = [f for f in fs if f["gold"] not in SCOPES]
    print(f"样本 {len(fs)}  域内(可判学科) {len(idom)} / 域外其他 {len(od)}")

    print("\n[1] 弃权规则体检（命中率 / 域内误伤）")
    for name, fn in junk_variants(cc).items():
        hit = [f for f in fs if fn(f)]
        fp = sum(1 for f in hit if f["gold"] in SCOPES)
        print(f"  {name:<10} 命中 {len(hit):>3}  其中域外 {len(hit)-fp:>3}  误伤域内 {fp:>3}")

    base = score(fs, {})
    print(f"\n[2] 策略对比（precision=学科池判对率，recall=域内块归到自己学科的比例）")
    print(f"{'策略':<28}{'prec':>7}{'recall':>8}{'F1':>7}{'覆盖':>7}{'域外污染':>9}")

    def line(name, policy):
        r = score(fs, policy)
        print(f"{name:<28}{r['prec']:>7.3f}{r['rec']:>8.3f}{r['f1']:>7.3f}"
              f"{r['cov']:>7.1%}{r['pollute']:>9.1%}")
        return r

    line("P0 现网(始终打标)", {})
    for name in ("pdf_only", "macro", "pua>=10%", "pua>=5%"):
        line(f"P1 +弃权[{name}]", {"junk": junk_variants(cc)[name]})
    best = max(("pdf_only", "macro", "pua>=10%", "pua>=5%"),
               key=lambda k: score(fs, {"junk": junk_variants(cc)[k]})["f1"])
    r_p0 = score(fs, {"junk": junk_variants(cc)[best]})
    r_p2 = score(fs, {"junk": junk_variants(cc)[best], "use_alt": True})
    line(f"P2 +第二志愿放行(junk={best})", {"junk": junk_variants(cc)[best], "use_alt": True})
    print(f"  ↑ P2 与 P1 同池口径：recall {(r_p2['rec'] - r_p0['rec']) * 100:+.2f}pt 但 "
          f"precision {(r_p2['prec'] - r_p0['prec']) * 100:+.2f}pt、F1 "
          f"{(r_p2['f1'] - r_p0['f1']) * 100:+.2f}pt、域外污染 "
          f"{(r_p2['pollute'] - r_p0['pollute']) * 100:+.1f}pt "
          f"（曝光 {r_p0['exposures']}→{r_p2['exposures']}）→ "
          f"{'净负，否决' if r_p2['f1'] < r_p0['f1'] else '净正，可落地'}")

    # 置信门控广播式放行：低置信块进入所有学科池
    broad = [f for f in fs if f["conf"] < TH]
    pool_now = [f for f in fs if f["sub"] in SCOPES]
    extra = sum(1 for f in broad if f["sub"] in SCOPES) * (len(SCOPES) - 1)
    prec_broad = (sum(1 for f in pool_now if f["sub"] == f["gold"]) /
                  (len(pool_now) + extra)) if pool_now else 0.0
    print(f"\n[3] 置信门控广播式放行实测：低置信块 {len(broad)} 条 × 额外 {len(SCOPES)-1} 个池 "
          f"= 池内新增 {extra} 条错误曝光，precision 从 {base['prec']:.3f} 跌到 {prec_broad:.3f} → 方案否决")

    # 第二志愿能挽回多少漏检
    recover = [f for f in idom if f["sub"] != f["gold"] and f["alt"] == f["gold"]]
    print(f"[4] 第二志愿可挽回漏检: {len(recover)}/{len(idom)} 域内块（现网 top1 打错但 top2 是对的）")

    # 相似度门限：域外块能否靠"离所有质心都远"识别
    ts_id = _np.array([f["top_sim"] for f in idom])
    ts_od = _np.array([f["top_sim"] for f in od])
    print(f"[5] 路1 top 余弦：域内 p10={_np.percentile(ts_id,10):.3f} "
          f"p50={_np.percentile(ts_id,50):.3f} | 域外 p10={_np.percentile(ts_od,10):.3f} "
          f"p50={_np.percentile(ts_od,50):.3f} p90={_np.percentile(ts_od,90):.3f}")
    ranks = []
    for f in idom:
        if f["gold_sim"] < 0:
            continue
        order = sorted(f["sims"].values(), reverse=True)
        ranks.append(order.index(f["gold_sim"]) + 1 if f["gold_sim"] in order else 99)
    if ranks:
        r = _np.array(ranks)
        print(f"[6] 纯相似度口径上限：gold 质心排名第1 的域内块 {sum(r == 1)}/{len(r)} "
              f"(前2 {sum(r <= 2)}/{len(r)}) —— 这是路1 单路的天花板")
    print(f"[7] 置信度分布：低置信(<{TH}) {sum(1 for f in fs if f['conf'] < TH)} 条, "
          f"其中打对错 {sum(1 for f in fs if f['conf'] < TH and f['sub'] != f['gold'])} 条, "
          f"打对 {sum(1 for f in fs if f['conf'] < TH and f['sub'] == f['gold'])} 条")

    # 入库：把整张策略表存进 eval_runs，否决结论也跟着留痕
    try:
        from services.chunk_classifier import JUNK_ABSTAIN_REASONS
        from services.eval_store import record_eval_run, text_fingerprint

        variants = junk_variants(cc)
        policies = {"P0_现网": score(fs, {})}
        for name in variants:
            policies[f"弃权[{name}]"] = score(fs, {"junk": variants[name]})
        prod = {"junk": variants["macro"]}
        policies["生产采用"] = score(fs, prod)
        metrics = {
            "n_items": len(fs), "n_in_scope": len(idom), "n_out_of_domain": len(od),
            "abstain_reasons": list(JUNK_ABSTAIN_REASONS),
            "policies": {k: {kk: round(vv, 4) if isinstance(vv, float) else vv
                             for kk, vv in v.items()} for k, v in policies.items()},
            "rejected": {
                "mojibake_abstention": "全库命中 18%（数学 4664 块），样本实测域内 recall 0.947→0.842",
                "conf_broadcast_gate": (
                    f"低置信(<{TH})块放行到所有学科池后 precision "
                    f"{base['prec']:.3f}→{prec_broad:.3f}（本轮实测，非历史值）"
                ),
                "second_choice_alt_filter": (
                    f"检索侧按 subject OR alt_subject 组池：precision "
                    f"{r_p0['prec']:.3f}→{r_p2['prec']:.3f}、F1 {r_p0['f1']:.3f}→{r_p2['f1']:.3f}、"
                    f"域外污染 {r_p0['pollute']:.1%}→{r_p2['pollute']:.1%}（recall 仅 "
                    f"{r_p0['rec']:.3f}→{r_p2['rec']:.3f}）→ 净负，不落地"
                ),
            },
            "second_choice_recoverable": len(recover),
            "second_choice_production_semantics": {
                "p1_top1_only": {k: round(v, 4) if isinstance(v, float) else v for k, v in r_p0.items()},
                "p2_top1_or_alt": {k: round(v, 4) if isinstance(v, float) else v for k, v in r_p2.items()},
            },
        }
        run_id = record_eval_run(
            "recognition_policy", arm="路1+路2（路3 需 GPU，本轮跳过）",
            metrics=metrics, primary_metric=policies["生产采用"]["prec"],
            n_samples=len(fs),
            fingerprint=text_fingerprint([f["text"][:200] for f in fs]),
            notes=f"主指标=生产策略学科池 precision {policies['生产采用']['prec']:.3f}"
                  f" / recall {policies['生产采用']['rec']:.3f}",
            db=db,
        )
        print(f"入库：eval_runs #{run_id}" if run_id else "eval_runs 入库失败")
    except Exception as e:  # noqa: BLE001
        print(f"eval_runs 入库异常（忽略）: {e}")



def main() -> int:
    from database import SessionLocal
    db = SessionLocal()
    try:
        fs = features(db)
        report(db, fs)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
