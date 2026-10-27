# -*- coding: utf-8 -*-
"""电路图理解服务（V11 模块3）。

主路径：本地 Ollama 上的 qwen2.5vl:7b VLM 直接读图，输出结构化拓扑
（元器件清单 / 连接关系 / 电路类型 / 自然语言描述）。

补充：PaddleOCR 微服务（http://127.0.0.1:8888）做图中文字标签识别，
与 VLM 结果交叉校正（R1/C1/VCC/GND 等参考位号）。OCR 不可用时
自动降级为纯 VLM 路径，不阻塞主流程。

设计原则：
- 不臆造元器件：VLM 不确定的字段留空或写 "unknown"，由调用方决定是否追问。
- 容错清晰：Ollama 不可达 / VLM 输出非法 JSON / OCR 超时，都有明确错误字段。
- 本模块只输出"电路拓扑理解"，不做解题状态机（解题由并行 Agentic 单元负责）。

对外接口：
    svc = CircuitVisionService()
    result = svc.analyze("path/to/circuit.png", question_text="...")
    # result = {
    #   "ok": bool,
    #   "circuit_type": "amplifier|rectifier|filter|logic|power|unknown",
    #   "components": [{"designator":"R1","type":"resistor","value":"10k","net_nodes":["Vcc","Base"],"confidence":"high|medium|low"}],
    #   "connections": [{"from":"R1.pin1","to":"Vcc"}, ...],
    #   "nodes": ["Vcc","GND","Base","Collector", ...],
    #   "description": "自然语言描述...",
    #   "question_hints": "结合题目文本的电路理解要点",
    #   "engines": {"vlm":"ok|unavailable|error", "ocr":"ok|skipped|unavailable|error"},
    #   "errors": [...],
    #   "elapsed_ms": ...
    # }
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from utils.compute_nodes import ocr_service_url, ollama_base, service_headers

# ---------------------------------------------------------------------------
# 默认配置（可用环境变量覆盖）
# ---------------------------------------------------------------------------
DEFAULT_OLLAMA_BASE = ollama_base()
DEFAULT_VLM_MODEL = os.environ.get("CIRCUIT_VLM_MODEL", "qwen2.5vl:7b")
# 备用视觉模型：主模型输出乱码/非 JSON 时自动切换重试（可空）
DEFAULT_VLM_MODEL_FALLBACK = os.environ.get("CIRCUIT_VLM_MODEL_FALLBACK", "")
# VLM 失败重试次数（每次换用下一个可用模型；0 表示不重试）
DEFAULT_VLM_RETRIES = int(os.environ.get("CIRCUIT_VLM_RETRIES", "1"))
DEFAULT_OCR_URL = ocr_service_url()
DEFAULT_TIMEOUT = float(os.environ.get("CIRCUIT_VLM_TIMEOUT", "180"))
DEFAULT_OCR_TIMEOUT = float(os.environ.get("CIRCUIT_OCR_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# VLM Prompt（中文，要求严格 JSON）
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """你是一名资深模拟/数字电路识图专家。给定一张电路原理图，请严格输出 JSON，不要输出任何 JSON 以外的文字。

