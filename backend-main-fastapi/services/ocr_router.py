# -*- coding: utf-8 -*-
"""三层 OCR 统一路由层（集各家所长：chineseocr_lite / backend-ocr-paddle / local-ocr-gpu）。

统一输出协议对齐 chineseocr_lite README 的 CLI JSON 协议：
    {"text": "...", "blocks": [{"text","score","box"}], "elapsed": 秒}

路由策略（默认精度优先，可用性探测 + 快速失败回退）：
    1. local-gpu    —— Intel AIPC 本地 GPU：OpenVINO PP-DocLayoutV3 + PaddleOCR-VL-1.5（run.ps1）
    2. paddleocr    —— 现有 backend-ocr-paddle 微服务（PP-OCRv5，HTTP 8888，复用 ocr_service.PaddleOCRService）
    3. rapidocr     —— 现有本地 RapidOCR（ONNX PP-OCRv4 系 CPU，与 chineseocr_lite 同构的轻量方案）
    4. chineseocr-lite —— 预留适配器：设置环境变量 OCR_LITE_CMD 后启用（如 pip install chineseocr_lite）

纯新增模块，不改动既有 ocr_service.py（红线：外科手术式改动）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class OCRBlock:
    """单个文本块（对齐 chineseocr_lite CLI 协议）。"""
    text: str
    score: float = 0.0
    box: Optional[List[List[float]]] = None

    def to_dict(self) -> dict:
        d: dict = {"text": self.text, "score": round(float(self.score), 4)}
        if self.box:
            d["box"] = self.box
        return d


@dataclass
class OCRResult:
    """统一 OCR 结果。"""
    text: str
    blocks: List[OCRBlock] = field(default_factory=list)
    elapsed: float = 0.0
    engine: str = ""            # 实际引擎名：local-gpu / paddleocr / rapidocr / chineseocr-lite
    backend: str = ""           # 后端标识（用于 manifest 记录）
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "blocks": [b.to_dict() for b in self.blocks],
            "elapsed": round(float(self.elapsed), 3),
            "engine": self.engine,
            "backend": self.backend,
            "error": self.error,
        }


# --------------------------------------------------------------------------- #
# 后端 1：local-ocr-gpu（Intel AIPC 本地 GPU，精度最高）
# --------------------------------------------------------------------------- #
class LocalGPUOCRBackend:
    name = "local-gpu"
    label = "本地 GPU OCR（PP-DocLayoutV3 + PaddleOCR-VL-1.5）"

    def __init__(self, run_ps1: Optional[str] = None, timeout: float = 300.0):
        self.run_ps1 = run_ps1 or os.environ.get(
            "LOCAL_OCR_GPU_RUN_PS1",
            r"C:\Users\33884\AppData\Roaming\Tencent\Marvis\User\oAN1i2T40ogJFVM4CCm9d72iRr_I\skills\market\local-ocr-gpu\scripts\run.ps1",
        )
        self.timeout = timeout

    def available(self) -> bool:
        if not os.path.exists(self.run_ps1):
            return False
        # run.ps1 会做 AIPC 检测（platform.exe --is-aipc）；这里做轻量预检：脚本存在即可路由，
        # 真正失败由 recognize 捕获并回退（避免每次路由都跑平台检测拖慢入库）。
        return True

    def recognize(self, image_path: str) -> OCRResult:
        """调用 run.ps1，stdout 即识别 markdown（client.py 约定：日志写文件，不污染 stdout）。"""
        t0 = time.time()
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", self.run_ps1, image_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
            elapsed = time.time() - t0
            if proc.returncode == 3:
                return OCRResult(text="", engine=self.name, backend=self.name,
                                 elapsed=elapsed, error="模型仍在下载，请先运行 run.ps1 --continue")
            if proc.returncode != 0:
                return OCRResult(text="", engine=self.name, backend=self.name,
                                 elapsed=elapsed, error=f"local-gpu 退出码 {proc.returncode}: {proc.stderr[-300:]}")
            text = (proc.stdout or "").strip()
            return OCRResult(text=text, engine=self.name, backend=self.name,
                             elapsed=elapsed, error=None if text else "未识别到文字")
        except subprocess.TimeoutExpired:
            return OCRResult(text="", engine=self.name, backend=self.name,
                             elapsed=time.time() - t0, error=f"local-gpu 超时（>{self.timeout:.0f}s）")
        except Exception as e:
            return OCRResult(text="", engine=self.name, backend=self.name,
                             elapsed=time.time() - t0, error=f"local-gpu 调用失败: {e}")


# --------------------------------------------------------------------------- #
# 后端 2：backend-ocr-paddle 微服务（PP-OCRv5，HTTP 8888）
# --------------------------------------------------------------------------- #
class PaddleOCRBackend:
    name = "paddleocr"
    label = "PaddleOCR PP-OCRv5 微服务（backend-ocr-paddle）"

    def __init__(self, service_url: Optional[str] = None, timeout: float = 120.0):
        from services.ocr_service import PaddleOCRService

        self._svc = PaddleOCRService(service_url=service_url, fallback_to_local=False)
        self.timeout = timeout

    async def available_async(self) -> bool:
        try:
            info = await self._svc.health_check()
            return info.get("status") in ("ok", "available") or "status" in info
        except Exception:
            return False

    def available(self) -> bool:
        """同步可用性探测（带 3s 超时，路由层调用）。"""
        try:
            import asyncio

            return asyncio.run(self.available_async())
        except Exception:
            return False

    async def recognize_bytes_async(self, image_bytes: bytes, filename: str = "image.png") -> OCRResult:
        t0 = time.time()
        try:
            data = await self._svc.recognize_bytes(image_bytes, filename=filename)
            elapsed = time.time() - t0
            if data.get("error"):
                return OCRResult(text="", engine=self.name, backend=self.name,
                                 elapsed=elapsed, error=str(data["error"]))
            lines = data.get("lines") or []
            text = data.get("text") or ""
            blocks = [OCRBlock(text=ln) for ln in lines if ln and str(ln).strip()]
            return OCRResult(text=text, blocks=blocks, elapsed=elapsed,
                             engine=self.name, backend=self.name, error=None)
        except Exception as e:
            return OCRResult(text="", engine=self.name, backend=self.name,
                             elapsed=time.time() - t0, error=f"paddleocr 调用失败: {e}")

    def recognize(self, image_path: str) -> OCRResult:
        import asyncio

        with open(image_path, "rb") as f:
            data = f.read()
        return asyncio.run(self.recognize_bytes_async(data, filename=os.path.basename(image_path)))


# --------------------------------------------------------------------------- #
# 后端 3：现有本地 RapidOCR（轻量 ONNX CPU，与 chineseocr_lite 同构的落地替代）
# --------------------------------------------------------------------------- #
class RapidOCRBackend:
    name = "rapidocr"
    label = "本地 RapidOCR（轻量 ONNX CPU）"

    def __init__(self):
        from services.ocr_service import OCRService

        self._svc = OCRService(device="cpu")

    def available(self) -> bool:
        try:
            from services.ocr_service import _get_engine  # noqa: F401
        except Exception:
            return False
        return True

    def recognize(self, image_path: str) -> OCRResult:
        t0 = time.time()
        try:
            text = self._svc.recognize(image_path)
            elapsed = time.time() - t0
            return OCRResult(text=text, engine=self.name, backend=self.name,
                             elapsed=elapsed, error=None if text else "未识别到文字")
        except Exception as e:
            return OCRResult(text="", engine=self.name, backend=self.name,
                             elapsed=time.time() - t0, error=f"rapidocr 调用失败: {e}")


# --------------------------------------------------------------------------- #
# 后端 4：chineseocr_lite CLI 适配器（预留，设置 OCR_LITE_CMD 后启用）
# --------------------------------------------------------------------------- #
class ChineseOCRLiteBackend:
    name = "chineseocr-lite"
    label = "chineseocr_lite CLI（ONNX CPU，稳定 JSON）"

    def __init__(self, cmd: Optional[str] = None):
        self.cmd = cmd or os.environ.get("OCR_LITE_CMD", "chineseocr")

    def available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def recognize(self, image_path: str) -> OCRResult:
        t0 = time.time()
        try:
            proc = subprocess.run(
                [self.cmd, image_path, "--output", "-"],
                capture_output=True, text=True, timeout=60.0,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                return OCRResult(text="", engine=self.name, backend=self.name,
                                 elapsed=time.time() - t0, error=proc.stderr[-300:])
            data = json.loads((proc.stdout or "{}").strip())
            blocks = [OCRBlock(text=b.get("text", ""), score=b.get("score", 0.0), box=b.get("box"))
                      for b in data.get("blocks", []) if b.get("text")]
            return OCRResult(text=data.get("text", ""), blocks=blocks,
                             elapsed=data.get("elapsed", time.time() - t0),
                             engine=self.name, backend=self.name, error=None)
        except json.JSONDecodeError as e:
            return OCRResult(text="", engine=self.name, backend=self.name,
                             elapsed=time.time() - t0, error=f"chineseocr-lite JSON 解析失败: {e}")
        except Exception as e:
            return OCRResult(text="", engine=self.name, backend=self.name,
                             elapsed=time.time() - t0, error=f"chineseocr-lite 调用失败: {e}")


# --------------------------------------------------------------------------- #
# 路由层
# --------------------------------------------------------------------------- #
#: 默认候选链（精度优先）。chineseocr-lite 仅当 OCR_LITE_CMD 可执行时插入链尾。
DEFAULT_CHAIN = ["local-gpu", "paddleocr", "rapidocr"]


class OCRRouter:
    """三层 OCR 路由：可用性探测 → 按候选链尝试 → 快速失败回退。"""

    def __init__(self, prefer: str = "auto", chain: Optional[List[str]] = None):
        self.prefer = prefer
        self._chain = chain or DEFAULT_CHAIN
        self._backends: dict = {}
        self._avail_cache: dict = {}
        self._avail_ts: dict = {}
        self._avail_ttl = 30.0

    def _backend(self, name: str):
        if name not in self._backends:
            if name == "local-gpu":
                self._backends[name] = LocalGPUOCRBackend()
            elif name == "paddleocr":
                self._backends[name] = PaddleOCRBackend()
            elif name == "rapidocr":
                self._backends[name] = RapidOCRBackend()
            elif name == "chineseocr-lite":
                self._backends[name] = ChineseOCRLiteBackend()
        return self._backends.get(name)

    def is_available(self, name: str) -> bool:
        """带 TTL 缓存的可用性探测（避免每张图都做 HTTP/CLI 探测）。"""
        now = time.time()
        if name in self._avail_ts and now - self._avail_ts[name] < self._avail_ttl:
            return self._avail_cache.get(name, False)
        backend = self._backend(name)
        try:
            ok = bool(backend.available()) if backend else False
        except Exception:
            ok = False
        self._avail_cache[name] = ok
        self._avail_ts[name] = now
        return ok

    def available_backends(self) -> List[str]:
        chain = self._chain[:]
        if "chineseocr-lite" not in chain and self._backend("chineseocr-lite").available():
            chain.append("chineseocr-lite")
        return [n for n in chain if self.is_available(n)]

    def _ordered_candidates(self) -> List[str]:
        chain = self._chain[:]
        if "chineseocr-lite" not in chain and self._backend("chineseocr-lite").available():
            chain.append("chineseocr-lite")
        if self.prefer and self.prefer != "auto":
            # 显式指定：把指定后端提到最前，仍保留回退链
            if self.prefer in chain:
                chain = [self.prefer] + [n for n in chain if n != self.prefer]
        return chain

    def recognize_file(self, image_path: str) -> OCRResult:
        """识别本地图片/PDF 文件，按候选链自动路由。"""
        for name in self._ordered_candidates():
            if not self.is_available(name):
                continue
            backend = self._backend(name)
            try:
                result = backend.recognize(image_path)
            except Exception as e:
                result = OCRResult(text="", engine=name, backend=name,
                                   elapsed=0.0, error=f"{type(e).__name__}: {e}")
            if result.text:
                result.backend = name
                return result
            # 文本为空 → 视为失败，回退下一后端（快速失败切换）
        return OCRResult(text="", engine="", backend="",
                         error=f"全部 OCR 后端不可用或未识别到文字（候选: {self._ordered_candidates()}）")

    def recognize_bytes(self, image_bytes: bytes, filename: str = "image.png") -> OCRResult:
        """识别内存图片字节（仅支持支持 bytes 的后端：paddleocr）。"""
        for name in self._ordered_candidates():
            if name == "paddleocr":
                backend = self._backend(name)
                import asyncio

                result = asyncio.run(backend.recognize_bytes_async(image_bytes, filename=filename))
                if result.text or result.error:
                    return result
        return OCRResult(text="", engine="", backend="", error="字节识别：无可用后端")

    def status(self) -> dict:
        """路由状态快照（供报告/调试）。"""
        return {
            "prefer": self.prefer,
            "chain": self._ordered_candidates(),
            "available": self.available_backends(),
            "backends": {
                "local-gpu": self._backend("local-gpu").label,
                "paddleocr": self._backend("paddleocr").label,
                "rapidocr": self._backend("rapidocr").label,
                "chineseocr-lite": self._backend("chineseocr-lite").label,
            },
        }


#: 全局路由实例（懒加载单例）
_router: Optional[OCRRouter] = None


def get_ocr_router(prefer: str = "auto") -> OCRRouter:
    global _router
    if _router is None:
        _router = OCRRouter(prefer=prefer)
    return _router


def recognize_file(image_path: str, prefer: str = "auto") -> OCRResult:
    """便捷入口：识别文件。"""
    return get_ocr_router(prefer=prefer).recognize_file(image_path)
