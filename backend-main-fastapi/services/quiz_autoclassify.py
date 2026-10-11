# -*- coding: utf-8 -*-
"""题目导入自动识别分类（T3）。

背景：/api/quiz/import 与 /import/markdown 要求调用方显式给 subject/
question_type/knowledge_point，缺省时题目直接以 None/default 落库，
导致「未分类」题堆积、刷题分项导航里查不到。

策略（诚实且低成本）：
1. **规则优先**（确定性，不标 ai_generated）：关键词命中判定科目/题型/知识点。
   规则覆盖不到时保持原值，不猜。
2. **LLM 兜底**（可选，use_llm=True 时）：把未判定题目按批交给本地小模型
   （qwen2.5:1.5b，快）输出 JSON 分类，标 ai_generated=True / verified=False。
   LLM 失败静默降级为规则结果。

判定口径与库内真实分布对齐（9 科 / 6 题型，见 quiz_questions 现有值）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 科目关键词（按命中优先级排序：专业核心科在前，公共课在后避免误抢）
# --------------------------------------------------------------------------- #
_SUBJECT_RULES: List[tuple] = [
    ("数字电子技术", [
        "卡诺图", "触发器", "门电路", "与门", "或门", "非门", "与非门", "或非门", "异或",
        "组合逻辑", "时序逻辑", "计数器", "寄存器", "译码器", "编码器", "数据选择器",
        "数制", "二进制", "八进制", "十六进制", "BCD", "布尔", "逻辑函数", "逻辑代数",
        "竞争冒险", "施密特", "多谐振荡", "单稳态", "555", "ADC", "DAC", "三态门", "OC门",
    ]),
    ("模拟电子技术", [
        "放大电路", "静态工作点", "三极管", "晶体管", "共射", "共集", "共基",
        "运放", "运算放大", "差分放大", "场效应", "MOSFET", "JFET", "反馈", "负反馈",
        "滤波", "低通", "高通", "带通", "振荡电路", "整流", "稳压", "二极管",
        "甲类", "乙类", "推挽", "OTL", "OCL", "增益", "频响", "截止频率", "波特图",
    ]),
    ("计算机学科专业基础408", [
        "数据结构", "操作系统", "计算机网络", "计算机组成", "二叉树", "链表", "排序算法",
        "TCP", "UDP", "IP地址", "页表", "虚存", "进程", "线程", "死锁", "指令周期", "流水线",
        "哈夫曼", "图的遍历", "哈弗曼", "cache", "Cache",
    ]),
    ("数学", [
        "极限", "微分", "导数", "积分", "矩阵", "行列式", "特征值", "概率",
        "级数", "收敛", "偏导", "重积分", "线性无关", "秩", "微分方程", "曲率", "泰勒",
        # 英文高频数学记号（OCR/输入混合常见）
        "limit", "sin", "cos", "tan", "ln", "log", "integral", "matrix", "eigenvalue", "∫", "∑",
    ]),
    ("英语", [
        "完形填空", "阅读理解", "翻译下列", "作文", "单词辨析", "语法填空",
    ]),
    ("政治", [
        "马克思", "唯物", "唯心", "辩证法", "剩余价值", "毛泽东", "中国特色社会主义",
        "史纲", "思修", "毛中特", "社会主义核心价值观", "新民主义", "三个代表", "科学发展观",
    ]),
]

# 关键词 → 知识点（仅高频、无歧义的映射；宁缺毋滥）
_KP_RULES: Dict[str, Dict[str, str]] = {
    "数字电子技术": {
        "卡诺图": "卡诺图化简", "触发器": "触发器", "计数器": "计数器", "译码器": "译码器",
        "编码器": "编码器", "寄存器": "寄存器", "组合逻辑": "组合逻辑电路", "时序逻辑": "时序逻辑电路",
        "竞争冒险": "竞争冒险", "逻辑函数": "逻辑函数化简", "ADC": "模数转换", "DAC": "数模转换",
    },
    "模拟电子技术": {
        "静态工作点": "静态工作点", "放大电路": "基本放大电路", "负反馈": "负反馈放大电路",
        "运放": "集成运放应用", "差分放大": "差分放大电路", "场效应": "场效应管放大电路",
        "振荡电路": "正弦波振荡电路", "整流": "直流稳压电源", "滤波": "有源滤波电路",
    },
    "计算机学科专业基础408": {
        "二叉树": "树与二叉树", "链表": "线性表", "排序算法": "排序", "死锁": "死锁",
        "TCP": "传输层", "页表": "虚拟内存", "流水线": "指令流水线",
    },
    "数学": {
        "极限": "极限", "limit": "极限", "导数": "导数与微分", "积分": "积分", "矩阵": "矩阵",
        "概率": "概率", "微分方程": "微分方程", "级数": "无穷级数",
    },
}

_FILL_RE = re.compile(r"_{3,}|＿{3,}")  # 填空下划线（中英文）
# 选项行以 A. B. C. 开头（re.M 让 ^ 匹配每一行，OCR 把选项内联进题干时识别）
_CHOICE_OPT_RE = re.compile(r"^[A-D][\.、．\)]", re.M)


def classify_question_type(content: str, options: Optional[List[str]], default: str = "single") -> str:
    """题型判定：选项结构优先，其次题干关键词；不确定时返回 default。"""
    text = (content or "").strip()
    opts = [o for o in (options or []) if o and str(o).strip()]
    # 有 2 个及以上选项 → 客观题（single 为库内主流客观类型）
    if len(opts) >= 2:
        return "single"
    # OCR 把选项内联进题干（A. xx B. xx 独立成行）→ 选择题。
    # 必须在 judge 之前查：否则「下列正确的是（ ）A.…」会被「正确…是」误判为判断题
    if len(_CHOICE_OPT_RE.findall(text)) >= 2:
        return "single"
    if re.search(r"判断|对错", text):
        return "judge"
    if _FILL_RE.search(text) or "填空" in text:
        return "fill"
    if re.search(r"画[出图]|作图|波形图", text):
        return "draw"
    if re.search(r"计算|化简|求[出值解]|最简|等于|是多少|求该|求其", text):
        return "calc"
    if re.search(r"简述|简答|论述|分析|为什么|说明理由|试说明|叙述", text):
        return "essay"
    return default


def classify_subject(content: str, options: Optional[List[str]] = None) -> Optional[str]:
    """科目判定：关键词计分制（命中数最多的科目胜出；零命中返回 None 不猜）。"""
    text = content or ""
    if options:
        text += "\n" + "\n".join(str(o) for o in options)
    best, best_hits = None, 0
    for subject, kws in _SUBJECT_RULES:
        hits = sum(1 for kw in kws if kw in text)
        if hits > best_hits:
            best, best_hits = subject, hits
    return best if best_hits > 0 else None


def classify_knowledge_point(subject: Optional[str], content: str) -> Optional[str]:
    """知识点判定：仅在高频无歧义关键词映射内命中时返回。

    多个关键词命中时取**最早出现**的——题干先提到的概念通常是考察焦点
    （例：「负反馈能使放大电路…」考察负反馈而非放大电路大类）。
    """
    if not subject:
        return None
    text = content or ""
    best_kw, best_pos = None, -1
    for kw in _KP_RULES.get(subject, {}):
        pos = text.find(kw)
        if pos != -1 and (best_pos == -1 or pos < best_pos):
            best_kw, best_pos = kw, pos
    return _KP_RULES[subject][best_kw] if best_kw else None


def classify_rules(question: Dict[str, Any]) -> Dict[str, Any]:
    """规则分类入口：补全缺失字段，返回 {字段: 填充值}（只含被补的字段）。"""
    filled: Dict[str, Any] = {}
    content = question.get("content") or ""
    options = question.get("options")
    if not question.get("subject"):
        subj = classify_subject(content, options)
        if subj:
            filled["subject"] = subj
    if not question.get("question_type") or question.get("question_type") in ("", "single", None):
        qtype = classify_question_type(content, options, default=question.get("question_type") or "single")
        if qtype != question.get("question_type"):
            filled["question_type"] = qtype
    if not question.get("knowledge_point"):
        kp = classify_knowledge_point(filled.get("subject") or question.get("subject"), content)
        if kp:
            filled["knowledge_point"] = kp
    return filled


# --------------------------------------------------------------------------- #
# LLM 兜底（批量）：规则未判出 subject 的题交给本地小模型
# --------------------------------------------------------------------------- #
_LLM_PROMPT = """你是考研题库的分类器。给下面每道题判定科目与题型。
科目只能从这些里选：数字电子技术/模拟电子技术/计算机学科专业基础408/数学/英语/政治/其他。
题型只能从这些里选：single(选择)/judge(判断)/fill(填空)/calc(计算)/essay(简答论述)/draw(作图)。
只输出 JSON 数组，每项 {{"id": 序号, "subject": "科目", "question_type": "题型"}}，不要其他文字。

