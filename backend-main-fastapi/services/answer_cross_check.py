# -*- coding: utf-8 -*-
"""
A6 答案交叉校验（services/answer_cross_check.py）
=================================================
对同一题目多来源答案（题库 answer / 真题 2-gram 检索 / LLM 生成）比对一致性，
写入 answer_candidates 并标注置信度；来源冲突标 quiz_questions.confidence='verify'。

answer_candidates 四态来源：bank | extracted | llm | user_confirmed
confidence 0.0~1.0；used_for_grading 仅高置信度参与自动判分与正确率统计。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from services.answer_rules import ANSWER_RULES  # E4 答题规则注入

try:
    from services.llm_output import looks_like_chain_of_thought  # 复用思维链检测
except Exception:  # pragma: no cover
    def looks_like_chain_of_thought(_t):  # type: ignore
        return False

SOURCE_BANK = "bank"
SOURCE_EXTRACTED = "extracted"
SOURCE_LLM = "llm"
SOURCE_USER = "user_confirmed"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_answer(s: Any) -> str:
    """答案归一化：去空白、转小写、去标点与括号内注。"""
    if s is None:
        return ""
    t = re.sub(r"\s+", "", str(s))
    t = re.sub(r"[（(][^）)]*[)）]", "", t)
    t = re.sub(r"[，,。.;；:：!?？！、\"'\"'《》<>【】\[\]]", "", t)
    return t.lower()


def _normalize_option_letter(s: str) -> str:
    t = _norm_answer(s)
    m = re.match(r"^([abcdABCD])$", t)
    if m:
        return m.group(1).upper()
    return t


# 从长文本答案中提取选择题选项字母（如 "C."、"（A）"、"选项B"、"答案：D"）
_OPT_LETTER_RE = [
    re.compile(r"答案[是为:：]*\s*([A-Da-d])"),
    re.compile(r"选项\s*[：:.]?\s*([A-Da-d])"),
    re.compile(r"[（(【\[]\s*([A-Da-d])\s*[）)】\]]"),
    re.compile(r"(?:^|[\s，,。;；、])([A-Da-d])\s*[.、:：)]"),
    re.compile(r"^\s*([A-Da-d])\s*[.、:：]"),
    re.compile(r"(?:^|\s)([A-Da-d])\s+(?:正确|对|是)"),
]


def _extract_option_letter(s: str) -> str:
    """从答案文本提取选项字母；纯字母直接返回，长文本尝试常见标记。"""
    if not s:
        return ""
    raw = str(s)
    m = re.match(r"^\s*([A-Da-d])\s*$", raw)
    if m:
        return m.group(1).upper()
    for pat in _OPT_LETTER_RE:
        mm = pat.search(raw)
        if mm:
            return mm.group(1).upper()
    return ""


def _consistency_score(a: str, b: str) -> float:
    """两来源答案一致性：1.0 相同；0.7 选项字母一致（含从长文本提取）；0.5 互相包含；0.0 冲突。"""
    na, nb = _norm_answer(a), _norm_answer(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    la = _extract_option_letter(a)
    lb = _extract_option_letter(b)
    if la and lb and la == lb:
        return 0.7
    if na in nb or nb in na:
        return 0.5
    # 列表式多值答案（LLM 常用 'A. xxx B. xxx' 自编号）：剥离字母标记后
    # 若一方内容包含另一方，视为内容一致（0.5），避免自编号造成假冲突。
    sa_all = _norm_answer(_strip_letter_prefixes_all(a))
    sb_all = _norm_answer(_strip_letter_prefixes_all(b))
    if sa_all and sb_all and (sa_all in sb_all or sb_all in sa_all):
        return 0.5
    return 0.0


# --------------------------------------------------------------------------- #
# 候选来源收集
# --------------------------------------------------------------------------- #
def _source_from_bank(db, question_id: int) -> Optional[Dict[str, Any]]:
    conn = db.connection().connection
    row = conn.execute(
        "SELECT id, answer, analysis FROM quiz_questions WHERE id = ?", (question_id,)
    ).fetchone()
    if not row or not (row[1] or "").strip():
        return None
    return {"source": SOURCE_BANK, "answer": row[1], "explanation": row[2] or "", "confidence": 0.9}


def _source_from_exam_engine(db, question_id: int, query: str) -> Optional[Dict[str, Any]]:
    """第二证据源：真题 2-gram 检索（仅公共课索引覆盖）。

    严格证据规则（本次优化，根除跨学科误命中）：
    - 只信 **external_id 精确命中** 的真题（0.85）；
    - 不再做"电子题回落不带 subject 取 top1"的宽松兜底——实测它会抽到
      政治/英语等跨学科无关题，375 个 bank,extracted 冲突全部因此误标；
    - subject 中文名先映射为索引科目（数学→math2 等），公共课检索按科目过滤，
      电子类（非公共课）无索引覆盖 → 直接返回 None（宁缺毋滥）。
    """
    try:
        from services.exam_engine import SUBJECT_ALIAS, get_exam_index

        idx = get_exam_index()
        conn = db.connection().connection
        row = conn.execute(
            "SELECT year, external_id, subject FROM quiz_questions WHERE id = ?", (question_id,)
        ).fetchone()
        year = row[0] if row else None
        ext = row[1] if row else None
        subj = row[2] if row else None
        # 非公共课（电子类/专业课/真题综合）索引无覆盖：不再回落，直接放弃证据
        idx_subj = SUBJECT_ALIAS.get(subj or "", None)
        if idx_subj is None:
            return None
        hits = idx.retrieve(query or "", k=5, subject=idx_subj)
        # 只信 external_id 精确命中；无 external_id 的数据（当前全部）→ 不产出证据
        for doc_id, _s, _h in hits:
            q = idx._q(doc_id)
            if ext and str(q.get("external_id") or "") == str(ext):
                ans = q.get("answer") or ""
                if ans.strip():
                    return {
                        "source": SOURCE_EXTRACTED,
                        "answer": ans,
                        "explanation": q.get("analysis") or "",
                        "confidence": 0.85,
                        "doc_id": doc_id,
                        "year": q.get("year"),
                    }
    except Exception:
        return None
    return None


_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

#: AI 回填失败时的兜底话术（不是真实答案，不能当证据/基准）
_BANK_FAILURE_PHRASES = (
    "错误", "题目错误", "题目信息错误", "题目描述存在矛盾", "题目信息不完整",
    "题目存在错误", "题面存在错误", "题面信息错误",
    "无法判断", "无法确定", "无法作答", "信息不足", "资料缺失", "题干缺失",
)


def _strip_letter_prefix(text: str) -> str:
    """剥离答案文本前导的选项字母标记（如 'D. 条件不足' → '条件不足'）。

    用于 unable 豁免判断：LLM 常输出 'X. 条件不足' / 'A. 无法判断' 这类
    带自编号前缀的保守话术，前缀字母并非真实选项，不应让豁免条件失效。
    """
    if not text:
        return text
    return re.sub(
        r"^\s*[A-Da-d]\s*[.、:：)）]\s*", "", str(text)
    )


def _strip_letter_prefixes_all(text: str) -> str:
    """剥离文本中所有前导选项字母标记（LLM 列表式输出如 'A. 真值表 B. 逻辑表达式'）。

    用于一致性包含匹配：LLM 常把多值答案整理成 'A. xxx B. xxx' 列表，
    字母只是自编号，不应阻断与 bank 纯文本答案的包含关系判定。
    """
    if not text:
        return text
    return re.sub(
        r"(?:^|[\s，,。;；、])[A-Ea-e]\s*[.、:：)）]", "", str(text)
    )


def _clean_llm_answer(ans: str) -> Optional[str]:
    """清洗 LLM 候选：剥内联 <think> 块 → 仍像思维链 → 返回 None。

    ModelGateway.chat 返回的是模型原始 content，Qwen3 系可能内联
    <think>...</think> 思维链（实测 134 条 llm 候选全部污染，且部分无闭合标签）。
    """
    if not ans:
        return None
    t = _THINK_BLOCK_RE.sub("", ans).strip()
    if not t:
        return None
    if "<think" in t.lower():          # 未闭合的 <think> 块同样视为污染
        return None
    if looks_like_chain_of_thought(t):
        return None
    return t


def _looks_like_failed_bank(answer: str) -> bool:
    """判断 bank 答案是否是回填失败的兜底话术（不可作为基准证据）。"""
    if not answer:
        return True
    t = re.sub(r"\s+", "", answer)
    return any(p in t for p in _BANK_FAILURE_PHRASES)


# LLM 无法作答话术：残缺/乱码/缺图题面的保守防御，不构成对具体答案的质疑
_UNABLE_RE = re.compile(
    r"条件不足|信息不足|无法判断|无法确定|无法作答|无法给出|无法推断|无法解答|无法识别|"
    r"题干不完整|题面不完整|题目不完整|缺少图|无图示|缺图|乱码|残缺|不完整|"
    r"需补充|需要补充|无法准确|不能确定"
)


def _looks_like_unable(text: str) -> bool:
    """识别 LLM 无法作答话术（条件不足/缺图/乱码等）。"""
    return bool(text) and bool(_UNABLE_RE.search(str(text)))


def _source_from_llm(db, question_id: int, query: str, answer_type: str) -> Optional[Dict[str, Any]]:
    """LLM 生成候选答案（llm 来源），走 ModelGateway.chat。"""
    try:
        from services.model_gateway import get_gateway

        prompt = (
            "请作答下面这道考研题目，严格遵循输出格式：\n"
            "1. 选择题：第一行只输出选项字母（A/B/C/D），可附带选项内容，不要输出推导过程。\n"
            "2. 填空/计算/简答：第一行输出最终结论（数值/表达式/名词），随后最多用一两行给出简要推导。\n"
            "3. 若题面文字残缺、乱码或缺图导致无法准确作答：先基于已有信息给出最可能的结论并标注（存疑），"
            "只有完全无法推断时才写'条件不足'。\n"
            "4. 严禁输出任何思考过程、内心独白或解释性废话。\n"
            "题目：\n" + (query or "")[:1500]
        )
        res = get_gateway().chat(
            question=prompt,
            subject=None,
            task="题目分析",
            context=None,
            system_prompt="你是考研辅导老师，作答准确简洁。\n" + ANSWER_RULES,
            prefer=None,
            db=db,
        )
        ans = _clean_llm_answer(res.get("answer") or "")
        if not ans:
            return None
        return {"source": SOURCE_LLM, "answer": ans, "explanation": "", "confidence": 0.5}
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def cross_check_question(
    db,
    question_id: int,
    *,
    use_llm: bool = True,
    query: Optional[str] = None,
    prefer: Optional[str] = None,  # 路由透传（保留参数位，当前按默认策略校验）
) -> Dict[str, Any]:
    """对单题执行交叉校验，写 answer_candidates 并标注置信度。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    from services.db_retry import exec_retry
    conn = db.connection().connection
    row = conn.execute(
        "SELECT id, content, answer, answer_type, year, external_id FROM quiz_questions WHERE id = ?",
        (question_id,),
    ).fetchone()
    if not row:
        return {"question_id": question_id, "error": "question not found"}
    content = row[1] or ""
    bank_answer = row[2] or ""
    answer_type = row[3] or "objective"
    ext = row[5]

    sources: List[Dict[str, Any]] = []
    bank_src = _source_from_bank(db, question_id)
    if bank_src and _looks_like_failed_bank(bank_src["answer"]):
        bank_src = None  # 回填失败话术不能当基准证据
    if bank_src:
        sources.append(bank_src)

    ex_src = _source_from_exam_engine(db, question_id, query or content)
    if ex_src:
        sources.append(ex_src)

    # AI 未核验答案的交叉校验语义：bank 本身是 AI 生成的，单靠它不算证据。
    # 用 LLM 独立重做一遍作第二证据（两次独立采样一致 → 可信）；
    # check_batch 对此类题显式开 use_llm。
    bank_is_ai = False
    try:
        row_ai = conn.execute(
            "SELECT ai_generated FROM quiz_questions WHERE id = ?", (question_id,)
        ).fetchone()
        bank_is_ai = bool(row_ai and row_ai[0])
    except Exception:
        pass
    if use_llm and (len(sources) <= 1 or (bank_is_ai and len(sources) < 2)):
        llm_src = _source_from_llm(db, question_id, query or content, answer_type)
        if llm_src:
            sources.append(llm_src)

    # 失效旧快照清理：bank 当前无效（空/失败话术）→ 删旧 bank 候选；
    # llm 当前清洗失败（含 think 污染等）→ 删旧 llm 候选。
    if not bank_src:
        conn.execute(
            "DELETE FROM answer_candidates WHERE question_id = ? AND source = ?",
            (question_id, SOURCE_BANK),
        )
    if not any(s["source"] == SOURCE_LLM for s in sources):
        conn.execute(
            "DELETE FROM answer_candidates WHERE question_id = ? AND source = ?",
            (question_id, SOURCE_LLM),
        )

    if len(sources) <= 1:
        # 单源不足以校验：若此前被误标为 verify（假冲突），恢复为未校验
        old_conf = conn.execute(
            "SELECT confidence FROM quiz_questions WHERE id = ?", (question_id,)
        ).fetchone()
        if old_conf and old_conf[0] == "verify":
            exec_retry(
                conn,
                "UPDATE quiz_questions SET confidence = NULL WHERE id = ?",
                (question_id,),
            )
            db.commit()
        return {
            "question_id": question_id,
            "checked": False,
            "reason": "insufficient_sources",
            "candidates": len(sources),
            "confidence": "medium",
        }

    # 两两比对，取最小一致性（最坏情况）
    # 豁免规则：LLM 对残缺/乱码/缺图题面保守返回"条件不足"类话术且无具体答案时，
    # 不构成对具体答案（bank/extracted）的质疑，跳过该冲突对；
    # 若 LLM 已给出可提取的选项字母或具体答案，即使附带"存疑"字样也不豁免。
    best = sources[0]
    min_consistency = 1.0
    conflicts = []
    for i in range(len(sources)):
        for j in range(i + 1, len(sources)):
            sa, sb = sources[i], sources[j]
            if _looks_like_unable(sa["answer"]) and _looks_like_unable(sb["answer"]):
                # 双源均无法作答：题面问题，不比对
                continue
            if (
                sa["source"] == SOURCE_LLM
                and _looks_like_unable(sa["answer"])
                and not _extract_option_letter(_strip_letter_prefix(sa["answer"]))
            ) or (
                sb["source"] == SOURCE_LLM
                and _looks_like_unable(sb["answer"])
                and not _extract_option_letter(_strip_letter_prefix(sb["answer"]))
            ):
                continue
            c = _consistency_score(sa["answer"], sb["answer"])
            min_consistency = min(min_consistency, c)
            if c < 0.5:
                conflicts.append((sa["source"], sb["source"]))

    final_conf = max(0.05, min(0.95, min_consistency * 0.9))
    final = {
        "question_id": question_id,
        "checked": True,
        "candidates": len(sources),
        "best_source": best["source"],
        "consistency": round(min_consistency, 3),
        "conflicts": conflicts,
        "confidence": final_conf,
        "answer_type": answer_type,
    }

    # 写 answer_candidates（同 question_id+source 幂等更新）

    for s in sources:
        exists = conn.execute(
            "SELECT id FROM answer_candidates WHERE question_id = ? AND source = ?",
            (question_id, s["source"]),
        ).fetchone()
        if exists:
            exec_retry(
                conn,
                """
                UPDATE answer_candidates SET answer = ?, explanation = ?, confidence = ?,
                used_for_grading = ?, verified_by = ?, verified_at = ?
                WHERE id = ?
                """,
                (s["answer"], s["explanation"] or "", s["confidence"],
                 1 if s["confidence"] >= 0.7 else 0,
                 "cross_check", _now_str(), exists[0]),
            )
        else:
            exec_retry(
                conn,
                """
                INSERT INTO answer_candidates
                (question_id, answer, explanation, confidence, source, used_for_grading, verified_by, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (question_id, s["answer"], s["explanation"] or "", s["confidence"],
                 s["source"], 1 if s["confidence"] >= 0.7 else 0, "cross_check", _now_str()),
            )

    # 来源冲突 → quiz_questions.confidence='verify'
    new_conf = "verify" if conflicts else ("high" if min_consistency >= 0.7 else "medium")
    exec_retry(
        conn,
        "UPDATE quiz_questions SET confidence = ? WHERE id = ?",
        (new_conf, question_id),
    )
    final["confidence_label"] = new_conf

    # V13 改造：冲突不再只放返回值，持久化进人工复核队列（幂等，open 唯一）。
    # 具体结案（采纳/驳回 + 候选降权）走 /api/conflicts，由人拍板。
    if conflicts:
        try:
            from services.confidence_service import register_conflict
            by_src = {s["source"]: s for s in sources}
            for sa, sb in conflicts[:4]:  # 最多登记前 4 对，避免队列爆炸
                register_conflict(
                    db, question_id,
                    answer_a=by_src.get(sa, {}).get("answer", ""),
                    answer_b=by_src.get(sb, {}).get("answer", ""),
                    source_a=sa, source_b=sb,
                    confidence_a=by_src.get(sa, {}).get("confidence", 0.0),
                    confidence_b=by_src.get(sb, {}).get("confidence", 0.0),
                    suggested_winner=final.get("best_source"),
                )
        except Exception:  # 队列写入失败不阻断主校验链路
            pass

    db.commit()
    return final


def check_batch(
    db,
    question_ids: List[int],
    *,
    use_llm: bool = True,  # 批量校验默认开 LLM：AI 生成答案必须独立重做交叉验证
    limit: int = 200,
    prefer: Optional[str] = None,  # 路由透传（保留参数位，当前按默认策略校验）
) -> Dict[str, Any]:
    """批量交叉校验。

    V12 性能修复：增量校验 —— 已核验为 high/verify 置信度的题直接跳过
    （保留历史结果，不重复调 LLM），只有未校验/低置信度的题才进入交叉校验。
    单批全量 LLM 串行（50 题 × 60s）是 504 超时的根因，此修复将常态批
    处理耗时从数百秒降到秒级。
    """
    ids = (question_ids or [])[:limit]
    if not ids:
        # 未指定时默认取真正需要重新校验的题：仅无置信度 / 冲突(verify) 两类。
        # medium（已有 bank/extracted 候选、历史已校验过）默认跳过，避免每批
        # 几百题全量 LLM 串行导致 504 —— 需要重跑时可显式传 question_ids。
        from services.module_a_schema import ensure_module_a_schema
        ensure_module_a_schema(db)
        conn = db.connection().connection
        rows = conn.execute(
            "SELECT id FROM quiz_questions "
            "WHERE confidence IS NULL OR confidence = 'verify' "
            "ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        ids = [r[0] for r in rows]

    out = []
    skipped = 0
    for qid in ids:
        # 已核验为 high / verify / medium 的题：跳过，不重跑 LLM
        try:
            from services.module_a_schema import ensure_module_a_schema
            ensure_module_a_schema(db)
            conn = db.connection().connection
            row = conn.execute(
                "SELECT confidence FROM quiz_questions WHERE id = ?", (qid,)
            ).fetchone()
            if row and row[0] in ("high", "verify", "medium"):
                skipped += 1
                continue
        except Exception:
            pass
        out.append(cross_check_question(db, qid, use_llm=use_llm))
    checked = [x for x in out if x.get("checked")]
    return {
        "total": len(ids),
        "checked": len(checked),
        "skipped": skipped,
        "conflicts": sum(1 for x in checked if x.get("conflicts")),
        "details": out,
    }

def stats(db) -> Dict[str, Any]:
    """答案校验统计。"""
    from services.module_a_schema import ensure_module_a_schema

    ensure_module_a_schema(db)
    conn = db.connection().connection
    total_candidates = conn.execute("SELECT COUNT(*) FROM answer_candidates").fetchone()[0]
    by_source = {}
    for src in (SOURCE_BANK, SOURCE_EXTRACTED, SOURCE_LLM, SOURCE_USER):
        n = conn.execute(
            "SELECT COUNT(*) FROM answer_candidates WHERE source = ?", (src,)
        ).fetchone()[0]
        by_source[src] = n
    graded = conn.execute(
        "SELECT COUNT(*) FROM answer_candidates WHERE used_for_grading = 1"
    ).fetchone()[0]
    verify_cnt = conn.execute(
        "SELECT COUNT(*) FROM quiz_questions WHERE confidence = 'verify'"
    ).fetchone()[0]
    return {
        "total_candidates": total_candidates,
        "by_source": by_source,
        "used_for_grading": graded,
        "verify_conflict_questions": verify_cnt,
    }


if __name__ == "__main__":  # pragma: no cover
    print("sources:", SOURCE_BANK, SOURCE_EXTRACTED, SOURCE_LLM, SOURCE_USER)
