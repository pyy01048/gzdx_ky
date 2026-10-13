"""域外污染定位：33/147 人工判分为"其他"（医学/法学/教育学/心理学/管综），
现网把它们 90.9% 打进了本平台学科池。这里量三件事：

1. 域外块是不是按"整篇文档"聚集的（是 → 文档级判定就能治，块级怎么调都治不好）
2. 只靠文件名能不能识别域外文档（能 → 零成本规则）
3. 现有学科候选集覆盖了多少语料（缺哪些学科 → 补质心而不是打"其他"）

用法：python scripts/outlier_doc_probe.py
"""
import collections
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

GOLD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "chunk_eval_graded.json")
SCOPES = ("数字电子技术", "模拟电子技术", "数学", "英语", "政治", "计算机学科专业基础408")

#: 域外学科线索（只用于统计口径，不是最终规则）
OD_HINT = re.compile(r"(医学|西医|中医|临床|护理|药学|口腔|法学|法律|法硕|民法|刑法|教育学|教育综合|"
                     r"心理|管理综合|MPAcc|会计|审计|物流|化学|生物|历史|地理|思政理论|力学|结构)")


def main() -> int:
    items = json.load(open(GOLD, encoding="utf-8"))["items"]
    by_doc = collections.defaultdict(list)
    for x in items:
        by_doc[x["doc_name"]].append(x)

    print("[1] 域外块的文档聚集度")
    pure_od_docs = mixed = 0
    for name, xs in by_doc.items():
        od = sum(1 for x in xs if x["label_l1"] == "其他")
        if od == 0:
            continue
        if od == len(xs):
            pure_od_docs += 1
        else:
            mixed += 1
    od_items = [x for x in items if x["label_l1"] == "其他"]
    print(f"  域外样本 {len(od_items)} 条，分布在 {pure_od_docs + mixed} 篇文档里："
          f"整篇皆域外 {pure_od_docs} 篇 / 与域内混标 {mixed} 篇")
    in_od_doc = sum(1 for x in od_items
                    if all(y["label_l1"] == "其他" for y in by_doc[x["doc_name"]]))
    print(f"  即 {in_od_doc}/{len(od_items)} 条域外块可靠「文档级判定」直接摘出学科池")

    print("\n[2] 只靠文件名识别域外文档")
    hit = [n for n in by_doc if OD_HINT.search(n or "")]
    od_hit = [n for n in hit if all(x["label_l1"] == "其他" for x in by_doc[n])]
    fp = [n for n in hit if any(x["label_l1"] != "其他" for x in by_doc[n])]
    od_docs = [n for n, xs in by_doc.items() if all(x["label_l1"] == "其他" for x in xs)]
    print(f"  文件名命中线索 {len(hit)} 篇：纯域外 {len(od_hit)} 篇 / 含域内(误伤) {len(fp)} 篇；"
          f"域外文档共 {len(od_docs)} 篇 → 文件名口径召回 {len(od_hit)}/{len(od_docs)}")
    for n in od_docs[:25]:
        print(f"     · {n[:58]}  (关键词命中={'是' if OD_HINT.search(n or '') else '否'})")

    print("\n[3] 域外样本的人工 label:")
    print("  ", collections.Counter(x["label_l1"] for x in od_items))

    from database import SQLALCHEMY_DATABASE_URL
    conn = sqlite3.connect(SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "", 1))
    print("\n[4] 全库文档学科覆盖（documents.subject 现值）")
    for s, n in conn.execute("SELECT IFNULL(subject,'<null>'),COUNT(*) FROM documents "
                             "GROUP BY 1 ORDER BY 2 DESC LIMIT 14"):
        print(f"  {s:<24}{n}")
    # 域外文档在全库的规模估计：用标题线索扫 documents
    rows = conn.execute("SELECT id,file_name,subject FROM documents").fetchall()
    od_like = [r for r in rows if OD_HINT.search(r[1] or "")]
    print(f"\n[5] 全库 {len(rows)} 篇文档中文件名带域外学科线索: {len(od_like)} 篇 "
          f"({len(od_like)/max(len(rows),1):.1%})")
    print("  这些文档现有学科:", collections.Counter(r[2] for r in od_like).most_common(8))
    ch = conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
    ids = ",".join(str(r[0]) for r in od_like)
    if ids:
        n = conn.execute(f"SELECT COUNT(*) FROM knowledge_chunks WHERE document_id IN ({ids})").fetchone()[0]
        print(f"  对应 chunk {n} 条 / 全库 {ch} 条 = {n/ch:.1%} —— 这就是学科池污染的规模上限")
    return 0


if __name__ == "__main__":
    sys.exit(main())