题目：
{items}
"""


_LLM_BUDGET_S = 45.0  # 单批 LLM 分类时间预算：超时放弃（规则结果生效），避免拖垮导入接口


def _llm_chat_with_budget(prompt: str) -> str:
    """带时间预算的网关调用：超时抛 TimeoutError，由调用方按「无 LLM 结果」处理。

    不直接给 httpx 传短超时的原因：gateway.chat 无超时参数，且底层
    LOCAL_TIMEOUT=360s（为答疑链设计）。线程放弃后底层请求会自行跑完丢弃，
    不强杀（Python 无法安全终止线程）。
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutTimeout

    from services.model_gateway import get_gateway

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(lambda: get_gateway().chat(
            prompt, subject=None, task="json_gen", prefer="local"))
        try:
            return fut.result(timeout=_LLM_BUDGET_S).get("answer") or ""
        except FutTimeout:
            raise TimeoutError("LLM 分类超时预算用尽")


def classify_batch_llm(questions: List[Dict[str, Any]], db=None) -> Dict[int, Dict[str, str]]:
    """批量 LLM 分类。返回 {题在入参中的下标: {subject, question_type}}；失败返回 {}。"""
    if not questions:
        return {}
    items = "\n".join(
        f"{i+1}. {(q.get('content') or '')[:200]}" for i, q in enumerate(questions)
    )
    try:
        raw = _llm_chat_with_budget(_LLM_PROMPT.format(items=items))
        # 剥离 qwen3 内联思考块（/v1 端点 thinking 泄漏进 content 的已知坑）
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
        if "<think>" in raw:
            raw = raw.split("<think>", 1)[0]
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            return {}
        import json

        arr = json.loads(m.group(0))
        out: Dict[int, Dict[str, str]] = {}
        valid_subjects = {s for s, _ in _SUBJECT_RULES} | {"其他"}
        valid_types = {"single", "judge", "fill", "calc", "essay", "draw"}
        for item in arr if isinstance(arr, list) else []:
            try:
                idx = int(item.get("id")) - 1
                if 0 <= idx < len(questions):
                    subj = item.get("subject")
                    qtype = item.get("question_type")
                    entry = {}
                    if subj in valid_subjects and subj != "其他":
                        entry["subject"] = subj
                    if qtype in valid_types:
                        entry["question_type"] = qtype
                    if entry:
                        out[idx] = entry
            except (TypeError, ValueError):
                continue
        return out
    except Exception as e:  # LLM 兜底失败静默：规则结果已够用
        logger.debug("[autoclassify] LLM 兜底失败: %s", e)
        return {}


