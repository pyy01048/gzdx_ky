# -*- coding: utf-8 -*-
"""测试文档152 OCR 前几页，估算全量耗时。"""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

p = r'D:/平台/knowledge_base/模拟电子技术/教材/【电子技术基础-模拟部分】康华光 第6版.pdf'

import pypdfium2 as pdfium
from services.ocr_service import OCRService, _reserve_project_utils

_reserve_project_utils()
ocr = OCRService(device="cpu")
t0 = time.time()
doc = pdfium.PdfDocument(p)
print('总页数:', len(doc))
for i in range(3):
    t1 = time.time()
    page = doc[i]
    bitmap = page.render(scale=200/72.0)
    img = bitmap.to_pil()
    fd, tmp = tempfile.mkstemp(suffix='.png')
    os.close(fd)
    img.save(tmp)
    text = ocr.recognize(tmp)
    os.remove(tmp)
    page.close()
    print(f'第{i+1}页: {len(text)}字, 耗时 {time.time()-t1:.1f}s')
    print('  文本预览:', text[:100].replace(chr(10), ' | '))
doc.close()
print(f'总耗时(3页): {time.time()-t0:.1f}s, 预估全量599页: {(time.time()-t0)/3*599/60:.1f}分钟')
