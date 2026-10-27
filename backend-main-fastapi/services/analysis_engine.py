# -*- coding: utf-8 -*-
"""
通用题目分析引擎（MathLens 式）
=================================
输入题目（文本 / 图片 OCR）→ 结构化分析（已知条件 / 思路 / 分步推导 / 结论验证）
→ 生成可视化 HTML 讲义（KaTeX 公式渲染）。

复用底座：
- ocr_router.recognize_file   : 图片题目识别（三层 OCR 路由）
- model_gateway.ModelGateway  : 本地模型 + API 灵活路由
"""
from __future__ import annotations
import logging

import json
import os
import re
import time
import uuid
from services.dbapi_compat import wrap_conn
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.timeutil import iso_utc_z

LECTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lectures")

from services.answer_rules import ANSWER_RULES  # noqa: E402  (E4 答题规则注入)

_STRUCT_PROMPT = (
    "你是考研全科辅导老师，擅长数学、数电、模电、英语、政治、408（数据结构/组成原理/操作系统/计算机网络）。"
    "请对用户给出的题目做【结构化分析】，严格按以下 JSON 结构输出（输出时用 ```json 代码块包裹，不要输出任何思考过程或额外文字）：\n"
    + ANSWER_RULES
    + "\n"
    "{\n"
    '  "known_conditions": ["已知条件1", "已知条件2", ...],\n'
    '  "solution_approach": "整体解题思路（2~4句）",\n'
    '  "steps": [{"title": "步骤标题", "content": "本步推导内容，公式用 $...$ 包裹", "conclusion": "本步结论（可空）"}],\n'
    '  "final_answer": "最终答案/结论",\n'
    '  "verification": "结论验证方法或代入检验（可空）",\n'
    '  "knowledge_points": ["涉及知识点1", "知识点2", ...],\n'
    '  "common_mistakes": ["易错点/常见错误1", ...]\n'
    "}\n"
    "要求：推导严谨、分步清晰，公式用 LaTeX 语法（行内 $...$），适合普通学情学生理解。"
)


