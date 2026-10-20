"""OCR 识别服务（本地开源模型）。

使用 RapidOCR（GitHub 开源：https://github.com/RapidAI/RapidOCR）。
底层为 PaddleOCR PP-OCRv4 系列模型 + ONNX Runtime，纯本地运行，
可选 CPU / GPU（onnxruntime-gpu + CUDA）推理，数据不出本机。
"""

import os
import re
import sys
import tempfile
import threading
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 延迟导入：避免未安装时影响后端启动
_engine = None
_engine_lock = threading.Lock()
_engine_device = None


def _reserve_project_utils() -> None:
    """抢先在 ``sys.modules`` 里占住项目的 ``utils`` 包。

    ``rapidocr_onnxruntime`` 在被 import 时会把**自己的包目录**追加到
    ``sys.path``（该目录下恰好有个 ``utils.py``）。一旦它排在前面，项目根
    的 ``utils`` 包就被遮蔽，之后任何 ``from utils.secret_codec import ...``
    都会抛::

        ModuleNotFoundError: No module named 'utils.secret_codec';
        'utils' is not a package

    实测：只要本进程跑过一次 OCR，随后的入库（``kb_service`` → ``models``
    → ``utils.secret_codec``）就必然崩，3584 篇全量入库无法进行。
    抢先 import 一次即可让项目 utils 永久占据该名字。
    """
    if "utils" in sys.modules:
        return
    try:
        import utils  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        logger.debug("预占项目 utils 包失败（项目根不在 sys.path）: %s", exc)


def _get_engine(device: str = "cpu"):
    """懒加载 RapidOCR 引擎（单例）。"""
    global _engine, _engine_device
    if _engine is not None and _engine_device == device:
        return _engine
    with _engine_lock:
        if _engine is not None and _engine_device == device:
            return _engine
        # 必须在 import rapidocr_onnxruntime 之前调用：见 _reserve_project_utils 注释
        _reserve_project_utils()
        from rapidocr_onnxruntime import RapidOCR

        params = {}
        if device == "gpu":
            try:
                import onnxruntime as ort

                if "CUDAExecutionProvider" in ort.get_available_providers():
                    params["providers"] = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                else:
                    params = {}
                    device = "cpu"
            except Exception:
                params = {}
                device = "cpu"
        _engine = RapidOCR(**params)
        _engine_device = device
        return _engine


