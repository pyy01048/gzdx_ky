# -*- coding: utf-8 -*-
"""OCR 版面切题：把含坐标的 OCR 结果按版面切分为独立题目。

借鉴 chenguanyou/CharacterRecognition 的"含位置信息版 OCR"思想：
对 OCRResult.blocks（text + box 坐标）按行/块聚合，
识别题号模式（`1.` / `（1）` / `一、` / `第1题`）切分题目与选项，
产出结构化字段 stem / options / type。

纯新增模块，不改动 ocr_router.py / ocr_service.py（红线：外科手术式改动）。
输出协议：
    [
      {
        "qno": 1, "type": "choice|fill|calc|judge|unknown",
        "stem": "题干文本", "options": ["A. ...", ...],
        "blocks": [ {"text":..., "box":[...]}, ... ],
        "page": 0
      }, ...
    ]
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 题号模式：数字题号 / （1） / 第1题
QNO_PATTERNS = [
    re.compile(r"^[（(]?\s*(\d{1,3})\s*[）)、.．]\s*"),          # 1. / 1、 / （1）
    re.compile(r"^第\s*(\d{1,3})\s*题\s*"),                      # 第1题
]

# 大题标题模式：一、选择题 / （一）填空题 等（作为 section 标记，不单独成题）
SECTION_PATTERNS = [
    re.compile(r"^[（(]?\s*([一二三四五六七八九十]{1,3})\s*[）)、.．]\s*"
               r"(选择题|单项选择|多项选择|不定项|填空题|判断题|计算题|简答题|解答题|"
               r"名词解释|综合题|问答题|分析题|证明题|应用题)"),
    re.compile(r"^[（(]?\s*([一二三四五六七八九十]{1,3})\s*[）)、.．]\s*.*(每题|共\d+分|每小题)"),
]

# 题型模式（含关键词且通常出现在题干首部）
TYPE_PATTERNS: List[tuple] = [
    (r"选择题|单项选择|多项选择|不定项|以下.*(正确|错误)|下列.*(正确|错误)", "choice"),
    (r"填空题|填空|补全", "fill"),
    (r"判断题|判断正误|正确打|错误打", "judge"),
    (r"计算题|求.*值|求解|化简|证明题|推导|计算下列|试求", "calc"),
]

# 选项前缀：A. / A、 / A） / (A) 等
OPT_PREFIX = re.compile(r"^[（(]?\s*([A-Ha-h])\s*[）)、.．:：]\s*")


def _box_top(box: Any) -> float:
    """取 block 顶部 y 坐标（box 为 4 点或 [x,y,w,h]）。"""
    if not box:
        return 0.0
    try:
        if len(box) >= 2 and isinstance(box[0], (int, float)):
            if len(box) >= 4:
                return float(box[1])          # [x, y, w, h]
            return float(box[1])              # [x, y]
        ys = [float(p[1]) for p in box if isinstance(p, (list, tuple)) and len(p) >= 2]
        return min(ys) if ys else 0.0
    except Exception:
        return 0.0


def _box_left(box: Any) -> float:
    """取 block 左 x 坐标。"""
    if not box:
        return 0.0
    try:
        if len(box) >= 2 and isinstance(box[0], (int, float)):
            return float(box[0])              # [x, y] 或 [x, y, w, h]
        xs = [float(p[0]) for p in box if isinstance(p, (list, tuple)) and len(p) >= 2]
        return min(xs) if xs else 0.0
    except Exception:
        return 0.0


def _classify_type(stem: str) -> str:
    for pat, t in TYPE_PATTERNS:
        if re.search(pat, stem):
            return t
    return "unknown"


def _match_qno(text: str) -> Optional[int]:
    """返回题号（1-based），非题号行返回 None。"""
    s = text.strip()
    for pat in QNO_PATTERNS:
        m = pat.match(s)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                cn = m.group(1)
                digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
                return digits.get(cn, 0)
    return None


def cut_questions_from_blocks(
    blocks: List[Dict[str, Any]],
    page: int = 0,
    min_qno: int = 1,
) -> List[Dict[str, Any]]:
    """核心切题：输入 [{text, score, box}]，输出题目列表。

    策略：
    1) 按 top(y) 排序（同 y 按 left 排序），还原阅读顺序；
    2) 命中题号模式的块作为新题目起点；
    3) 同题内 `A.` 前缀块归入 options；
    4) 聚合文本，识别题型，产出 stem/options。
    """
    if not blocks:
        return []

    # 排序：按 top 分桶（行高近似），同桶按 left
    def _row_key(b: Dict[str, Any]) -> tuple:
        top = _box_top(b.get("box"))
        left = _box_left(b.get("box"))
        return (round(top / 20.0), left)

    ordered = sorted(blocks, key=_row_key)

    questions: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None

    def _flush(cur_question: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        section = cur_question.get("section") or ""
        stem_blocks = cur_question.get("stem_blocks", [])
        opts = cur_question.get("option_blocks", [])
        # 纯 section 标记（尚未有题号）不产出题目
        if not cur_question.get("qno") and not stem_blocks:
            return None
        stem = " ".join(stem_blocks)
        if section:
            stem = f"{section}\n{stem}"
        q = {
            "qno": cur_question["qno"],
            "type": _classify_type(section + stem),
            "stem": stem,
            "options": opts,
            "blocks": cur_question.get("raw_blocks", []),
            "page": page,
        }
        return q

    for b in ordered:
        text = (b.get("text") or "").strip()
        if not text:
            continue

        # 大题标题行：flush 当前题，标记 section，不单独成题
        section_match = None
        for sp in SECTION_PATTERNS:
            if sp.match(text):
                section_match = text
                break
        if section_match:
            if cur is not None:
                flushed = _flush(cur)
                if flushed is not None:
                    questions.append(flushed)
            cur = {
                "qno": 0,
                "section": section_match,
                "stem_blocks": [],
                "option_blocks": [],
                "raw_blocks": [],
            }
            continue

        qno = _match_qno(text)
        if qno is not None and qno >= min_qno:
            inherited_section = ""
            if cur is not None:
                flushed = _flush(cur)
                if flushed is not None:
                    questions.append(flushed)
                inherited_section = cur.get("section") or ""
            cur = {
                "qno": qno,
                "section": inherited_section,
                "stem_blocks": [],
                "option_blocks": [],
                "raw_blocks": [],
            }
        if cur is None:
            continue  # 题号前的页眉/封面文本丢弃

        # 选项行：以 A. B. C. D. 开头（且不是新题号）
        m = OPT_PREFIX.match(text)
        if m and not (_match_qno(text) is not None and text[0] not in "ABCDEFGH"):
            opt_letter = m.group(1).upper()
            cur["option_blocks"].append(f"{opt_letter}. {text[m.end():].strip()}")
        else:
            cur["stem_blocks"].append(text)
        cur["raw_blocks"].append({"text": text, "box": b.get("box"), "score": b.get("score")})

    if cur is not None:
        flushed = _flush(cur)
        if flushed is not None:
            questions.append(flushed)

    # 重新编号（防止 OCR 起始题号非 1）
    for i, q in enumerate(questions, start=1):
        q["qno"] = i
    return questions


def cut_questions(result: Any, min_qno: int = 1) -> List[Dict[str, Any]]:
    """OCRResult 或 dict 的便捷入口。"""
    if hasattr(result, "blocks"):
        blocks = [b.to_dict() if hasattr(b, "to_dict") else b for b in result.blocks]
        return cut_questions_from_blocks(blocks, page=0, min_qno=min_qno)
    if isinstance(result, dict):
        return cut_questions_from_blocks(result.get("blocks") or [], page=result.get("page", 0), min_qno=min_qno)
    return []


if __name__ == "__main__":
    # 自测样例（无坐标模拟）
    import json
    sample = [
        {"text": "一、选择题（每题2分）", "box": [[0, 0], [200, 0], [200, 30], [0, 30]]},
        {"text": "1. 数字电路中，TTL与非门多余的输入端应如何处理？", "box": [[0, 40], [300, 40], [300, 70], [0, 70]]},
        {"text": "A. 悬空", "box": [[0, 75], [80, 75], [80, 95], [0, 95]]},
        {"text": "B. 接高电平", "box": [[100, 75], [180, 75], [180, 95], [100, 95]]},
        {"text": "C. 接低电平", "box": [[0, 100], [80, 100], [80, 120], [0, 120]]},
        {"text": "D. 并联使用", "box": [[100, 100], [180, 100], [180, 120], [100, 120]]},
        {"text": "2. 求函数 F=A'B+AB' 的最简与或式。", "box": [[0, 140], [300, 140], [300, 170], [0, 170]]},
    ]
    qs = cut_questions_from_blocks(sample, page=0)
    print(json.dumps(qs, ensure_ascii=False, indent=2))
