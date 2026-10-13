# -*- coding: utf-8 -*-
"""跨门类学科（管综/法硕/教育学/心理学/中西医）文档级判定与回写。

为什么要它（实测口径，见 docx/14）：
  147 条人工判分样本里 29 条（20%）是本平台候选集没有的学科，现网把其中
  90.9% 硬塞进了电子/数学/英语学科池；按文件名线索估计全库规模 318 篇文档 /
  5127 块（8.4%）。而且 26/29 条域外块来自"整篇都是那个学科"的文档
  —— 说明正确的判定粒度是**文档级**，块级三路融合永远猜不出"候选集外还有候选集"。

判定口径（两条证据，必须同时达标才写）：
  1. 文件名线索：统考科目代码/名称（199 管综、396 经济类联考、397/497 法硕、
     311/333 教育学、312/347 心理学、306 西医综合、320 中医综合等）；
  2. 正文术语密度：取该文档最长的 3 个块，统计各学科专属术语出现次数/千字。
单靠文件名在样本上只召回 12/24 篇且有误伤，所以两条都要；写库前先看 --dry-run 审计表。

用法：
    python scripts/label_doc_discipline.py --audit out.json          # 只算不写
    python scripts/label_doc_discipline.py --apply                   # 审完再写
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

#: 新学科 → (文件名强线索, 正文术语)。术语表刻意只收高区分度的，不收"学生/学习"这类共用词。
DISCIPLINES: Dict[str, Dict[str, object]] = {
    "管理类联考综合": {
        "name": re.compile(r"(管综|199管理类|管理类联考|MPAcc|MPA|MEM|会计专硕|审计专硕|物流工程|项目管理)", re.I),
        "terms": ["条件充分性判断", "论证有效性分析", "逻辑推理", "支持以下哪项", "削弱以下", "假设上述",
              "以下哪项为真", "求解：以下", "管综", "MBA", "MPAcc"],
    },
    "经济类联考综合": {
        "name": re.compile(r"(经济类联考|(?<!\d)396(?!\d)|经综|(?<!\d)369(?!\d))", re.I),
        "terms": ["微观经济", "需求弹性", "机会成本", "边际效用", "GDP", "财政政策", "货币政策",
              "完全竞争", "外部性", "国际收支", "经综"],
    },
    "法律硕士专业基础": {
        "name": re.compile(r"(法硕|法律硕士|(?<!\d)39[78](?!\d)|(?<!\d)49[78](?!\d)|非法学|法学联考)", re.I),
        "terms": ["法律关系", "犯罪构成", "善意取得", "无权代理", "合同无效", "正当防卫",
              "有期徒刑", "标的物", "刑法学", "民法学", "法理学", "法律硕士"],
    },
    "教育学专业基础": {
        "name": re.compile(r"(教育学|(?<!\d)311(?!\d)|(?<!\d)333(?!\d)|教育综合|教育学期末|课程论)", re.I),
        "terms": ["德育原则", "课程目标", "夸美纽斯", "赫尔巴特", "裴斯泰洛齐", "最近发展区",
              "维果茨基", "义务教育法", "课程标准", "教学过程的原则", "班级授课制"],
    },
    "心理学专业基础": {
        "name": re.compile(r"(心理学|(?<!\d)312(?!\d)|(?<!\d)347(?!\d)|发展心理学|教育心理|心理统计)", re.I),
        "terms": ["普通心理学", "发展心理学", "教育心理学", "社会心理学", "认知心理学", "实验心理学",
              "心理统计", "心理测量", "格式塔", "冯特", "斯金纳", "正强化", "负强化",
              "短时记忆", "记忆广度", "韦伯定律", "费希纳", "信号检测论"],
    },
    "西医综合": {
        "name": re.compile(r"(西医综合|临床综合|(?<!\d)306(?!\d)|内科学|外科学|病理学|生理学|生物化学|诊断学)", re.I),
        "terms": ["患者", "并发症", "首选的治疗是", "白细胞", "血小板", "心肌梗死", "肝硬化",
              "肾小球", "大出血", "休克", "阑尾炎", "骨折", "西医综合", "内科学", "外科学"],
    },
    "中医综合": {
        "name": re.compile(r"(中医综合|(?<!\d)320(?!\d)|中药学|方剂学|针灸|黄帝内经|伤寒论|金匮|温病)", re.I),
        "terms": ["辨证", "方剂", "汤头", "穴位", "经络", "气血", "舌红", "脉数", "痰饮",
              "肾阴虚", "健脾", "中药", "伤寒论", "金匮", "温病", "中医综合"],
    },
}

#: 具体专业课标签：判定新学科时默认不覆盖（这些是用户真正在备考的电子/通信口径）
PROTECTED_SUBJECTS = {
    "数字电子技术", "模拟电子技术", "电路", "电路分析", "信号与系统",
    "通信原理", "光学", "光学与工程光学", "普通物理",
    "计算机学科专业基础408", "电气工程", "电子科学与技术", "控制科学与工程",
}
#: 只允许"文件名强线索"才翻转的软标签（公共课/兜底口径）
SOFT_SUBJECTS = {"数学", "英语", "政治", "其他", "真题综合", "数模电", "公共课-数学", ""}


#: 文件名命中权重。取 25 是实测结论：正文术语密度最高的一条误判也只有 14.6
#: （"333"在医学答案数字串里命中 9 次），文件名代码（312/306/396…）是权威证据，
#: 不该被正文噪声稀释；多名命中时靠下面的 name_only 豁免与 margin 共同把关。
NAME_WEIGHT = 25.0
#: 密度证据的最小正文长度：几百字的碎片里几个术语就能把密度顶到 10+。
DENSITY_MIN_BLOB = 1000


def _term_density(texts: List[str], terms: List[str]) -> float:
    """术语密度：每千字命中次数（跨该文档最长 3 块）。"""
    blob = "\n".join(texts)
    if not blob:
        return 0.0
    hits = sum(blob.count(t) for t in terms)
    return hits / max(len(blob), 1) * 1000.0


def judge(doc, chunks: List[str], *, min_density: float, min_margin: float,
          name_bypass: bool = True, allow_density: bool = False) -> Optional[Dict]:
    """返回判定结果 {subject, name_hit, density, margin, action} 或 None（不动）。"""
    blob_chars = sum(len(t) for t in chunks)
    scored = []
    for subj, spec in DISCIPLINES.items():
        name_hit = bool(spec["name"].search(doc.file_name or ""))
        dens = _term_density(chunks, list(spec["terms"]))
        scored.append({"subject": subj, "name_hit": name_hit, "density": dens,
                       "score": (NAME_WEIGHT if name_hit else 0.0) + dens})
    scored.sort(key=lambda x: -x["score"])
    best, second = scored[0], (scored[1] if len(scored) > 1 else {"score": 0.0, "subject": ""})
    margin = best["score"] - second["score"]
    cur = (doc.subject or "").strip()

    def _skip(action):
        return {"subject": best["subject"], "name_hit": best["name_hit"],
                "density": round(best["density"], 2), "margin": round(margin, 2),
                "action": action, "current": cur}

    # 密度证据只在正文够长时才算数；文件名线索不受长度限制
    density_ok = best["density"] >= min_density and blob_chars >= DENSITY_MIN_BLOB
    if not best["name_hit"]:
        if not density_ok:
            return None
        # 实测：只凭正文密度改判 4 篇里错 3 篇（2017 英语一真题解析因经济学题材
        # 术语密度 5.35 被判成经综）。所以密度默认只做同名核对，不单独改判，
        # 需要实验该口径时才加 --allow-density。
        return _skip("skip_density_only") if not allow_density else None

    # 文件名只命中一个学科时（如「312心理学」），代码就是权威证据，不被正文密度稀释；
    # 多名命中（如既含「心理学」又含「生理学」）仍需 margin 判别。
    name_only = name_bypass and sum(1 for s in scored if s["name_hit"]) == 1
    if margin < min_margin and not name_only:
        return None
    if cur in PROTECTED_SUBJECTS:
        # 具体专业课（数电/模电/电路…）被改判需要文件名强线索——上面已保证 name_hit，
        # 这里只打个标记，供审计表单独核一遍（apply 前必须看）。
        out = _skip("assign")
        out["over_protected"] = True
        return out
    if cur not in SOFT_SUBJECTS and cur:
        return _skip("skip_unknown_current")
    return _skip("assign")


def main() -> int:
    ap = argparse.ArgumentParser(description="跨门类学科文档级判定")
    ap.add_argument("--min-density", type=float, default=3.0, help="术语密度下限（次/千字）")
    ap.add_argument("--min-margin", type=float, default=2.0, help="与第二名的分数差下限")
    ap.add_argument("--no-name-bypass", action="store_true",
                    help="关闭「文件名唯一命中豁免 margin」，回退旧口径做对照")
    ap.add_argument("--allow-density", action="store_true",
                    help="允许仅凭正文术语密度改判（实测 4 篇错 3 篇，默认关闭）")
    ap.add_argument("--audit", default="", help="审计 JSON 输出路径")
    ap.add_argument("--apply", action="store_true", help="真正回写 documents.subject")
    ap.add_argument("--grade-gold", default="", help="用 147 人工判分样本验证文档级口径")
    args = ap.parse_args()

    from database import SessionLocal
    from models import Document, KnowledgeChunk

    db = SessionLocal()
    try:
        texts: Dict[int, List[str]] = collections.defaultdict(list)
        for did, text in (db.query(KnowledgeChunk.document_id, KnowledgeChunk.text).all()):
            if text:
                texts[did].append(text)
        # 每篇取最长的 3 块算术语密度：短块/目录行没有判别力
        chunk_map = {k: sorted(v, key=len, reverse=True)[:3] for k, v in texts.items()}
        docs = db.query(Document).all()
        results = []
        for d in docs:
            j = judge(d, chunk_map.get(d.id, []),
                      min_density=args.min_density, min_margin=args.min_margin,
                      name_bypass=not args.no_name_bypass,
                      allow_density=args.allow_density)
            if j:
                j["doc_id"] = d.id
                j["file_name"] = (d.file_name or "")[:70]
                results.append(j)

        by_action = collections.Counter(r["action"] for r in results)
        print(f"文档 {len(docs)} 篇，产生判定 {len(results)} 条")
        for a, n in by_action.most_common():
            print(f"  {a:<22}{n}")
        assign = [r for r in results if r["action"] == "assign"]
        dist = collections.Counter(r["subject"] for r in assign)
        print("\n将写入的学科分布：")
        for s, n in dist.most_common():
            print(f"  {s:<14}{n} 篇")
        print("\n样例（前 12 条）：")
        for r in assign[:12]:
            print(f"  [{r['subject']}] {r['file_name']}  "
                  f"现学科={r['current'] or '空'} 名={int(r['name_hit'])} 密度={r['density']}")
        over = [r for r in assign if r.get("over_protected")]
        if over:
            print(f"\n⚠️ 覆盖具体专业课标签的改判 {len(over)} 篇（逐条核）：")
            for r in over:
                print(f"  [{r['subject']}] 现={r['current']} 密度={r['density']} {r['file_name']}")

        if args.grade_gold:
            _grade_gold(db, assign, args.grade_gold)

        if args.audit:
            with open(args.audit, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=1)
            print(f"审计输出：{args.audit}")

        if args.apply:
            changed = 0
            for r in assign:
                d = db.get(Document, r["doc_id"])
                if d is not None and (d.subject or "").strip() != r["subject"]:
                    d.subject = r["subject"]
                    changed += 1
            db.commit()
            print(f"已回写 documents.subject：{changed} 篇")
        else:
            print("（未回写；确认审计表后加 --apply）")
        return 0
    finally:
        db.close()


def _grade_gold(db, assign: List[Dict], gold_path: str) -> None:
    """用 147 人工判分样本核**落库后状态**：域外文档召回率 / 域内文档误伤率。

    口径注意：判"这篇文档现在是哪个学科"必须读 `documents.subject`（已回写的
    真值），不能只看本次 assign 列表 —— 重跑时已正确的文档会走
    skip_unknown_current 分支，不出现在 assign 里，只看它会假性召回 0。
    """
    items = json.load(open(gold_path, encoding="utf-8"))["items"]
    from models import Document
    from services.taxonomy import CROSS_SUBJECTS
    id2name = {d.id: (d.file_name or "") for d in db.query(Document).all()}
    labelled = {id2name.get(d.id, "") for d in
                db.query(Document).filter(Document.subject.in_(tuple(CROSS_SUBJECTS))).all()}
    pending = {r["file_name"] for r in assign}
    got = labelled | pending          # 本次尚未 apply 时，待写入的也算判出
    gold_by_doc: Dict[str, set] = collections.defaultdict(set)
    for x in items:
        gold_by_doc[x["doc_name"]].add("域外" if x["label_l1"] == "其他" else "域内")
    od_docs = [n for n, g in gold_by_doc.items() if g == {"域外"}]
    id_docs = [n for n, g in gold_by_doc.items() if "域内" in g]
    od_hit = sum(1 for n in od_docs if n in got)
    id_fp = sum(1 for n in id_docs if n in got)
    print(f"\n[gold 文档级口径] 纯域外文档 {len(od_docs)} 篇：判出 {od_hit} 篇（召回 {od_hit/max(len(od_docs),1):.0%}）")
    print(f"                  含域内块文档 {len(id_docs)} 篇：被改判 {id_fp} 篇（误伤口径，需逐条看）")
    print(f"                  跨门类标签文档共 {len(labelled)} 篇，本次待写入 {len(assign)} 篇")


if __name__ == "__main__":
    sys.exit(main())