class OCRService:
    """本地 OCR 识别服务，基于 RapidOCR 开源模型。"""

    def __init__(self, device: str = "cpu"):
        self.device = device
        #: 最近一次失败的原因（供上层可观测；成功时置 None）
        self.last_error: Optional[str] = None
        self._warned = False

    def recognize(self, image_path: str) -> str:
        """识别图片中的文字，返回拼接文本。

        :param image_path: 本地图片路径（png/jpg/bmp 等）
        :return: 识别出的文本，每行以换行分隔；失败返回 ""（原因见 last_error）
        """
        if not os.path.exists(image_path):
            self.last_error = "图片不存在"
            return ""
        try:
            engine = _get_engine(self.device)
            result, _ = engine(image_path)
        except Exception as e:
            # **可观测性修复**：旧代码 `except Exception: return ""` 把
            # 依赖缺失（缺 six/yaml/Pillow/onnxruntime）等致命错误吞成空串，
            # 上层只看到「0 字」，无从判断是模型坏了还是图里没字。
            # 这里记录真实异常，并只对「首次」打印一次堆栈避免刷屏。
            self.last_error = f"{type(e).__name__}: {e}"
            if not getattr(self, "_warned", False):
                logger.error("OCR 识别失败（后续同类错误不再重复打印）: %s", self.last_error,
                             exc_info=True)
                self._warned = True
            return ""

        if not result:
            self.last_error = "引擎返回空结果"
            return ""
        lines = []
        for item in result:
            # RapidOCR 返回结构： [box, text, score]
            text = item[1] if len(item) > 1 else ""
            if text and str(text).strip():
                lines.append(str(text).strip())
        self.last_error = None
        return "\n".join(lines)

    def recognize_lines(self, image_path: str) -> List[Dict[str, Any]]:
        """识别图片并返回**逐行**结果（带 bbox 与置信度）。

        为什么要有这个方法（2026-10-20）
        -------------------------------
        :meth:`recognize` 只回文本，把 RapidOCR 的 ``[box, text, score]`` 三元组
        里的**框和分数全丢了**。于是走 rapidocr 后端的扫描件（数学类 PDF 的主路径）
        拿不到任何置信度，下游无法判断「这段 OCR 文本能不能信」——
        而 RapidOCR 在数学公式上恰恰会读错（``x``→``α``、``f(x)``→``fLg(）``）。

        本方法**不改变** :meth:`recognize` 的行为，只是把引擎原始结果原样透出来：
        返回 ``[{"text": str, "box": list|None, "score": float|None}, ...]``。

        失败时返回空列表，原因写进 ``self.last_error``（与 recognize 一致）。
        """
        if not os.path.exists(image_path):
            self.last_error = "图片不存在"
            return []
        try:
            engine = _get_engine(self.device)
            result, _ = engine(image_path)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            if not getattr(self, "_warned", False):
                logger.error("OCR 识别失败（后续同类错误不再重复打印）: %s", self.last_error,
                             exc_info=True)
                self._warned = True
            return []

        if not result:
            self.last_error = "引擎返回空结果"
            return []
        out: List[Dict[str, Any]] = []
        for item in result:
            try:
                text = str(item[1]) if len(item) > 1 else ""
            except Exception:  # noqa: BLE001 - 结构异常就跳过这一行
                continue
            if not text.strip():
                continue
            box = item[0] if len(item) > 0 else None
            score = None
            if len(item) > 2:
                try:
                    score = float(item[2])
                except (TypeError, ValueError):
                    score = None
            out.append({
                "text": text.strip(),
                "box": list(box) if isinstance(box, (list, tuple)) else None,
                "score": score,
            })
        self.last_error = None
        return out

    def recognize_bytes(self, image_bytes: bytes) -> str:
        """识别内存中的图片字节（Base64 解码后）"""
        if not image_bytes:
            return ""
        # 用 mkstemp 先拿到路径并立即关闭 fd，避免 Windows 下
        # NamedTemporaryFile 独占句柄导致后续识别时 Permission denied
        fd, tmp_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            with open(tmp_path, "wb") as f:
                f.write(image_bytes)
            return self.recognize(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def extract_questions(self, text: str) -> List[Dict[str, Any]]:
        """从文本中提取题目结构。

        使用正则匹配常见的题目编号格式，将文本切分为题目列表。
        """
        questions: List[Dict[str, Any]] = []

        # 匹配 "1." "1、" "(1)" "一、" 等题号
        pattern = re.compile(
            r"(?:^|\n)\s*(?:(\d+)[.、)）]\s*|[(（](\d+)[)）]\s*|([一二三四五六七八九十]+)[、.]\s*)"
        )

        matches = list(pattern.finditer(text))
        if not matches:
            # 无法识别题号，整段作为一个题目
            if text.strip():
                questions.append({
                    "index": 1,
                    "content": text.strip(),
                    "options": [],
                    "answer": None,
                })
            return questions

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[start:end].strip()
            if not block:
                continue

            # 提取选项（A. B. C. D.）
            option_pattern = re.compile(r"([A-D])[.、)）]\s*(.+?)(?=[A-D][.、)）]|$)", re.DOTALL)
            option_matches = option_pattern.findall(block)
            options = [f"{letter}. {content.strip()}" for letter, content in option_matches]

            # 去掉选项部分，得到题干
            content = block
            if options:
                content = option_pattern.sub("", block).strip()

            questions.append({
                "index": i + 1,
                "content": content,
                "options": options,
                "answer": None,
            })

        return questions


# ---------------------------------------------------------------------------
# PaddleOCR PP-OCRv5 微服务适配层（V2.0 新增）
# 通过 HTTP 调用独立的 PaddleOCR 微服务，精度高于 RapidOCR
# ---------------------------------------------------------------------------

class PaddleOCRService:
    """PaddleOCR PP-OCRv5 微服务客户端。

    通过 HTTP 调用独立部署的 PaddleOCR 微服务（默认端口8888），
    支持图片和 PDF 识别，返回识别文字和标注图像。
    微服务不可用时自动回退到本地 RapidOCR。
    """

    def __init__(self, service_url: Optional[str] = None, fallback_to_local: bool = True):
        from utils.compute_nodes import ocr_service_url, service_headers
        self.service_url = (service_url or ocr_service_url()).rstrip("/")
        self._headers = service_headers()
        self.fallback_to_local = fallback_to_local
        self._local_service: Optional[OCRService] = None

    def _get_local(self) -> OCRService:
        if self._local_service is None:
            self._local_service = OCRService()
        return self._local_service

    async def health_check(self) -> Dict[str, Any]:
        """检查 PaddleOCR 微服务是否可用。"""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0, headers=self._headers) as client:
                resp = await client.get(f"{self.service_url}/health")
                return resp.json()
        except Exception as e:
            return {"status": "unavailable", "error": str(e)}

    async def recognize_bytes(self, image_bytes: bytes, filename: str = "image.png") -> Dict[str, Any]:
        """识别图片字节，返回完整结果（含文字、时间、标注图像）。"""
        if not image_bytes:
            return {"text": "", "lines": [], "detail_time": 0, "annotated_image": "", "engine": "none", "error": "空文件"}

        try:
            import httpx
            async with httpx.AsyncClient(timeout=120.0, headers=self._headers) as client:
                resp = await client.post(
                    f"{self.service_url}/ocr",
                    files={"file": (filename, image_bytes)},
                )
                resp.raise_for_status()
                data = resp.json()

            if data.get("error"):
                raise RuntimeError(data["error"])

            lines = data.get("result", [])
            text = "\n".join(lines)
            annotated = data.get("image_list", [""])[0] if data.get("image_list") else ""

            return {
                "text": text,
                "lines": lines,
                "detail_time": data.get("detail_time", 0),
                "annotated_image": annotated,
                "engine": "paddleocr",
                "error": None,
            }
        except Exception as e:
            if self.fallback_to_local:
                try:
                    local = self._get_local()
                    text = local.recognize_bytes(image_bytes)
                    lines = text.split("\n") if text else []
                    return {
                        "text": text,
                        "lines": lines,
                        "detail_time": 0,
                        "annotated_image": "",
                        "engine": "rapidocr(fallback)",
                        "error": f"PaddleOCR微服务不可用，已回退本地RapidOCR: {str(e)}",
                    }
                except Exception as e2:
                    return {
                        "text": "", "lines": [], "detail_time": 0,
                        "annotated_image": "", "engine": "none",
                        "error": f"识别失败: {str(e2)}",
                    }
            return {
                "text": "", "lines": [], "detail_time": 0,
                "annotated_image": "", "engine": "none",
                "error": f"PaddleOCR微服务调用失败: {str(e)}",
            }
