# -*- coding: utf-8 -*-
"""《27考研电子通信考研择校宝典》全量文本抽取。

PDF：D:\\下载\\QQ\\【100%更新】27考研电子通信考研择校宝典最新版（全网最快最全发布！240+.pdf
（2491 页，191MB，绝大多数页有文字层）
输出：D:\\平台\\data_sources\\kaoyan-zexiao-baodian\\text_pages.jsonl
每行：{"page": 1, "text": "..."}（page 从 1 开始，与 PDF 页码一致）

用法：python -X utf8 scripts/extract_zexiao_baodian_text.py
"""
import json
import os
import sys
import time

import pdfplumber

SRC = r'D:\下载\QQ\【100%更新】27考研电子通信考研择校宝典最新版（全网最快最全发布！240+.pdf'
OUT_DIR = r'D:\平台\data_sources\kaoyan-zexiao-baodian'
OUT = os.path.join(OUT_DIR, 'text_pages.jsonl')


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    pdf = pdfplumber.open(SRC)
    total = len(pdf.pages)
    print(f'total pages: {total}', flush=True)
    start = time.time()
    with open(OUT, 'w', encoding='utf-8') as fh:
        for i, page in enumerate(pdf.pages):
            try:
                text = page.extract_text() or ''
            except Exception as exc:  # noqa: BLE001
                text = ''
                print(f'[warn] page {i+1} extract failed: {exc}', flush=True)
            fh.write(json.dumps({'page': i + 1, 'text': text}, ensure_ascii=False) + '\n')
            if (i + 1) % 100 == 0:
                elapsed = time.time() - start
                print(f'[{i+1}/{total}] {elapsed:.1f}s', flush=True)
    pdf.close()
    print(f'done, wrote {OUT} ({os.path.getsize(OUT)} bytes)', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())