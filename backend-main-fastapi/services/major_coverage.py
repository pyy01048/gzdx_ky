# -*- coding: utf-8 -*-
"""择校可靠度：专业初试科目 ↔ 知识库语料覆盖。

口径与 scripts/build_major_kb_link.py 的 L1 完全一致：只按**专业课名与
documents.subject 精确相等**匹配，绝不用数学/英语/政治这类人人必考的公共课
（拿它匹配覆盖率会虚高到 98%，等于没信息量）。这里复制而非 import 那个脚本：
脚本在模块级重配置 stdout 编码，服务进程不该带这个副作用。

不做的事：不猜"专业代码 → 学科"的映射。语料里没有的科目就如实报未覆盖。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Dict, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

_WS_RE = re.compile(r"\s+")
_CODE_RE = re.compile(r"[（(]\s*\d{3,5}\s*[）)]")
_NOISE_RE = re.compile(r"[（(][^）)]*[）)]")

#: 公共课：人人必考，用于匹配等于没匹配
PUBLIC_SUBJECTS = {
    "政治", "英语", "英语一", "英语二", "数学", "数学一", "数学二", "数学三",
    "英语或俄语", "英语或俄语或日语", "日语", "俄语",
}

#: 弃权/未打标学科没有覆盖语义（chunk 打标把垃圾块判成"其他"）
_VACUOUS = {"其他", "其它", "未知", "未分类", "真题综合"}

#: 公共课的**变体写法**（实测库内存在），精确同名集合拦不住：
#:   「自命题数学一」「英语或日语」「英语或日语或自命题德语」。
#: 正则刻意只认"整名都是公共课"，所以「数学分析」「高等数学」这类真自命题
#: 专业课不会被误判——误判会把数学系专业的真实语料从分母里抹掉。
_PUB_MATH_RE = re.compile(r"^(?:自命题)?数学(?:[一二三123]|[（(][一二三][）)])?$")
_LANG = "(?:英语|日语|俄语|德语|外国语)"
_PUB_LANG_RE = re.compile(r"^(?:自命题)?" + _LANG + r"(?:或(?:自命题)?" + _LANG + r")*$")
_PUB_POL_RE = re.compile(r"^(?:自命题)?(?:思想政治理论|思想道德修养与法律基础|"
                         r"毛泽东思想和中国特色社会主义理论体系概论)$")

#: 覆盖分档：只描述"库里有多少篇"，不评价"够不够刷题"
MIN_DOCUMENTS = 5


def _norm(s) -> str:
    return _WS_RE.sub("", str(s or ""))


def decode_subjects(raw) -> list:
    """把 kaoyan_majors.exam_subjects 解析成科目名列表。

    库内格式陷阱：可能是 ' | ' 拼接的 JSON 字符串，也可能已是 JSON 数组。
    """
    if not raw:
        return []
    if isinstance(raw, (list, dict)):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            data = raw
    if isinstance(data, str):
        data = [data]
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        for seg in re.split(r"\s*\|\s*", str(item)):
            seg = _CODE_RE.sub("", seg).strip()   # 剥 (301) 科目代码前缀
            seg = _NOISE_RE.sub("", seg).strip()  # 剥（含..）等括注
            seg = _norm(seg)
            if seg:
                out.append(seg)
    return out


def is_public_subject(name) -> bool:
    """是否公共课（含变体写法）。公共课用于匹配覆盖率等于没匹配。"""
    s = _norm(name)
    if not s:
        return False
    if s in PUBLIC_SUBJECTS:
        return True
    return bool(_PUB_MATH_RE.match(s) or _PUB_LANG_RE.match(s) or _PUB_POL_RE.match(s))


def professional_subject(subjects: list) -> Optional[str]:
    """取第一条非公共课（专业课）；全是公共课时返回 None。"""
    for s in subjects:
        if not is_public_subject(s):
            return s
    return None


def coverage_state(documents: int, chunks: int) -> str:
    """covered / thin / unindexed / uncovered。

    unindexed 是实测出来的真实状态：「数模电」有 186 篇文档但库里 0 个可检索块
    （文档归档了、没切块入库），拿它当"覆盖"会在答疑时落空。
    """
    if documents >= MIN_DOCUMENTS:
        return "covered" if chunks > 0 else "unindexed"
    if documents > 0:
        return "thin"
    return "uncovered"


def _lookup(ps: str, supply: Dict[str, dict]) -> dict:
    """精确匹配优先；其次剥掉大纲里的"能力"后缀。

    唯一需要的归一：统考大纲叫「199 管理类联考综合能力」，本库学科名沿用
    taxonomy 的「管理类联考综合」。除此之外不做模糊匹配——名称对不上就报
    未覆盖，宁可少报也不虚报覆盖。
    """
    hit = supply.get(_norm(ps))
    if hit is None and ps.endswith("能力"):
        hit = supply.get(ps[:-2])
    return hit or {}


def subject_supply(db: Session) -> Dict[str, dict]:
    """供给侧索引：归一学科名 → {documents, chunks, avg_confidence}。"""
    from models import Document, KnowledgeChunk

    supply: Dict[str, dict] = {}
    for subj, n in (db.query(Document.subject, func.count(Document.id))
                      .filter(Document.subject.isnot(None))
                      .group_by(Document.subject).all()):
        k = _norm(subj)
        if not k or k in _VACUOUS:
            continue
        supply.setdefault(k, {"documents": 0, "chunks": 0, "_conf": 0.0})
        supply[k]["documents"] += int(n or 0)

    for subj, n, avg in (db.query(KnowledgeChunk.subject, func.count(KnowledgeChunk.id),
                                  func.avg(KnowledgeChunk.classify_confidence))
                           .filter(KnowledgeChunk.subject.isnot(None))
                           .group_by(KnowledgeChunk.subject).all()):
        k = _norm(subj)
        if not k or k in _VACUOUS:
            continue
        e = supply.setdefault(k, {"documents": 0, "chunks": 0, "_conf": 0.0})
        e["chunks"] += int(n or 0)
        e["_conf"] += float(avg or 0.0) * int(n or 0)

    for k, e in list(supply.items()):
        e["avg_confidence"] = (round(e.pop("_conf") / e["chunks"], 4)
                               if e["chunks"] else None)
    return supply


def coverage_for(raw_exam_subjects, supply: Dict[str, dict]) -> dict:
    """单个专业的语料覆盖徽标数据（无覆盖时也返回明确状态，前端不猜）。"""
    ps = professional_subject(decode_subjects(raw_exam_subjects))
    if not ps:
        return {"subject": None, "state": "public_only", "documents": 0, "chunks": 0}
    hit = _lookup(ps, supply)
    documents = int(hit.get("documents") or 0)
    chunks = int(hit.get("chunks") or 0)
    return {
        "subject": ps,
        "state": coverage_state(documents, chunks),
        "documents": documents,
        "chunks": chunks,
        "avg_confidence": hit.get("avg_confidence"),
    }


def school_coverage(db: Session, supply: Dict[str, dict], school_ids) -> Dict[int, Counter]:
    """按院校聚合专业覆盖计数：school_id → Counter(majors/covered/thin/unindexed/uncovered)。

    majors 只数"有专业课"的专业（只考公共课的不计入分母，否则覆盖率被稀释）。
    """
    from models import KaoyanMajor

    ids = [int(i) for i in school_ids if i is not None]
    if not ids:
        return {}
    out: Dict[int, Counter] = {}
    rows = (db.query(KaoyanMajor.school_id, KaoyanMajor.exam_subjects)
              .filter(KaoyanMajor.school_id.in_(ids)).all())
    for sid, raw in rows:
        c = out.setdefault(int(sid), Counter())
        ps = professional_subject(decode_subjects(raw))
        if not ps:
            continue
        c["majors"] += 1
        hit = _lookup(ps, supply)
        c[coverage_state(int(hit.get("documents") or 0), int(hit.get("chunks") or 0))] += 1
    return out


def school_rollup(db: Session, supply: Dict[str, dict]) -> Dict[str, dict]:
    """全量院校覆盖汇总：school_id(str) → {majors, covered}，供列表页徽标一次拉取。"""
    from models import KaoyanMajor

    ids = [r[0] for r in db.query(KaoyanMajor.school_id).distinct().all()]
    return {
        str(sid): {"majors": int(c.get("majors", 0)), "covered": int(c.get("covered", 0))}
        for sid, c in school_coverage(db, supply, ids).items()
    }


def coverage_summary(db: Session, supply: Dict[str, dict]) -> dict:
    """全库专业 → 语料覆盖率，外加"考它但库里没有"的供给缺口 TOP。"""
    from models import KaoyanMajor

    total = with_prof = covered = thin = unindexed = 0
    gaps: Counter = Counter()
    for raw, in db.query(KaoyanMajor.exam_subjects).all():
        total += 1
        ps = professional_subject(decode_subjects(raw))
        if not ps:
            continue
        with_prof += 1
        hit = _lookup(ps, supply)
        n = int(hit.get("documents") or 0)
        st = coverage_state(n, int(hit.get("chunks") or 0))
        if st == "covered":
            covered += 1
        elif st == "thin":
            thin += 1
        elif st == "unindexed":
            unindexed += 1
        else:
            gaps[ps] += 1
    return {
        "majors_total": total,
        "majors_with_professional": with_prof,
        "majors_covered": covered,
        "majors_thin": thin,
        "majors_unindexed": unindexed,
        "majors_uncovered": with_prof - covered - thin - unindexed,
        "coverage_rate": round(covered / with_prof, 4) if with_prof else 0.0,
        "corpus_subjects": len(supply),
        "min_documents": MIN_DOCUMENTS,
        "supply_gaps": [{"subject": s, "majors": n} for s, n in gaps.most_common(20)],
    }
