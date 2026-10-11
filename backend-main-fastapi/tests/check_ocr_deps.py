# -*- coding: utf-8 -*-
"""检查扫描版真题 OCR 链路依赖是否齐备。"""
import importlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

DEPS = [
    ("pypdfium2", "PDF 逐页渲染（扫描件转图）", True),
    ("rapidocr_onnxruntime", "本地 OCR 引擎（PP-OCRv4 ONNX）", True),
    ("onnxruntime", "OCR 推理后端", True),
    ("pypdf", "PDF 文本层提取（引擎1）", False),
    ("pdfplumber", "PDF 文本层提取（引擎2）", False),
    ("PIL", "图像处理", True),
    ("numpy", "向量计算", False),
    ("jieba", "中文分词（FTS5 检索）", False),
]

ok = True
for mod, desc, required in DEPS:
    try:
        m = importlib.import_module(mod)
        print(f"  [OK]   {mod:<24} {getattr(m, '__version__', '')}  — {desc}")
    except Exception as e:
        tag = "FAIL" if required else "warn"
        if required:
            ok = False
        print(f"  [{tag}] {mod:<24} {type(e).__name__}  — {desc}")

print()
print("OCR 链路" + ("依赖齐备 ✅" if ok else "缺少必需依赖 ❌"))
sys.exit(0 if ok else 1)
