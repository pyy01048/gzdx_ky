# -*- coding: utf-8 -*-
"""V11 模块5：电路图辅助理解（图内文字 OCR + 本地 LLM 结构化描述）。

对外入口（**冻结签名**，后续 Agentic 升级按此接线，不得改动）：

    async def analyze_circuit_image(image_path: str, question_text: str) -> Dict[str, Any]

返回键固定：
    {
      "status": "ok" | "degraded" | "failed",
      "engine": str,                     # 实际使用的 OCR/描述引擎名
      "labels": List[str],               # 图内识别出的文字标签（R1/C1/VCC/地 等）
      "description": str,                # 结构化电路描述（元器件清单+连接关系+电路类型+与题面结合）
      "circuit_type": Optional[str],     # 电路类型判断
      "degraded_reason": Optional[str],  # 降级原因，如实说明失败环节
      "question_text": str,
    }

引擎优先级：
    0. CircuitVisionService（V11 模块3 并行线，qwen2.5vl:7b VLM 直接读图 +
       PaddleOCR 交叉校正）——可选优先引擎。**不修改该文件**；
       import 失败 / 调用异常 / 返回 ok=False 时落到本模块自有主路径。
    1. PaddleOCR 微服务（http://127.0.0.1:8888，services.ocr_service.PaddleOCRService）
       提取图内文字标签；不可用 → 本地 RapidOCR（services.ocr_service.OCRService）回退。
    2. Ollama qwen3:8b（/api/chat、stream=False、keep_alive=10m、超时 360s、
       不传 think:false、services.llm_output.extract_answer 提取正文）按结构化模板描述。
    3. 兜底增强：OCR 标签过少或文本 LLM 失败时，qwen2.5vl:7b 直接读图
       （/api/chat 的 messages.images 字段，图片 base64）生成描述。

容错：任一环节失败都如实降级，description 至少给出基于题面文字的兜底分析，
绝不向上抛异常。只连 127.0.0.1:8888 与 127.0.0.1:11434，不新增第三方依赖（httpx）。
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from utils.compute_nodes import ocr_service_url

# --------------------------------------------------------------------------- #
# 配置（环境变量可覆盖；只允许本地回环地址）
# --------------------------------------------------------------------------- #
from utils.ollama_host import resolve_ollama_host as _resolve_ollama_host

OLLAMA_HOST = _resolve_ollama_host()
OCR_PADDLE_URL = ocr_service_url()
TEXT_MODEL = os.getenv("CIRCUIT_LLM_MODEL", "qwen3:8b")          # 文本结构化描述
VLM_MODEL = os.getenv("CIRCUIT_VLM_MODEL", "qwen2.5vl:7b")       # VLM 直接读图兜底
TEXT_TIMEOUT = float(os.getenv("CIRCUIT_TEXT_TIMEOUT", "360"))    # qwen3 思考模型，给够
VLM_TIMEOUT = float(os.getenv("CIRCUIT_VLM_TIMEOUT", "180"))

#: OCR 有效标签数阈值：少于此数视为"标签过少"，直接走 VLM 读图兜底
MIN_LABELS = 2


# --------------------------------------------------------------------------- #
# 图内文字标签提取（R1 / C2 / VCC / GND / 10kΩ / +5V …）
# --------------------------------------------------------------------------- #
_LABEL_RES = [
    re.compile(r"^[A-Za-z]{1,4}\d{1,4}[A-Za-z]?$"),                       # R1, C10, Q2, U1A
    re.compile(r"^(VCC|VDD|VEE|VSS|GND|AGND|DGND|Vin|Vout|Vi|Vo|Vb|Ve|Vc)$", re.I),
    re.compile(r"^[+\-]?\d+(?:\.\d+)?(?:V|v|kΩ|K|Ω|ohm|uF|µF|nF|pF|mF)$", re.I),
    re.compile(r"^(地|电源|输入|输出)$"),
]

_TOKEN_SPLIT_RE = re.compile(r"[\s,;，、()（）\[\]{}:：/\\=~]+")


def _extract_labels(ocr_text: str) -> List[str]:
    """从 OCR 原始文本中挑出像电路标签的词（位号 / 电源网络 / 数值参数），按出现顺序去重。"""
    if not ocr_text:
        return []
    labels: List[str] = []
    seen = set()
    for tok in _TOKEN_SPLIT_RE.split(ocr_text):
        t = tok.strip().strip(".。,，;；")
        if not t or len(t) > 16:
            continue
        if any(p.match(t) for p in _LABEL_RES):
            key = t.upper()
            if key not in seen:
                seen.add(key)
                labels.append(t)
    return labels


# --------------------------------------------------------------------------- #
# 优先引擎：CircuitVisionService（V11 模块3，只读调用，绝不修改该文件）
# --------------------------------------------------------------------------- #
def _map_circuit_vision(cv: Dict[str, Any], question_text: str) -> Dict[str, Any]:
    """把 CircuitVisionService.analyze 的成功结果映射为冻结返回结构。"""
    labels: List[str] = []
    seen = set()

    def _push(t: Any) -> None:
        s = str(t).strip()
        if not s or s.lower() == "unknown":
            return
        k = s.upper()
        if k not in seen:
            seen.add(k)
            labels.append(s)

    for comp in cv.get("components") or []:
        if isinstance(comp, dict):
            _push(comp.get("designator"))
    for node in cv.get("nodes") or []:
        _push(node)
    for lab in cv.get("ocr_labels") or []:
        _push(lab)

    desc_parts = [
        str(cv.get("description") or "").strip(),
        str(cv.get("question_hints") or "").strip(),
    ]
    description = "\n".join(p for p in desc_parts if p)

    engines = cv.get("engines") or {}
    engine = f"circuit_vision({VLM_MODEL})"
    if engines.get("ocr") == "ok":
        engine += "|ocr:paddle"

    circuit_type = cv.get("circuit_type_cn") or cv.get("circuit_type") or None
    if str(circuit_type).lower() == "unknown":
        circuit_type = None

    return {
        "status": "ok",
        "engine": engine,
        "labels": labels,
        "description": description,
        "circuit_type": circuit_type,
        "degraded_reason": None,
        "question_text": question_text or "",
    }


async def _circuit_vision_priority(
    image_path: str, question_text: str
) -> Optional[Dict[str, Any]]:
    """优先尝试 CircuitVisionService；任何失败都返回 None，由主路径接管。"""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        from services.circuit_vision import CircuitVisionService  # noqa: F401
    except Exception:
        # 并行线模块未就绪（尚未创建 / 依赖缺失）——静默回退主路径
        return None
    try:
        svc = CircuitVisionService()
        # analyze 是同步且阻塞（httpx 同步 + VLM 推理），丢到线程池避免卡事件循环
        cv = await asyncio.to_thread(svc.analyze, image_path, question_text, True)
    except Exception:
        return None
    if not isinstance(cv, dict) or not cv.get("ok"):
        return None
    try:
        return _map_circuit_vision(cv, question_text)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# OCR 层：PaddleOCR 微服务优先，本地 RapidOCR 回退
# --------------------------------------------------------------------------- #
async def _ocr_paddle(image_path: str) -> str:
    """调用 PaddleOCR 微服务（8888），返回原始文本；失败抛异常由调用方回退。"""
    from services.ocr_service import PaddleOCRService

    with open(image_path, "rb") as f:
        image_bytes = f.read()
    # fallback_to_local=False：这里要的是"微服务到底通不通"，回退由本模块显式做
    svc = PaddleOCRService(service_url=OCR_PADDLE_URL, fallback_to_local=False)
    result = await svc.recognize_bytes(image_bytes, filename=os.path.basename(image_path))
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result.get("text") or ""


def _ocr_local(image_path: str) -> str:
    """本地 RapidOCR（CPU ONNX），同步函数，由 asyncio.to_thread 调用。"""
    from services.ocr_service import OCRService

    return OCRService(device="cpu").recognize(image_path) or ""


# --------------------------------------------------------------------------- #
# 本地 LLM 层：qwen3:8b 文本结构化描述 / qwen2.5vl:7b 读图兜底
# --------------------------------------------------------------------------- #
async def _ollama_chat(
    model: str,
    prompt: str,
    images_b64: Optional[List[str]] = None,
    timeout: float = TEXT_TIMEOUT,
) -> str:
    """统一的 Ollama /api/chat 调用。

    - stream=False、keep_alive=10m；
    - **不传 think:false**（qwen3 系列会把思维链倒进 content）；
    - 用 services.llm_output.extract_answer 提取干净正文；空正文视为失败抛异常。
    """
    message: Dict[str, Any] = {"role": "user", "content": prompt}
    if images_b64:
        message["images"] = images_b64  # VLM 模型读图（base64，不带 data: 前缀）
    payload = {
        "model": model,
        "messages": [message],
        "stream": False,
        "keep_alive": "10m",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        resp = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

    from services.llm_output import extract_answer

    answer = extract_answer(data.get("message") or {})
    if not answer:
        raise RuntimeError(f"模型 {model} 未返回干净正文（仅思考过程或空）")
    return answer.strip()


def _build_text_prompt(question_text: str, labels: List[str]) -> str:
    labels_str = "、".join(labels) if labels else "（未识别到图内文字标签）"
    return f"""你是电子电路识图与解题助手。请根据题面与图中识别到的标签分析这张电路图，严格按以下四个小节输出，不要输出小节之外的解释：