def autoclassify(questions: List[Dict[str, Any]], *, use_llm: bool = True, db=None) -> Dict[str, Any]:
    """导入自动分类主入口。

    就地补全每题缺失的 subject/question_type/knowledge_point。
    返回统计：{classified: n, by_rules: n, by_llm: n, ai_generated: n}
    规则判定不标 ai_generated（确定性）；LLM 判定的题标 ai_generated=True/verified=False。
    """
    by_rules = by_llm = 0
    for q in questions:
        filled = classify_rules(q)
        if filled:
            by_rules += 1
            q.update(filled)
    if use_llm:
        # 仅规则后仍缺 subject 的题走 LLM（省时省显存）
        need = [i for i, q in enumerate(questions) if not q.get("subject")]
        if need:
            llm = classify_batch_llm([questions[i] for i in need], db=db)
            for pos, entry in llm.items():
                q = questions[need[pos]]
                # 只补仍缺的字段，不覆盖规则结果——规则是确定性的，
                # LLM 只作兜底（避免模型意见翻转已判定的字段）
                entry = {k: v for k, v in entry.items() if not q.get(k)}
                if not entry:
                    continue
                q.update(entry)
                # LLM 判定的字段属于 AI 生成，需人工/交叉校验后才可信
                q["ai_generated"] = True
                q["verified"] = False
                by_llm += 1
    return {
        "classified": by_rules + by_llm,
        "by_rules": by_rules,
        "by_llm": by_llm,
    }