def _strip_think(text: str) -> str:
    """去除 qwen3/deepseek-r1 等模型的 <think>...</think> 思考链块，并收敛空白。"""
    if not text:
        return text
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中容错提取 JSON。"""
    if not text:
        return None
    # 去掉 ```json ... ``` 围栏
    t = re.sub(r"```(?:json)?\s*", "", text).strip()
    t = re.sub(r"```", "", t).strip()
    # 截取第一个 { 到最后一个 }
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    body = t[start:end + 1]
    try:
        return json.loads(body)
    except Exception as _exc:  # noqa: BLE001
        # 不静默：原先此处裸 pass，异常被无声吞掉，出问题无从排查
        # （项目血泪教训 #1）。保留「不阻塞主流程」语义，仅补留痕。
        logging.getLogger(__name__).warning(
            '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
        )
    # 尝试修复常见问题：尾逗号
    try:
        body_fixed = re.sub(r",\s*([}\]])", r"\1", body)
        return json.loads(body_fixed)
    except Exception:
        return None


def _ensure_struct(data: Dict[str, Any], question: str) -> Dict[str, Any]:
    """补全缺失字段，保证前端渲染安全。"""
    return {
        "question": question,
        "known_conditions": data.get("known_conditions") or [],
        "solution_approach": data.get("solution_approach") or "",
        "steps": data.get("steps") or [],
        "final_answer": data.get("final_answer") or "",
        "verification": data.get("verification") or "",
        "knowledge_points": data.get("knowledge_points") or [],
        "common_mistakes": data.get("common_mistakes") or [],
    }


def analyze_problem(
    question: str,
    subject: Optional[str] = None,
    prefer: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """题目结构化分析入口。"""
    t0 = time.time()
    from services.model_gateway import get_gateway

    gateway = get_gateway()
    result = gateway.chat(
        question=question,
        subject=subject,
        task="题目分析",
        prefer=prefer,
        system_prompt=_STRUCT_PROMPT,
        db=db,
    )
    raw_answer = result.get("answer", "") or ""
    clean_answer = _strip_think(raw_answer)
    parsed = _extract_json(clean_answer)
    if parsed is None:
        # 模型未输出 JSON：降级包装为单步推导
        parsed = {
            "known_conditions": [],
            "solution_approach": "模型未返回结构化结果，以下为原始解答。",
            "steps": [{"title": "解答", "content": clean_answer or raw_answer, "conclusion": ""}],
            "final_answer": "",
            "verification": "",
            "knowledge_points": [],
            "common_mistakes": [],
        }
    struct = _ensure_struct(parsed, question)
    struct["engine"] = result.get("engine", "")
    struct["provider"] = result.get("provider", "")
    struct["model"] = result.get("model", "")
    struct["latency_ms"] = result.get("latency_ms", 0)
    struct["fallback_used"] = result.get("fallback_used", False)
    struct["error"] = result.get("error")
    struct["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
    return struct


def recognize_problem_image(image_path: str, prefer: str = "auto") -> Dict[str, Any]:
    """图片题目识别（三层 OCR 路由）。"""
    from services.ocr_router import recognize_file

    res = recognize_file(image_path, prefer=prefer)
    return {
        "text": res.text,
        "engine": res.engine,
        "backend": res.backend,
        "elapsed": res.elapsed,
        "error": res.error,
    }


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_math(text: str) -> str:
    """保留 $...$ 供 KaTeX 渲染，其余转义。"""
    parts = re.split(r"(\$[^$]+\$)", text)
    out = []
    for p in parts:
        if p.startswith("$") and p.endswith("$") and len(p) > 2:
            out.append(p)  # 保留原样，前端 KaTeX 处理
        else:
            out.append(_escape_html(p))
    return "".join(out)


def build_lecture_html(
    analysis: Dict[str, Any],
    output_path: Optional[str] = None,
) -> str:
    """生成可视化 HTML 讲义（KaTeX 公式渲染 + 分步解答 + 易错点）。"""
    q = _escape_html(analysis.get("question", ""))
    subject = _escape_html(analysis.get("subject", "") or "")
    approach = _render_math(analysis.get("solution_approach", ""))
    final = _render_math(analysis.get("final_answer", ""))
    verify = _render_math(analysis.get("verification", ""))
    engine = analysis.get("engine", "")
    model = analysis.get("model", "")
    provider = analysis.get("provider", "")

    known_html = "\n".join(
        f"<li>{_render_math(k)}</li>" for k in (analysis.get("known_conditions") or [])
    ) or "<li>（无）</li>"

    steps_html = ""
    steps = analysis.get("steps") or []
    for i, st in enumerate(steps, 1):
        title = _render_math(st.get("title", f"步骤 {i}"))
        content = _render_math(st.get("content", ""))
        conclusion = _render_math(st.get("conclusion", ""))
        steps_html += f"""
        <div class="step">
          <div class="step-head"><span class="step-num">{i}</span><h3>{title}</h3></div>
          <div class="step-body">{content}</div>
          {f'<div class="step-concl">结论：{conclusion}</div>' if conclusion else ''}
        </div>"""

    kps = "、".join(_escape_html(x) for x in (analysis.get("knowledge_points") or []))
    mistakes_html = "\n".join(
        f"<li>{_render_math(m)}</li>" for m in (analysis.get("common_mistakes") or [])
    ) or "<li>（无）</li>"

    meta_line = ""
    if engine or model:
        meta_line = f'<div class="meta">分析引擎：{engine} · {_escape_html(provider)} · {_escape_html(model)}</div>'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>题目分析讲义</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}}]}});"></script>
<style>
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; max-width: 860px; margin: 32px auto; padding: 0 20px; color: #1f2937; background: #f8fafc; }}
  h1 {{ font-size: 22px; border-bottom: 3px solid #4f46e5; padding-bottom: 10px; color: #312e81; }}
  .subject-tag {{ display:inline-block; background:#eef2ff; color:#4338ca; padding:2px 10px; border-radius:12px; font-size:13px; }}
  .card {{ background:#fff; border-radius:12px; padding:18px 22px; margin:16px 0; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  .card h2 {{ font-size:16px; color:#4338ca; margin-top:0; }}
  ul {{ margin:6px 0; padding-left:22px; }}
  .approach {{ background:#fffbeb; border-left:4px solid #f59e0b; padding:12px 16px; border-radius:6px; }}
  .step {{ border-left:4px solid #4f46e5; margin:14px 0; padding:6px 14px; background:#f5f7ff; border-radius:6px; }}
  .step-head {{ display:flex; align-items:center; gap:10px; }}
  .step-num {{ background:#4f46e5; color:#fff; width:26px; height:26px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:14px; flex-shrink:0; }}
  .step-body {{ margin-top:6px; line-height:1.8; }}
  .step-concl {{ margin-top:8px; color:#166534; font-weight:600; }}
  .final {{ background:#ecfdf5; border-left:4px solid #10b981; padding:12px 16px; border-radius:6px; }}
  .verify {{ background:#eff6ff; border-left:4px solid #3b82f6; padding:12px 16px; border-radius:6px; }}
  .mistake {{ color:#b91c1c; }}
  .meta {{ color:#6b7280; font-size:12px; margin-top:20px; text-align:right; }}
</style>
</head>
<body>
<h1>题目分析讲义</h1>
{f'<div class="subject-tag">{subject}</div>' if subject else ''}
<div class="card"><h2>📝 题目</h2><div>{q}</div></div>
<div class="card"><h2>已知条件</h2><ul>{known_html}</ul></div>
<div class="card"><h2>解题思路</h2><div class="approach">{approach}</div></div>
<div class="card"><h2>分步推导</h2>{steps_html}</div>
{f'<div class="card final"><h2>最终答案</h2><div>{final}</div></div>' if final else ''}
{f'<div class="card verify"><h2>结论验证</h2><div>{verify}</div></div>' if verify else ''}
{f'<div class="card"><h2>涉及知识点</h2><div>{kps}</div></div>' if kps else ''}
<div class="card"><h2>易错提醒</h2><ul class="mistake">{mistakes_html}</ul></div>
{meta_line}
</body>
</html>"""
    return html


