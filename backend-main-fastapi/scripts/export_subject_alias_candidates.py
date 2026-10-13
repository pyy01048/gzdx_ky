"""#29 生成「L2 学科别名候选表」供**人工逐条过表**（只读，不写库、不改匹配逻辑）。

为什么必须人工：择校语料覆盖一直卡在 40.6%（335/825），缺口**全部是同科异名**
（大纲写「电子技术基础」，库里叫「数字电子技术」）。但别名一旦自动猜，就会把
「半导体物理」并进「电子科学与技术」这类**看似合理实则错科**的映射，覆盖面是
虚假繁荣。所以本脚本只产候选 + 证据 + 上限估算，`status` 一律 `pending`，
批准前不进 `major_coverage._lookup`，也不写 `kaoyan_major_kb_link`。

红线：
* 候选右侧**只能**是 `documents.subject ∪ knowledge_chunks.subject` 里真实存在的值；
* 候选右侧**永不含公共课语料池**（政治/数学/英语 及其 `公共课-*` 变体）——首轮实测就产出了
  「自命题数学一→数学」「英语或日语→英语」这类建议，映射过去等于用人人必考的语料刷覆盖率；
* 专业代码一律取 `kaoyan_majors.code` 的原值，**绝不生成或补全**；
* 不猜代码 → 学科的映射（口径同 `services/major_coverage.py:4-9`）。

用法：
    python scripts/export_subject_alias_candidates.py            # 生成 + 打印 TOP 表
    python scripts/export_subject_alias_candidates.py --limit 60
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from services.major_coverage import (  # noqa: E402
    _WS_RE, _lookup, _norm, coverage_state, decode_subjects, is_public_subject,
    professional_subject, subject_supply,
)


def _has_name_char(ps: str) -> bool:
    """纯符号/纯数字的科目名（如 "-"）不值得配别名，配上就是伪映射。"""
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", ps or ""))


def _is_public_pool(subj: str) -> bool:
    """候选右侧不许是公共课语料池：政治/数学/英语 人人必考，映射过去覆盖率会虚高。"""
    return is_public_subject(subj) or subj.replace(" ", "").startswith("公共课")

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "data", "subject_alias_candidates.json")

#: 名称尾部噪声词：只影响字面重合度，不影响学科身份
_SUFFIX_NOISE = ("基础", "技术", "科学", "综合", "概论", "导论", "论", "学")


def norm(s) -> str:
    return _WS_RE.sub("", str(s or ""))


def stem(s: str) -> str:
    out = s
    for suf in _SUFFIX_NOISE:
        if out.endswith(suf) and len(out) > len(suf) + 1:
            out = out[: -len(suf)]
            break
    return out


def bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def prior_alias_tables():
    """两份人工底稿（键=专业侧科目名，值=库内 subject 候选）。缺失则跳过。"""
    merged = defaultdict(list)
    for mod in ("probe_major_kb_link", "build_major_kb_link"):
        try:
            m = __import__(f"scripts.{mod}", fromlist=["SUBJECT_ALIAS"])
        except Exception:  # noqa: BLE001
            continue
        for k, v in (getattr(m, "SUBJECT_ALIAS", {}) or {}).items():
            for cand in (v if isinstance(v, (list, tuple)) else [v]):
                if cand not in merged[norm(k)]:
                    merged[norm(k)].append(cand)
    return merged


def candidates_for(ps: str, supply: dict, prior: dict, topn: int = 4) -> list:
    """确定性信号出候选，每个候选带证据标签，供人工判断而非机器判断。"""
    ps_n, ps_stem = norm(ps), stem(norm(ps))
    ps_bi = bigrams(ps_n)
    scored = {}
    for subj in supply:
        signals = []
        if subj == ps_n:
            continue
        # 公共课语料池永不作候选（见 _is_public_pool 注释）
        if _is_public_pool(subj):
            continue
        if subj in ps_n or ps_n in subj:
            signals.append("包含")
        if stem(subj) and (stem(subj) == ps_stem or stem(subj) in ps_stem
                           or ps_stem in stem(subj)):
            signals.append("剥后缀同名")
        jacc = len(bigrams(subj) & ps_bi) / max(len(bigrams(subj) | ps_bi), 1)
        if jacc >= 0.34:
            signals.append(f"字面{jacc:.2f}")
        if subj in prior.get(ps_n, []):
            signals.append("人工底稿")
        if not signals:
            continue
        # 底稿 + 结构信号权重最高，纯字面相似只作参考
        rank = (2 if "人工底稿" in signals else 0) + (1 if "包含" in signals or
                                                     "剥后缀同名" in signals else 0)
        prev = scored.get(subj)
        if prev is None or (rank, jacc) > (prev["rank"], prev["jacc"]):
            scored[subj] = {"rank": rank, "jacc": round(jacc, 3), "signals": signals}
    out = sorted(scored.items(), key=lambda kv: (-kv[1]["rank"], -kv[1]["jacc"]))[:topn]
    return [{"subject": s,
             "documents": supply[s].get("documents", 0),
             "chunks": supply[s].get("chunks", 0),
             "signals": v["signals"]} for s, v in out]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40, help="终端打印前 N 行（JSON 全量）")
    args = ap.parse_args()

    from database import SessionLocal
    from models import KaoyanMajor

    db = SessionLocal()
    try:
        supply = subject_supply(db)
        prior = prior_alias_tables()
        majors = db.query(KaoyanMajor).all()

        gap = Counter()
        codes = defaultdict(set)
        schools = defaultdict(set)
        parsed = 0
        matched = 0
        covered = 0
        for m in majors:
            ps = professional_subject(decode_subjects(m.exam_subjects))
            if not ps:
                continue
            parsed += 1
            hit = _lookup(ps, supply)
            matched += bool(hit)
            covered += (coverage_state(int(hit.get("documents") or 0),
                                       int(hit.get("chunks") or 0)) == "covered")
            if hit:
                continue
            gap[ps] += 1
            if m.code:
                codes[ps].add(str(m.code))
            if m.school_id is not None:
                schools[ps].add(m.school_id)

        def state_of(subject: str) -> str:
            h = supply.get(_norm(subject)) or {}
            return coverage_state(int(h.get("documents") or 0),
                                  int(h.get("chunks") or 0))

        rows = []
        for ps, n in gap.most_common():
            # 纯符号科目名（"-"、"—"）不是学科，给它配候选会把「公共课-政治」当别名塞进去
            if not _has_name_char(ps):
                rows.append({"major_subject": ps, "majors": n,
                             "schools": len(schools[ps]),
                             "codes_observed": sorted(codes[ps])[:8],
                             "candidates": [], "suggested": None,
                             "status": "rejected_not_a_subject"})
                continue
            cands = candidates_for(ps, supply, prior)
            rows.append({
                "major_subject": ps,
                "majors": n,
                "schools": len(schools[ps]),
                "codes_observed": sorted(codes[ps])[:8],   # 原值，绝不生成
                "candidates": cands,
                "suggested": cands[0]["subject"] if cands and cands[0]["signals"] else None,
                "suggested_state": (state_of(cands[0]["subject"])
                                    if cands and cands[0]["signals"] else None),
                "status": "pending",                        # 人工批准前不得启用
            })

        # 上限估算：若全部按 suggested 批准，覆盖能到多少（这是"人工要不要认真过表"的代价感）
        # 两个口径分开报：命中率（进了供给池就算）≠ covered（语料量达标），别混用
        resolved = sum(r["majors"] for r in rows if r["suggested"])
        resolved_covered = sum(r["majors"] for r in rows
                               if r.get("suggested_state") == "covered")
        ceiling_hit = (matched + resolved) / parsed if parsed else 0.0
        ceiling_cover = (covered + resolved_covered) / parsed if parsed else 0.0

        payload = {
            "generated_from": "kaoyan_majors × subject_supply（documents ∪ knowledge_chunks）",
            "note": "候选仅供人工逐条批准；批准前不进 major_coverage._lookup，"
                    "不写 kaoyan_major_kb_link。codes_observed 为库内原值，未做任何补全。"
                    "matched_rate 口径=能命中供给池；coverage_rate 口径=看板用的 covered（语料量达标）。",
            "majors_total": len(majors),
            "majors_with_professional": parsed,
            "matched_now": matched,
            "matched_rate_now": round(matched / parsed, 4) if parsed else 0.0,
            "covered_now": covered,
            "coverage_rate_now": round(covered / parsed, 4) if parsed else 0.0,
            "unmatched_kinds": len(rows),
            "unmatched_majors": sum(r["majors"] for r in rows),
            "match_ceiling_if_all_approved": round(ceiling_hit, 4),
            "coverage_ceiling_if_all_approved": round(ceiling_cover, 4),
            "rows": rows,
        }
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)

        print(f"专业 {len(majors)} 条，可解析专业课 {parsed}；"
              f"现命中率 {matched}（{payload['matched_rate_now']:.1%}）/ "
              f"现 covered {covered}（{payload['coverage_rate_now']:.1%}）")
        print(f"未匹配科目名 {len(rows)} 种 / 覆盖 {payload['unmatched_majors']} 个专业；"
              f"若全部批准 suggested → 命中率上限 {payload['match_ceiling_if_all_approved']:.1%}，"
              f"covered 上限 {payload['coverage_ceiling_if_all_approved']:.1%}")
        print(f"工件已写入 {OUT}\n")
        print(f"{'专业侧科目名':<22}{'专业':>4}{'院校':>5}  候选（证据）")
        for r in rows[:args.limit]:
            cand = "、".join(f"{c['subject']}[{c['documents']}篇/{c['chunks']}块]"
                             f"({'|'.join(c['signals'])})" for c in r["candidates"]) or "（无候选）"
            print(f"{r['major_subject']:<22}{r['majors']:>4}{r['schools']:>5}  {cand}")
        no_cand = [r["major_subject"] for r in rows
                   if not r["candidates"] and r["status"] == "pending"]
        not_subject = [r for r in rows if r["status"] != "pending"]
        print(f"\n完全无候选（需人工命名或确认确实无语料）：{len(no_cand)} 种："
              f"{'、'.join(no_cand[:20])}{' …' if len(no_cand) > 20 else ''}")
        if not_subject:
            print(f"非学科名（不参与别名候选）：{len(not_subject)} 种："
                  f"{'、'.join(repr(r['major_subject']) for r in not_subject[:10])}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