【元器件清单】列出图中元器件的位号、类型与参数（如电阻R1=10kΩ、电容C1=100µF、三极管Q1、运放U1、电源VCC=+5V、接地端GND等）。
【连接关系】描述主要连接：信号从哪里输入、流经哪些元件、从哪里输出，电源与地如何接入。
【电路类型】用一句话判断（例如：共射极放大电路 / 反相比例运算放大电路 / 一阶RC低通滤波 / 半波整流电路 / 分压偏置电路）。只写一句，不要分点。
【与题面结合】结合题面要求，说明该电路如何对应解答题目。

题面：{question_text or "（无题面文字）"}
图中识别到的文字标签：{labels_str}"""


async def _text_describe(question_text: str, labels: List[str]) -> str:
    """qwen3:8b 按结构化模板输出电路描述。"""
    return await _ollama_chat(
        TEXT_MODEL, _build_text_prompt(question_text, labels),
        timeout=TEXT_TIMEOUT,
    )


async def _vlm_describe(image_path: str, question_text: str) -> str:
    """qwen2.5vl:7b 直接读图生成描述（文本 LLM 失败/标签过少时的兜底）。"""
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")
    prompt = (
        "这是一张电路原理图，请用中文按小节输出：\n"
        "【元器件清单】位号+类型+参数\n"
        "【连接关系】信号流向与主要连线\n"
        "【电路类型】一句话（如共射放大/运算放大/一阶RC滤波/二极管整流）\n"
        f"【与题面结合】{question_text or '无题面文字'}"
    )
    return await _ollama_chat(
        VLM_MODEL, prompt, images_b64=[image_b64], timeout=VLM_TIMEOUT,
    )


# --------------------------------------------------------------------------- #
# 结果拼装工具
# --------------------------------------------------------------------------- #
def _parse_circuit_type(description: str) -> Optional[str]:
    """从结构化描述的【电路类型】小节里提取一句话类型判断。

    截取范围：下一个【小节】之前，或文本结束；再按句号/换行切第一句。
    （兼容 VLM 兜底输出"【电路类型】反相比例运算放大电路。VLM补充描述。"这类单行。）
    """
    if not description:
        return None
    m = re.search(r"【电路类型】\s*(.+?)(?=【|$)", description, re.S)
    if not m:
        return None
    t = re.split(r"[。\n]", m.group(1).strip(), maxsplit=1)[0].strip("。:： ")
    return t or None


def _question_only_description(question_text: str, labels: List[str]) -> str:
    """所有图描述引擎都失败时的兜底：至少给基于题面文字的分析。"""
    if not question_text and not labels:
        return ""
    parts: List[str] = []
    if labels:
        parts.append(f"图中识别到的文字标签：{', '.join(labels)}。")
    if question_text:
        parts.append(f"以下仅基于题面文字：{question_text}")
    parts.append("（注：图描述引擎未能返回结构化结果，请以人工识图核对为准。）")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# 对外主入口（冻结签名）
# --------------------------------------------------------------------------- #
async def analyze_circuit_image(image_path: str, question_text: str = "") -> Dict[str, Any]:
    """电路图辅助理解主入口。任何环节失败都如实降级，绝不抛异常。"""
    degraded_reasons: List[str] = []
    question_text = question_text or ""

    # ---- 0) 优先引擎：CircuitVisionService（VLM 直接读图）----
    try:
        mapped = await _circuit_vision_priority(image_path, question_text)
        if mapped is not None:
            return mapped
    except Exception as e:  # 兜底：优先引擎任何意外都不许炸掉主流程
        degraded_reasons.append(f"circuit_vision 优先引擎异常，已回退主路径: {e}")

    # ---- 1) OCR 提取图内文字标签：Paddle 优先，RapidOCR 回退 ----
    labels: List[str] = []
    ocr_engine = "none"
    image_ok = bool(image_path) and os.path.exists(image_path)

    if image_ok:
        try:
            raw = await _ocr_paddle(image_path)
            labels = _extract_labels(raw)
            ocr_engine = "paddleocr"
            if not labels:
                degraded_reasons.append("PaddleOCR 微服务未识别到有效电路标签")
        except Exception as e:
            degraded_reasons.append(f"PaddleOCR 微服务(8888)不可用，已回退本地 RapidOCR: {e}")
            try:
                raw = await asyncio.to_thread(_ocr_local, image_path)
                labels = _extract_labels(raw)
                ocr_engine = "rapidocr"
                if not labels:
                    degraded_reasons.append("本地 RapidOCR 也未识别到有效电路标签")
            except Exception as e2:
                degraded_reasons.append(f"本地 RapidOCR 识别失败: {e2}")
    else:
        degraded_reasons.append(f"图片文件不存在或不可读: {image_path!r}")

    # ---- 2) 文本 LLM（qwen3:8b）结构化描述：标签充足时优先 ----
    description = ""
    llm_engine = "none"
    labels_ok = len(labels) >= MIN_LABELS

    if labels_ok:
        try:
            description = await _text_describe(question_text, labels)
            if description:
                llm_engine = TEXT_MODEL
            else:
                degraded_reasons.append("文本 LLM(qwen3:8b) 返回空正文")
        except Exception as e:
            degraded_reasons.append(f"文本 LLM(qwen3:8b) 描述失败: {e}")

    # ---- 3) VLM 读图兜底：标签过少或文本 LLM 失败时 ----
    if not description and image_ok:
        try:
            vlm_desc = await _vlm_describe(image_path, question_text)
            if vlm_desc:
                description = vlm_desc
                llm_engine = VLM_MODEL
            else:
                degraded_reasons.append("VLM(qwen2.5vl:7b) 返回空正文")
        except Exception as e:
            degraded_reasons.append(f"VLM(qwen2.5vl:7b) 读图兜底失败: {e}")
            # 标签过少时本跳过了文本 LLM；VLM 也挂了再用题面+少量标签试一次
            if not labels_ok:
                try:
                    description = await _text_describe(question_text, labels)
                    if description:
                        llm_engine = TEXT_MODEL
                except Exception as e2:
                    degraded_reasons.append(f"文本 LLM(qwen3:8b) 二次尝试仍失败: {e2}")

    # ---- 4) 题面文字兜底 ----
    if not description:
        description = _question_only_description(question_text, labels)
        if description:
            degraded_reasons.append(
                "所有图描述引擎均未返回结构化结果，当前为仅基于题面文字的兜底内容"
            )

    circuit_type = _parse_circuit_type(description)

    if not description:
        status = "failed"
    elif degraded_reasons:
        status = "degraded"
    else:
        status = "ok"

    return {
        "status": status,
        "engine": f"ocr:{ocr_engine}|llm:{llm_engine}",
        "labels": labels,
        "description": description,
        "circuit_type": circuit_type,
        "degraded_reason": "; ".join(degraded_reasons) if degraded_reasons else None,
        "question_text": question_text,
    }