def save_lecture(
    html: str,
    subject: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """保存讲义到 lectures 目录，返回文件绝对路径。"""
    os.makedirs(LECTURE_DIR, exist_ok=True)
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        subj = re.sub(r"[^\w\u4e00-\u9fff]", "", subject or "") or "未分类"
        fname = f"讲义_{ts}_{subj}_{uuid.uuid4().hex[:6]}.html"
        output_path = os.path.join(LECTURE_DIR, fname)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    return output_path


def list_lectures() -> List[Dict[str, Any]]:
    """列出已生成讲义。"""
    os.makedirs(LECTURE_DIR, exist_ok=True)
    out = []
    for fn in sorted(os.listdir(LECTURE_DIR), reverse=True):
        if fn.endswith(".html"):
            fp = os.path.join(LECTURE_DIR, fn)
            out.append(
                {
                    "name": fn,
                    "path": fp,
                    "size": os.path.getsize(fp),
                    "mtime": iso_utc_z(datetime.fromtimestamp(os.path.getmtime(fp), timezone.utc)),
                }
            )
    return out


# =========================================================================== #
# A1 增强：MathLens 式深度结构（题目→步骤分解→知识点归因→四段式讲解）
# 仅借鉴 MathLens（CC BY-NC 4.0）思路，代码自研；analysis_templates 分层设计
# 简化为内置 subject 模板注册表，避免破坏现有函数。
# =========================================================================== #

_SUBJECT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "数学": {
        "structure": "坐标系/函数图像/代数推导",
        "assertions": ["极限存在性", "导数符号", "积分收敛"],
    },
    "数电": {
        "structure": "真值表/卡诺图/时序图",
        "assertions": ["逻辑表达式化简", "状态转换"],
    },
    "模电": {
        "structure": "电路图（KCL/KVL/增益断言）",
        "assertions": ["KCL 节点电流平衡", "增益符号与幅值"],
    },
    "英语": {"structure": "句子结构/选项比对", "assertions": ["语法点识别"]},
    "政治": {"structure": "选项辨析/原理定位", "assertions": ["原理对应"]},
    "408": {"structure": "数据结构/算法流程/组成原理", "assertions": ["复杂度边界", "状态转移"]},
}


def _detect_subject_for_template(subject: Optional[str]) -> str:
    s = (subject or "").strip()
    for key in ("408", "数学", "数电", "模电", "英语", "政治"):
        if key in s:
            return key
    return "数学"


