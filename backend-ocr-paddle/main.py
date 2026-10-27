# -*- coding: utf-8 -*-
"""
PaddleOCR PP-OCRv5 独立微服务
基于 FastAPI 集成 PaddleOCR，支持图片和 PDF 文件文字识别
参考项目：https://github.com/tgtgwin/PaddleOCRFastAPI2
"""

import io
import os
import time
import base64
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 全局 OCR 实例（懒加载）
_ocr = None
_ocr_loading = False

app = FastAPI(
    title="PaddleOCR 文字识别服务",
    description="基于 PP-OCRv5 的高精度文字识别微服务，支持图片和 PDF",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 主后端经隧道调用：设了 COMPUTE_SERVICE_TOKEN 就要求 X-Service-Token 匹配（/health 留给探活）
_SERVICE_TOKEN = os.getenv("COMPUTE_SERVICE_TOKEN", "").strip()


@app.middleware("http")
async def _require_service_token(request, call_next):
    if _SERVICE_TOKEN and request.url.path != "/health":
        import hmac
        from fastapi.responses import JSONResponse
        if not hmac.compare_digest(request.headers.get("x-service-token", ""), _SERVICE_TOKEN):
            return JSONResponse({"detail": "invalid service token"}, status_code=401)
    return await call_next(request)


class OCRResult(BaseModel):
    result: List[str] = []
    detail_time: float = 0.0
    image_list: List[str] = []
    error: Optional[str] = None


def get_ocr():
    """获取或初始化 PaddleOCR 实例（懒加载，首次调用较慢）。"""
    global _ocr, _ocr_loading
    if _ocr is not None:
        return _ocr
    if _ocr_loading:
        raise HTTPException(status_code=503, detail="OCR 模型正在加载中，请稍后重试")
    _ocr_loading = True
    try:
        from paddleocr import PaddleOCR
        # PP-OCRv5 模型配置
        _ocr = PaddleOCR(
            use_angle_cls=True,
            lang="ch",
            use_gpu=False,  # 默认CPU，有GPU可改为True
            show_log=False,
        )
        return _ocr
    except ImportError:
        _ocr_loading = False
        raise HTTPException(
            status_code=500,
            detail="PaddleOCR 未安装，请执行: pip install paddlepaddle paddleocr"
        )
    except Exception as e:
        _ocr_loading = False
        raise HTTPException(status_code=500, detail=f"OCR 模型加载失败: {str(e)}")


def image_to_base64(image) -> str:
    """将 PIL Image 或 numpy 数组转为 base64 字符串。"""
    try:
        from PIL import Image
        import numpy as np
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    except Exception:
        return ""


def process_image(file_content: bytes, filename: str) -> OCRResult:
    """处理单张图片的 OCR 识别。"""
    start_time = time.time()
    ocr = get_ocr()

    try:
        # 读取图片
        from PIL import Image
        import numpy as np
        image = Image.open(io.BytesIO(file_content))
        image_np = np.array(image)

        # PaddleOCR 识别
        result = ocr.ocr(image_np, cls=True)

        # 解析识别结果
        texts = []
        if result and result[0]:
            for line in result[0]:
                if line and len(line) >= 2:
                    text = line[1][0] if line[1] else ""
                    confidence = line[1][1] if line[1] and len(line[1]) > 1 else 0
                    if text:
                        texts.append(text)

        # 生成标注图像（在原图上绘制识别框）
        annotated_base64 = ""
        try:
            from PIL import ImageDraw
            annotated = image.copy()
            draw = ImageDraw.Draw(annotated)
            if result and result[0]:
                for line in result[0]:
                    if line and line[0]:
                        box = line[0]
                        # 绘制四边形框
                        points = [(int(p[0]), int(p[1])) for p in box]
                        for i in range(len(points)):
                            draw.line([points[i], points[(i + 1) % len(points)]], fill="red", width=2)
            annotated_base64 = image_to_base64(annotated)
        except Exception:
            pass

        elapsed = round(time.time() - start_time, 3)
        return OCRResult(
            result=texts,
            detail_time=elapsed,
            image_list=[annotated_base64] if annotated_base64 else [],
        )
    except Exception as e:
        elapsed = round(time.time() - start_time, 3)
        return OCRResult(
            result=[],
            detail_time=elapsed,
            error=f"图片处理失败: {str(e)}",
        )


def process_pdf(file_content: bytes, filename: str) -> OCRResult:
    """处理 PDF 文件的 OCR 识别（逐页识别）。"""
    start_time = time.time()
    ocr = get_ocr()

    try:
        import fitz  # PyMuPDF
        from PIL import Image
        import numpy as np

        doc = fitz.open(stream=file_content, filetype="pdf")
        all_texts = []
        all_images = []

        for page_num in range(min(len(doc), 10)):  # 最多处理10页，避免超时
            page = doc[page_num]
            # 将 PDF 页面渲染为图片
            pix = page.get_pixmap(dpi=200)
            image_data = pix.tobytes("png")
            image = Image.open(io.BytesIO(image_data))
            image_np = np.array(image)

            # OCR 识别
            result = ocr.ocr(image_np, cls=True)
            page_texts = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        text = line[1][0] if line[1] else ""
                        if text:
                            page_texts.append(text)
            all_texts.extend(page_texts)

            # 生成标注图像
            try:
                annotated = image.copy()
                from PIL import ImageDraw
                draw = ImageDraw.Draw(annotated)
                if result and result[0]:
                    for line in result[0]:
                        if line and line[0]:
                            box = line[0]
                            points = [(int(p[0]), int(p[1])) for p in box]
                            for i in range(len(points)):
                                draw.line([points[i], points[(i + 1) % len(points)]], fill="red", width=2)
                all_images.append(image_to_base64(annotated))
            except Exception:
                pass

        doc.close()
        elapsed = round(time.time() - start_time, 3)
        return OCRResult(
            result=all_texts,
            detail_time=elapsed,
            image_list=all_images,
        )
    except ImportError:
        elapsed = round(time.time() - start_time, 3)
        return OCRResult(
            result=[],
            detail_time=elapsed,
            error="PDF 处理需要 PyMuPDF，请执行: pip install pymupdf",
        )
    except Exception as e:
        elapsed = round(time.time() - start_time, 3)
        return OCRResult(
            result=[],
            detail_time=elapsed,
            error=f"PDF 处理失败: {str(e)}",
        )


@app.get("/health")
async def health_check():
    """健康检查接口。"""
    return {
        "status": "ok",
        "service": "paddleocr-service",
        "version": "2.0.0",
        "model": "PP-OCRv5",
        "ocr_loaded": _ocr is not None,
    }


@app.get("/ocr/status")
async def ocr_status():
    """OCR 模型加载状态。"""
    return {
        "loaded": _ocr is not None,
        "loading": _ocr_loading,
        "model": "PP-OCRv5",
        "lang": "ch",
    }


@app.post("/ocr", response_model=OCRResult)
async def ocr_recognize(file: UploadFile = File(...)):
    """
    OCR 文字识别接口

    - 支持图片格式：JPEG、PNG、BMP、WEBP 等
    - 支持 PDF 文件（逐页识别，最多10页）
    - 返回识别文字列表、处理时间、标注图像 base64
    """
    if not file:
        raise HTTPException(status_code=400, detail="未上传文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    filename = file.filename or ""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    # PDF 文件处理
    if ext == "pdf":
        return process_pdf(content, filename)

    # 图片文件处理
    image_exts = ["jpg", "jpeg", "png", "bmp", "webp", "tiff", "gif"]
    if ext in image_exts or ext == "":
        return process_image(content, filename)

    raise HTTPException(status_code=400, detail=f"不支持的文件类型: .{ext}")


@app.post("/ocr/batch")
async def ocr_batch(files: List[UploadFile] = File(...)):
    """批量 OCR 识别（最多10张图片）。"""
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="批量识别最多支持10个文件")

    results = []
    for file in files:
        content = await file.read()
        filename = file.filename or ""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext == "pdf":
            result = process_pdf(content, filename)
        else:
            result = process_image(content, filename)
        results.append({
            "filename": filename,
            "result": result.result,
            "detail_time": result.detail_time,
            "error": result.error,
        })

    return {"total": len(results), "results": results}


if __name__ == "__main__":
    print("=" * 60)
    print("  PaddleOCR PP-OCRv5 文字识别服务")
    host = os.getenv("SERVICE_HOST", "127.0.0.1")  # 云端经 Tailscale 调用时设为本机 tailscale IP，勿用 0.0.0.0
    port = int(os.getenv("SERVICE_PORT", "8888"))
    print(f"  接口地址: http://{host}:{port}")
    print(f"  文档地址: http://{host}:{port}/docs")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port, reload=False)
