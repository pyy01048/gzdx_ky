# PaddleOCR PP-OCRv5 文字识别微服务

基于 FastAPI 集成 PaddleOCR，使用 2025年5月发布的 PP-OCRv5 模型，支持图片和 PDF 文件的高精度文字识别。

## 特性

- ✅ PP-OCRv5 最新模型，识别精度和速度均有提升
- ✅ 支持中英文混合识别
- ✅ 支持图片格式：JPEG、PNG、BMP、WEBP、TIFF
- ✅ 支持 PDF 文件（逐页识别，最多10页）
- ✅ 返回识别文字 + 标注图像（识别框可视化）
- ✅ 批量识别（最多10张图片）
- ✅ 独立微服务，可单独部署和扩展
- ✅ REST API 接口，自动生成 Swagger 文档

## 快速启动

### Windows
双击 `start.bat`，脚本会自动安装依赖并启动服务。

### 手动启动
```bash
# 1. 安装 PaddlePaddle（CPU版本，约500MB）
pip install paddlepaddle

# 2. 安装其他依赖
pip install -r requirements.txt

# 3. 启动服务
python main.py
```

启动后访问：
- 服务地址：http://127.0.0.1:8888
- API文档：http://127.0.0.1:8888/docs
- 健康检查：http://127.0.0.1:8888/health

## API 接口

### 1. 单文件识别
```
POST /ocr
Content-Type: multipart/form-data
参数：file (图片或PDF文件)

返回：
{
  "result": ["识别文字行1", "识别文字行2", ...],
  "detail_time": 1.234,
  "image_list": ["data:image/png;base64,..."],
  "error": null
}
```

### 2. 批量识别
```
POST /ocr/batch
Content-Type: multipart/form-data
参数：files (多个图片文件，最多10个)
```

### 3. 健康检查
```
GET /health
返回：{"status": "ok", "service": "paddleocr-service", "version": "2.0.0", "model": "PP-OCRv5"}
```

### 4. OCR状态
```
GET /ocr/status
返回：{"loaded": true, "loading": false, "model": "PP-OCRv5", "lang": "ch"}
```

## 与主服务集成

主服务（backend-main-fastapi）通过 HTTP 调用本 OCR 微服务：

```python
import httpx

async def ocr_recognize(file_content: bytes, filename: str) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "http://127.0.0.1:8888/ocr",
            files={"file": (filename, file_content)},
        )
        return resp.json()
```

## GPU 加速（可选）

如有 NVIDIA 显卡，可安装 GPU 版本提升识别速度：
```bash
# 卸载CPU版本
pip uninstall paddlepaddle

# 安装GPU版本（根据CUDA版本选择）
pip install paddlepaddle-gpu
```

然后修改 `main.py` 中的 `use_gpu=False` 为 `use_gpu=True`。

## 注意事项

1. 首次启动会自动下载 PP-OCRv5 模型文件（约 10-20MB），请确保网络畅通
2. PaddlePaddle 安装包较大（CPU版约500MB），首次安装较慢
3. PDF 识别最多处理10页，避免大文件超时
4. 服务默认监听 127.0.0.1，如需局域网访问，修改 main.py 中的 host 为 0.0.0.0

## 参考项目

- [PaddleOCRFastAPI2](https://github.com/tgtgwin/PaddleOCRFastAPI2) - 原始参考项目
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) - 百度飞桨OCR工具库