_DEEP_PROMPT = (
    "你是考研全科辅导老师。请对题目做 MathLens 式深度结构化分析，严格按以下 JSON 输出"
    "（```json 代码块包裹，不要输出思考过程或额外文字）：\n"
    + ANSWER_RULES
    + "\n"
    "{\n"
    '  "known_conditions": ["已知条件1", ...],\n'
    '  "derived_facts": [{"name": "推导事实名", "derivation": "如何得出", "expression": "表达式(LaTeX)"}],\n'
    '  "structure": "图形/结构构建描述（坐标系/真值表/电路图 spec）",\n'
    '  "target_conclusion": "待证/待求结论",\n'
    '  "steps": [{"title": "步骤标题", "content": "推导内容(LaTeX)", "keywords": ["关键词锚点1", ...], "conclusion": "本步结论"}],\n'
    '  "knowledge_points": [{"name": "知识点名", "role": "primary|secondary"}],\n'
    '  "four_part": {"kaodian": "1.考点定位（引用知识点）", "dagang": "2.大纲依据（考纲条目）", "silu": "3.思路拆解（分步）", "ganrao": "4.干扰项解析（逐个说明错误选项）"}\n'
    "}\n"
    "要求：推导严谨、分步清晰；步骤含关键词锚点；知识点名称尽量与平台 knowledge_points 表一致；"
    "干扰项解析强制逐个错误选项说明为什么错。"
)


def _map_knowledge_points(db, names: List[str]) -> List[Dict[str, Any]]:
    """知识点归因：将模型输出的知识点名称映射到 knowledge_points 表真实 ID。"""
    if not names or db is None:
        return [{"name": n, "id": None, "matched": False} for n in names]
    out = []
    try:
        conn = wrap_conn(db.connection().connection)
        for n in names:
            name = (n or "").strip()
            if not name:
                continue
            row = conn.execute(
                "SELECT id, name, subject, chapter FROM knowledge_points WHERE name = ? LIMIT 1",
                (name,),
            ).fetchone()
            if row:
                out.append({"name": name, "id": row[0], "matched": True,
                            "subject": row[2], "chapter": row[3]})
                continue
            row = conn.execute(
                "SELECT id, name, subject, chapter FROM knowledge_points"
                " WHERE name LIKE ? LIMIT 1",
                (f"%{name}%",),
            ).fetchone()
            if row:
                out.append({"name": name, "id": row[0], "matched": True,
                            "subject": row[2], "chapter": row[3],
                            "note": "模糊匹配"})
                continue
            out.append({"name": name, "id": None, "matched": False})
    except Exception:
        out = [{"name": n, "id": None, "matched": False} for n in names]
    return out