JSON schema（字段名必须完全一致）：
{
  "circuit_type": "amplifier|rectifier|filter|regulator|logic|oscillator|power_supply|mixed|unknown",
  "circuit_type_cn": "电路类型中文简述，如'共射极放大电路'、'桥式整流电路'、'RC低通滤波'",
  "components": [
    {
      "designator": "R1/C1/Q1/D1/U1/V1/L1 等参考位号；图中看不清就写 unknown",
      "type": "resistor|capacitor|inductor|diode|zener|bjt_npn|bjt_pnp|mosfet_n|mosfet_p|opamp|voltage_source|current_source|ground|fuse|switch|logic_gate|ic|transformer|unknown",
      "value": "标称值，如 10kΩ / 100µF / 5V；看不清写 unknown",
      "net_nodes": ["该元件引脚连接到的网络/节点名，如 Vcc/GND/Base/Out；看不清写 unknown"],
      "confidence": "high|medium|low"
    }
  ],
  "connections": [
    {"from": "R1.pin1 或节点名", "to": "Vcc 或另一元件引脚/节点名"}
  ],
  "nodes": ["图中出现的关键网络名/节点名，如 Vcc, GND, Vin, Vout, Base, Collector, Emitter"],
  "description": "2-4 句中文自然语言描述：电路结构、信号流向、典型功能。",
  "uncertainties": ["你不确定的地方，例如'R2 阻值无法辨认'、'右下角连线可能是反馈']
}

要求：
1. 只输出 JSON，不要 markdown 代码块包裹，不要解释。
2. 严禁臆造元器件；图中看不清就写 unknown 并放进 uncertainties。
3. designator 优先使用图中印刷位号（R1/C1/Q1 等）。
4. 连接关系按图中真实连线描述，不要凭经验补全。
"""


def _build_user_prompt(question_text: Optional[str], ocr_hints: Optional[str]) -> str:
    parts: List[str] = ["请识别这张电路图。"]
    if ocr_hints:
        parts.append(f"OCR 辅助识别到图中文字标签（仅供交叉参考，以你自己的视觉判断为准）：{ocr_hints}")
    if question_text:
        parts.append(f"题目文本（结合题意给出电路理解要点，但不要解题）：{question_text}")
    parts.append("按系统要求的 JSON schema 输出。")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------
class CircuitVLMUnavailable(RuntimeError):
    """Ollama 服务不可用或 VLM 模型未安装。"""


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------
@dataclass
class CircuitVisionService:
    ollama_base: str = DEFAULT_OLLAMA_BASE
    vlm_model: str = DEFAULT_VLM_MODEL
    vlm_model_fallback: str = DEFAULT_VLM_MODEL_FALLBACK
    vlm_retries: int = DEFAULT_VLM_RETRIES
    ocr_url: str = DEFAULT_OCR_URL
    timeout: float = DEFAULT_TIMEOUT
    ocr_timeout: float = DEFAULT_OCR_TIMEOUT
    use_ocr: bool = True

    # -------------------- 内部工具 --------------------
    @staticmethod
    def _encode_image(source: Union[str, bytes]) -> Tuple[bytes, str]:
        """接受路径或 bytes，返回 (image_bytes, filename_hint)。"""
        if isinstance(source, bytes):
            return source, "circuit.png"
        if not os.path.exists(source):
            raise FileNotFoundError(f"图片不存在: {source}")
        with open(source, "rb") as f:
            data = f.read()
        return data, os.path.basename(source)

    def _http(self):
        """延迟导入 httpx，避免未安装时阻塞模块 import。"""
        import httpx
        return httpx

    # -------------------- 健康检查 --------------------
    def health_check(self) -> Dict[str, Any]:
        """检查 Ollama 与 PaddleOCR 微服务是否可用（同步，短超时）。"""
        result: Dict[str, Any] = {"vlm": {"ok": False}, "ocr": {"ok": False}}

        # Ollama tags
        try:
            httpx = self._http()
            r = httpx.get(f"{self.ollama_base}/api/tags", timeout=5.0)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            vlm_ok = self.vlm_model in models or any(self.vlm_model.split(":")[0] in m for m in models)
            result["vlm"] = {
                "ok": vlm_ok,
                "model": self.vlm_model,
                "installed_models": models,
            }
        except Exception as e:
            result["vlm"] = {"ok": False, "error": f"Ollama 不可达: {e!s}"}

        # OCR
        if not self.use_ocr:
            result["ocr"] = {"ok": False, "skipped": True}
        else:
            try:
                httpx = self._http()
                r = httpx.get(f"{self.ocr_url}/health", headers=service_headers(), timeout=3.0)
                r.raise_for_status()
                result["ocr"] = {"ok": True, **r.json()}
            except Exception as e:
                result["ocr"] = {"ok": False, "error": f"PaddleOCR 微服务不可达: {e!s}"}

        return result

    # -------------------- VLM 调用 --------------------
    def _call_vlm(self, image_b64: str, question_text: Optional[str],
                  ocr_hints: Optional[str], model: Optional[str] = None) -> str:
        """调用 Ollama /api/generate，返回原始文本（应为 JSON）。

        :param model: 要使用的模型名；默认 self.vlm_model。
        """
        httpx = self._http()
        use_model = model or self.vlm_model
        payload = {
            "model": use_model,
            "prompt": _build_user_prompt(question_text, ocr_hints),
            "system": _SYSTEM_PROMPT,
            "images": [image_b64],
            "stream": False,
            "format": "json",   # Ollama 强制 JSON 输出
            "options": {"temperature": 0.1, "num_ctx": 4096},
        }
        try:
            r = httpx.post(
                f"{self.ollama_base}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise CircuitVLMUnavailable(f"Ollama 调用失败: {e!s}") from e

        data = r.json()
        text = (data.get("response") or "").strip()
        if not text:
            raise CircuitVLMUnavailable(f"VLM 返回空响应: {data!r}")
        return text

    # -------------------- JSON 解析（容错） --------------------
    @staticmethod
    def _looks_like_garbage(text: str) -> bool:
        """判断 VLM 输出是否为乱码（视觉塔失效时常见表现）。

        启发式：
        1. CJK 字符极少 + 常见电路词汇命中为 0 + 文本较长 → 乱码。
        2. 周期性重复：取前 2~8 字符作为候选 unit，若 text 几乎由该 unit 重复而成 → 乱码。
        3. 相邻去重后长度 < 原文 30%（单字符重复，如 "aaaa..."）→ 乱码。
        """
        if not text:
            return False
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        meaningful_words = ["the", "this", "is", "are", "and", "图", "电路", "电阻",
                            "电容", "电源", "二极管", "三极管", "输出", "输入", "节点",
                            "resistor", "capacitor", "diode", "transistor", "Vcc", "GND"]
        lower = text.lower()
        meaningful_hits = sum(lower.count(w.lower()) for w in meaningful_words)

        # 条件 1：几乎无 CJK 且无有意义词
        if cjk < 5 and meaningful_hits < 1 and len(text) > 50:
            return True

        # 条件 2：周期重复（"火烧火烧..."、"a a a a..."）
        n = len(text)
        if n > 100:
            for unit_len in range(2, 9):
                unit = text[:unit_len]
                # 检查 text 是否≈ unit 重复
                repeats = n // unit_len
                expected = unit * repeats
                # 允许末尾截断
                if text.startswith(expected) or text[:len(expected)] == expected:
                    return True
                # 高相似度：超过 80% 位置匹配
                mismatches = sum(1 for i, ch in enumerate(text) if ch != unit[i % unit_len])
                if mismatches / n < 0.15:
                    return True

        # 条件 3：单字符重复
        compact: List[str] = []
        for ch in text:
            if not compact or compact[-1] != ch:
                compact.append(ch)
        ratio = len(compact) / max(n, 1)
        if ratio < 0.3 and n > 100:
            return True
        return False

    @staticmethod
    def _extract_balanced_json(text: str) -> Optional[str]:
        """从文本中提取第一个『括号平衡』的 JSON 对象子串。

        与简单 `text[lo:hi+1]` 的区别：逐字符跟踪括号深度，
        只取到完整闭合处，避免截断为 `{'` 或只到第一个 `}` 就停。
        :returns: 平衡的 JSON 子串；找不到返回 None。
        """
        lo = text.find("{")
        if lo == -1:
            return None
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(lo, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            return None
        return text[lo:end + 1]

    @staticmethod
    def _repair_truncated_json(text: str) -> Optional[str]:
        """修复截断的 JSON：补闭合引号与缺失的 ] }。

        适用于 VLM 输出被 max_tokens/num_ctx 截断、或模型生成中断
        导致 `{"key": "value", "arr": [1,2` 这类不完整内容。
        :returns: 补齐后的 JSON 字符串；无法补则返回 None。
        """
        stack: List[str] = []
        in_str = False
        esc = False
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                stack.append("}")
            elif ch == "[":
                stack.append("]")
            elif ch == "}":
                if stack and stack[-1] == "}":
                    stack.pop()
                else:
                    # 多余的闭合符：截断到此处（后续内容无效）
                    text = text[:i]
                    break
            elif ch == "]":
                if stack and stack[-1] == "]":
                    stack.pop()
                else:
                    text = text[:i]
                    break
            i += 1
        if in_str:
            text += '"'
        if stack:
            text += "".join(reversed(stack))
        return text

    @staticmethod
    def _fix_json_common(text: str) -> str:
        """清洗常见脏 JSON：全角引号/冒号、单引号键、尾逗号、BOM。"""
        text = text.lstrip("\ufeff\u00a0")
        text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("：", ":")
        # 单引号对 → 双引号（仅当不像 apostrophe 用法时尽量保守：先只处理整对出现的情况）
        # 简化处理：把独立的 ' 替换为 "，但保留 " 内出现的 '（极少）
        cleaned: List[str] = []
        in_dq = False
        for ch in text:
            if ch == '"':
                in_dq = not in_dq
                cleaned.append(ch)
            elif ch == "'" and not in_dq:
                cleaned.append('"')
            else:
                cleaned.append(ch)
        text = "".join(cleaned)
        # 尾逗号（,} 或 ,]）
        text = re.sub(r",\s*([}\]])", r"\1", text)
        return text

    @staticmethod
    def _result_has_content(obj: Optional[Dict[str, Any]]) -> bool:
        """判断 VLM 解析结果是否包含有效电路内容。

        空 dict / 只有未知类型且无元件无节点 → 视为无效结果，
        用于触发 fallback 模型重试（避免模型输出 {} 被当作成功）。
        """
        if not obj:
            return False
        if obj.get("components"):
            return True
        if obj.get("nodes"):
            return True
        ctype = obj.get("circuit_type") or obj.get("circuit_type_cn") or ""
        return bool(ctype) and ctype != "unknown"

    @staticmethod
    def _parse_vlm_json(raw: str) -> Dict[str, Any]:
        """从 VLM 输出中提取 JSON。多级容错：

        1. 去掉 markdown 代码块包裹、常见脏字符；
        2. 平衡括号提取（避免截断为 `{'` 或中途闭合）；
        3. 截断修复（补 `"` / `]` / `}`）；
        4. 逐级候选 loads；全部失败且像乱码时给出明确错误。

        :raises ValueError: 输出既不是合法 JSON，也明显是乱码（视觉塔失效）。
        """
        text = raw.strip()
        # 去掉 ```json ... ``` 包裹
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()

        candidates: List[str] = []
        candidates.append(text)
        # 平衡括号提取
        balanced = CircuitVisionService._extract_balanced_json(text)
        if balanced is not None and balanced != text:
            candidates.append(balanced)
        # 截断修复（对原文与平衡子串都试）
        for base in list(candidates):
            repaired = CircuitVisionService._repair_truncated_json(base)
            if repaired and repaired != base:
                candidates.append(repaired)
        # 常见脏字符清洗
        fixed = CircuitVisionService._fix_json_common(text)
        if fixed != text:
            candidates.append(fixed)

        seen: set = set()
        last_err: Optional[Exception] = None
        for cand in candidates:
            if cand in seen:
                continue
            seen.add(cand)
            try:
                obj = json.loads(cand)
                if isinstance(obj, dict):
                    # 即使解析成功，若内容为空且原文像乱码仍报错
                    if not obj and CircuitVisionService._looks_like_garbage(raw):
                        raise ValueError(
                            f"VLM 返回空 JSON 且原文像乱码: {raw[:200]!r}"
                        )
                    return obj
            except json.JSONDecodeError as e:
                last_err = e
        if CircuitVisionService._looks_like_garbage(raw):
            raise ValueError(
                "VLM 输出为乱码（视觉塔可能未正确加载），"
                f"原文片段: {raw[:200]!r}"
            )
        raise ValueError(
            f"VLM 输出不是合法 JSON: {last_err!s}; 原文片段: {text[:300]!r}"
        )

    # -------------------- OCR 补充 --------------------
    def _call_ocr(self, image_bytes: bytes, filename: str) -> Tuple[List[str], Optional[str]]:
        """调用 OCR 识别图中文字标签。降级链：
        1. PaddleOCR 微服务（http://127.0.0.1:8888）
        2. 本地 RapidOCR（services.ocr_service.OCRService）
        3. 都不可用则返回 ([], "skipped")
        """
        if not self.use_ocr:
            return [], "skipped"
        httpx = self._http()
        # 1) PaddleOCR 微服务
        try:
            r = httpx.post(
                f"{self.ocr_url}/ocr",
                files={"file": (filename, image_bytes, "image/png")},
                headers=service_headers(),
                timeout=self.ocr_timeout,
            )
            r.raise_for_status()
            data = r.json()
            labels = [t for t in (data.get("result") or []) if t and str(t).strip()]
            if labels:
                return labels, None
            return [], "paddleocr: 无识别结果"
        except Exception as e:
            paddle_err = f"PaddleOCR 微服务不可达: {e!s}"

        # 2) 本地 RapidOCR
        try:
            from services.ocr_service import OCRService
            local = OCRService()
            text = local.recognize_bytes(image_bytes)
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if lines:
                return lines, None
            return [], f"{paddle_err}; RapidOCR: 无识别结果"
        except Exception as e2:
            return [], f"{paddle_err}; RapidOCR 也不可用: {e2!s}"

    # -------------------- OCR 与 VLM 交叉校正 --------------------
    @staticmethod
    def _cross_check(components: List[Dict[str, Any]],
                     ocr_labels: List[str]) -> List[Dict[str, Any]]:
        """把 OCR 识别到的标签合并进 components。

        策略：
        - OCR 标签若是 R/C/L/D/Q/U/V/J/F/S 开头 + 数字 的位号，
          且 VLM 没识别到该 designator，则补一条 confidence=low 的 component。
        - 不修改 VLM 已识别的元器件（视觉判断优先）。
        """
        if not ocr_labels:
            return components
        known_designators = {c.get("designator", "") for c in components}
        # 位号正则：从 "R1=10kΩ"、"C1 100µF"、"Q1" 这类标签开头提取 R1/C1/Q1
        refdes_extract = re.compile(r"^\s*((?:[RCLDQUJVFSW]|RT|CN|JP|K)\d{1,4}[A-Z]?)")
        extras: List[Dict[str, Any]] = []
        seen_extras = set()
        for label in ocr_labels:
            lab = label.strip()
            if not lab or len(lab) > 30:
                continue
            if lab in {"GND", "VCC", "Vdd", "Vss", "Vin", "Vout", "+Vout", "+5V", "+12V", "AC220V"}:
                continue  # 这些是节点/电源名，后面并入 nodes
            m = refdes_extract.match(lab)
            if not m:
                continue
            desg = m.group(1)
            if desg in known_designators or desg in seen_extras:
                continue
            seen_extras.add(desg)
            extras.append({
                "designator": desg,
                "type": "unknown",
                "value": "unknown",
                "net_nodes": ["unknown"],
                "confidence": "low",
                "source": "ocr_only",
                "raw_label": lab,
            })
        return components + extras

    # -------------------- 主入口 --------------------
    def analyze(self,
                image: Union[str, bytes],
                question_text: Optional[str] = None,
                use_ocr: Optional[bool] = None) -> Dict[str, Any]:
        """识别电路图，返回结构化拓扑。

        :param image: 本地图片路径 或 bytes
        :param question_text: 题目文本（可选），用于结合题意给提示
        :param use_ocr: 是否启用 PaddleOCR 交叉校正（默认 True）
        """
        t0 = time.time()
        engines: Dict[str, str] = {"vlm": "pending", "ocr": "pending"}
        errors: List[str] = []

        # 1) 读图片
        try:
            image_bytes, filename = self._encode_image(image)
        except Exception as e:
            return {
                "ok": False, "circuit_type": "unknown",
                "components": [], "connections": [], "nodes": [],
                "description": "", "question_hints": "",
                "engines": engines, "errors": [f"图片读取失败: {e!s}"],
                "elapsed_ms": int((time.time() - t0) * 1000),
            }
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        # 2) OCR 补充（best-effort）
        ocr_labels: List[str] = []
        if use_ocr is False:
            engines["ocr"] = "skipped"
        else:
            ocr_labels, ocr_err = self._call_ocr(image_bytes, filename)
            if ocr_err:
                engines["ocr"] = "unavailable"
                errors.append(f"[OCR] {ocr_err}")
            else:
                engines["ocr"] = "ok" if ocr_labels else "empty"

        ocr_hints = ", ".join(ocr_labels) if ocr_labels else None

        # 3) VLM 主路径（多模型重试：主模型失败 → fallback 模型 → 报错）
        models_to_try: List[str] = [self.vlm_model]
        if self.vlm_model_fallback and self.vlm_model_fallback != self.vlm_model:
            models_to_try.append(self.vlm_model_fallback)
        # 重试次数只对"解析失败/乱码"生效；模型不可达直接短路
        vlm_obj: Optional[Dict[str, Any]] = None
        vlm_raw: str = ""
        vlm_errs: List[str] = []
        for attempt in range(1 + max(self.vlm_retries, 0)):
            model = models_to_try[attempt % len(models_to_try)]
            try:
                raw = self._call_vlm(image_b64, question_text, ocr_hints, model=model)
                vlm_raw = raw
                vlm_obj = self._parse_vlm_json(raw)
                # 空结果视为无效（如模型输出 {} 而非真实拓扑）：计入失败并继续重试
                if not self._result_has_content(vlm_obj):
                    raise ValueError(
                        f"VLM 返回空结果（无电路类型/元件/节点）: {raw[:200]!r}"
                    )
                engines["vlm"] = "ok"
                if attempt > 0 or len(models_to_try) > 1 and model != self.vlm_model:
                    engines["vlm"] = f"ok(fallback:{model})"
                break
            except CircuitVLMUnavailable as e:
                # 模型不可达：不再对该模型重试，换 fallback 或直接失败
                vlm_errs.append(f"[VLM] 模型 {model}: {e!s}")
                engines["vlm"] = "unavailable"
                if len(models_to_try) > 1 and models_to_try.index(model) < len(models_to_try) - 1:
                    continue
                return {
                    "ok": False, "circuit_type": "unknown",
                    "components": self._cross_check([], ocr_labels),
                    "connections": [], "nodes": [],
                    "description": "",
                    "question_hints": "",
                    "engines": engines, "errors": vlm_errs,
                    "ocr_labels": ocr_labels,
                    "elapsed_ms": int((time.time() - t0) * 1000),
                }
            except Exception as e:
                # 解析失败/乱码/未预期错误：记录后按重试次数再试
                vlm_errs.append(f"[VLM] 模型 {model} 尝试 {attempt + 1}: {e!s}")
                engines["vlm"] = "error"
                if attempt < self.vlm_retries:
                    continue
                return {
                    "ok": False, "circuit_type": "unknown",
                    "components": self._cross_check([], ocr_labels),
                    "connections": [], "nodes": [],
                    "description": vlm_raw[:500],  # 保留原文便于排查
                    "question_hints": "",
                    "engines": engines, "errors": vlm_errs,
                    "ocr_labels": ocr_labels,
                    "elapsed_ms": int((time.time() - t0) * 1000),
                }

        obj = vlm_obj or {}

        components = obj.get("components") or []
        connections = obj.get("connections") or []
        nodes = obj.get("nodes") or []

        # 5) OCR 交叉校正：补 VLM 漏识别的位号
        components = self._cross_check(components, ocr_labels)

        # 6) 合并节点（OCR 看到的 Vcc/GND 也并入 nodes）
        extra_nodes = [l for l in ocr_labels
                       if l in {"GND", "VCC", "Vdd", "Vss", "Vin", "Vout", "+5V", "+12V", "-12V"}]
        nodes = list(dict.fromkeys(list(nodes) + extra_nodes))

        # 7) question_hints：题目文本结合电路类型给出提示（不解题）
        question_hints = ""
        if question_text:
            ctype = obj.get("circuit_type_cn") or obj.get("circuit_type") or "该"
            question_hints = (
                f"结合题目文本，本图识别为「{ctype}」；"
                f"后续解题时需关注该电路的输入/输出关系与关键节点电压。"
            )

        return {
            "ok": True,
            "circuit_type": obj.get("circuit_type", "unknown"),
            "circuit_type_cn": obj.get("circuit_type_cn", ""),
            "components": components,
            "connections": connections,
            "nodes": nodes,
            "description": obj.get("description", ""),
            "uncertainties": obj.get("uncertainties", []),
            "question_hints": question_hints,
            "engines": engines,
            "ocr_labels": ocr_labels,
            "errors": errors,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }


# ---------------------------------------------------------------------------
# 模块级单例（方便 routers 直接 import）
# ---------------------------------------------------------------------------
_default_singleton: Optional[CircuitVisionService] = None


def get_circuit_vision_service() -> CircuitVisionService:
    global _default_singleton
    if _default_singleton is None:
        _default_singleton = CircuitVisionService()
    return _default_singleton
