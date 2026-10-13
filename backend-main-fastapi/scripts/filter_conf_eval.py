"""学科过滤口径实测：现网硬相等 vs 置信度门限放行，在 147 人工判分样本上的漏检/精度对比。

只读，不改库。用法：python scripts/filter_conf_eval.py
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "chunk_eval_graded.json")
TH = float(os.environ.get("CHUNK_CONF_THRESHOLD", 0.40))


def _db_path() -> str:
    """跟 app 走同一个库（DATABASE_PATH 指向 D:\\平台\\database\\kaoyan.db），别自己猜。"""
    from database import SQLALCHEMY_DATABASE_URL
    return SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1)


def main() -> int:
    conn = sqlite3.connect(_db_path())
    cols = {r[1] for r in conn.execute("PRAGMA table_info(knowledge_chunks)")}
    print(f"knowledge_chunks 标签列: {sorted(c for c in cols if c.startswith(('l2_', 'l3_', 'classify_')))}")

    n_all = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    n_lab = conn.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE classify_confidence IS NOT NULL").fetchone()[0]
    print(f"chunk 总数={n_all} 已打标={n_lab}")
    print("置信分布（已打标）:")
    for lo, hi in [(0, 0.2), (0.2, TH), (TH, 0.55), (0.55, 0.75), (0.75, 1.01)]:
        c = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE classify_confidence >= ? AND classify_confidence < ?",
            (lo, hi)).fetchone()[0]
        print(f"  [{lo:.2f},{hi:.2f}) {c} ({c / max(n_lab,1):.1%})")
    print("来源分布:", conn.execute(
        "SELECT classify_source, COUNT(*) FROM knowledge_chunks WHERE classify_confidence IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC").fetchall())

    # 镜像表学科是否跟着 chunk 标签走
    try:
        mism = conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks_fts f JOIN knowledge_chunks k ON k.id=f.chunk_id "
            "IFNULL(f.subject,'')<>IFNULL(k.subject,'')").fetchone()[0]
        tot = conn.execute("SELECT COUNT(*) FROM knowledge_chunks_fts").fetchone()[0]
        print(f"FTS 镜像学科与 chunk 表不一致: {mism}/{tot} ({mism/max(tot,1):.1%})")
    except sqlite3.Error as e:
        print("FTS 镜像检查失败:", e)

    items = json.load(open(GOLD, encoding="utf-8"))["items"]
    in_dom = [i for i in items if i["label_l1"] not in ("其他", "真题综合")]
    shield_now = shield_gated = 0
    for i in in_dom:
        pred, conf, gold = i["pred_l1"], float(i["pred_conf"] or 0), i["label_l1"]
        if not pred:
            continue
        if pred != gold:
            shield_now += 1          # 硬相等：错标签把块永久藏起来
            if conf >= TH:
                shield_gated += 1    # 门限：只有高置信错标才藏
    print(f"\n147 样本中域内 {len(in_dom)} 条，可判 pred 的块里：")
    print(f"  现网硬相等会把真实学科漏掉的块: {shield_now}")
    print(f"  置信门限后仍会漏掉: {shield_gated}（高置信错标）")
    print(f"  门限挽回: {shield_now - shield_gated} 条 → 这些块从『永久不可检索』变回可被向量/FTS 命中")

    lo_wrong = sum(1 for i in in_dom if i["pred_l1"] and i["pred_l1"] != i["label_l1"]
                   and float(i["pred_conf"] or 0) < TH)
    lo_all = sum(1 for i in in_dom if float(i["pred_conf"] or 0) < TH)
    print(f"  低置信块 {lo_all} 条，其中标签判错 {lo_wrong} 条（{lo_wrong/max(lo_all,1):.0%}）——"
          f"这就是硬过滤引入的随机噪声比例")
    return 0


if __name__ == "__main__":
    sys.exit(main())