def deep_analyze_problem(
    question: str,
    subject: Optional[str] = None,
    prefer: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """A1 MathLens 式深度分析入口。

    输出包含：
      - known_conditions / derived_facts / structure / target_conclusion / steps(含锚点)
      - knowledge_points（归因到 knowledge_points 表真实 ID）
      - four_part 四段式讲解（考点定位/大纲依据/思路拆解/干扰项解析）
      - build_sft 兼容质检字段（is_copy / noisy）
    """
    t0 = time.time()
    from services.model_gateway import get_gateway

    tpl = _SUBJECT_TEMPLATES.get(_detect_subject_for_template(subject), {})
    system_prompt = _DEEP_PROMPT + f"\n本题科目模板：structure={tpl.get('structure')}；断言项={tpl.get('assertions')}"

    gateway = get_gateway()
    result = gateway.chat(
        question=question,
        subject=subject,
        task="题目分析",
        prefer=prefer,
        system_prompt=system_prompt,
        db=db,
    )
    raw_answer = result.get("answer", "") or ""
    clean_answer = _strip_think(raw_answer)
    parsed = _extract_json(clean_answer)
    if parsed is None:
        parsed = {
            "known_conditions": [],
            "derived_facts": [],
            "structure": "",
            "target_conclusion": "",
            "steps": [{"title": "解答", "content": clean_answer or raw_answer,
                       "keywords": [], "conclusion": ""}],
            "knowledge_points": [],
            "four_part": {"kaodian": "", "dagang": "", "silu": clean_answer or raw_answer, "ganrao": ""},
        }

    # 知识点归因（映射真实 ID）
    kp_names = [kp.get("name") if isinstance(kp, dict) else str(kp)
                for kp in (parsed.get("knowledge_points") or [])]
    mapped = _map_knowledge_points(db, kp_names)
    parsed["knowledge_points_mapped"] = mapped
    parsed["knowledge_point_ids"] = [m["id"] for m in mapped if m.get("id")]

    four = parsed.get("four_part") or {}
    four_text = (
        f"{four.get('kaodian', '')}\n{four.get('dagang', '')}\n"
        f"{four.get('silu', '')}\n{four.get('ganrao', '')}"
    ).strip()

    struct = {
        "question": question,
        "subject": subject or "",
        "known_conditions": parsed.get("known_conditions") or [],
        "derived_facts": parsed.get("derived_facts") or [],
        "structure": parsed.get("structure") or "",
        "target_conclusion": parsed.get("target_conclusion") or "",
        "steps": parsed.get("steps") or [],
        "knowledge_points": parsed.get("knowledge_points") or [],
        "knowledge_points_mapped": mapped,
        "knowledge_point_ids": parsed.get("knowledge_point_ids") or [],
        "four_part": four,
        "four_part_text": four_text,
        "template": _detect_subject_for_template(subject),
        "validator_notes": [],
        "engine": result.get("engine", ""),
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "latency_ms": result.get("latency_ms", 0),
        "fallback_used": result.get("fallback_used", False),
        "error": result.get("error"),
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }

    # 断言层（analysis_validator 简化）：检查步骤与四段式完整性
    notes = []
    if not struct["steps"]:
        notes.append("缺少步骤分解")
    if not four.get("kaodian"):
        notes.append("四段式缺少考点定位")
    if not four.get("ganrao"):
        notes.append("四段式缺少干扰项解析")
    struct["validator_notes"] = notes
    return struct


# =========================================================================== #
# A1 build_sft 友好输出：对齐 D:\\kaoyan_ai\\pipeline\\build_sft.py 质检口径
#   is_copy：16-gram 重合度 > 0.5 判为重复（丢弃）
#   noisy  ：18 个噪声词命中判为噪声
# =========================================================================== #

_NOISY_WORDS = [
    "加载中", "点击下载", "关注公众号", "微信扫码", "广告", "推广",
    "复制链接", "提取码", "百度网盘", "转发", "点赞", "收藏",
    "打开APP", "阅读原文", "点击上方", "长按识别", "仅供参考", "免责声明",
]


def _n_grams(text: str, n: int = 16) -> set:
    t = re.sub(r"\s+", "", text or "")
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def is_copy(text1: str, text2: str, threshold: float = 0.5) -> bool:
    """build_sft.is_copy 口径：16-gram 重合度 > 0.5 判为重复。"""
    g1, g2 = _n_grams(text1), _n_grams(text2)
    if not g1 or not g2:
        return False
    inter = len(g1 & g2)
    return inter / min(len(g1), len(g2)) > threshold


def noisy(text: str) -> bool:
    """build_sft.noisy 口径：18 个噪声词命中。"""
    t = text or ""
    return any(w in t for w in _NOISY_WORDS)


def build_sft_entry(
    analysis: Dict[str, Any],
    *,
    instruction: Optional[str] = None,
) -> Dict[str, Any]:
    """将深度分析结果转为 SFT 语料条目（含质检字段）。

    Returns:
        {
          "instruction": 题目,
          "output": 四段式讲解文本,
          "is_copy": bool, "noisy": bool,
          "quality_ok": bool,          # 可进入语料生产线
          "subject", "knowledge_point_ids", "source": "analysis_engine.deep_analyze"
        }
    """
    instruction = instruction or analysis.get("question", "")
    output = (
        analysis.get("four_part_text")
        or " ".join(s.get("content", "") for s in (analysis.get("steps") or []))
    )
    entry = {
        "instruction": instruction,
        "output": output,
        "is_copy": False,
        "noisy": noisy(output) or noisy(instruction),
        "quality_ok": True,
        "subject": analysis.get("subject", ""),
        "knowledge_point_ids": analysis.get("knowledge_point_ids", []),
        "source": "analysis_engine.deep_analyze",
    }
    entry["quality_ok"] = not (entry["is_copy"] or entry["noisy"]) and bool(output.strip())
    return entry
