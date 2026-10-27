# -*- coding: utf-8 -*-
"""图片型分数线表格 OCR 批量抽取 v2（带文本框坐标）。

对 parsed_schools.json 中 scorelines 为空的学校：
- 找「分数线变化」标题所在页（或「报考建议」页及前一页）
- 渲染候选页（200dpi）
- 用 OCRService.recognize_lines 获取 [{text, box, score}]（bbox 用于表格行重建）
- 结果写入 ocr_scorelines_raw_boxes.jsonl
  {"school": ..., "page": ..., "items": [{"text","box","score"}], "text": "..."}

用法：.venv\\Scripts\\python.exe -X utf8 scripts/ocr_scorelines_extract.py [学校名...]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz  # noqa: E402
from services.ocr_service import OCRService  # noqa: E402

BASE = r'D:\平台\data_sources\kaoyan-zexiao-baodian'
PARSED = os.path.join(BASE, 'parsed_schools.json')
PAGES = os.path.join(BASE, 'text_pages.jsonl')
OUT = os.path.join(BASE, 'ocr_scorelines_raw_boxes.jsonl')
PDF = r'D:\下载\QQ\【100%更新】27考研电子通信考研择校宝典最新版（全网最快最全发布！240+.pdf'

PAGE_TEXTS = {}


def load_pages():
    global PAGE_TEXTS
    if PAGE_TEXTS:
        return PAGE_TEXTS
    with open(PAGES, encoding='utf-8') as f:
        for line in f:
            o = json.loads(line)
            PAGE_TEXTS[o['page']] = o['text']
    return PAGE_TEXTS


def find_scoreline_pages(school, start, end):
    pages = load_pages()
    candidates = []
    # 1) 文本层中出现分数线关键词的页
    for p in range(start, min(end, 2600)):
        t = pages.get(p, '')
        if any(k in t for k in ('录取分数线', '复试分数线', '分数线变化', '复试线变化', '年复试线', '单科线')):
            candidates.append(p)
    # 2) 「报考建议」所在页及其前一页（分数线图片通常在建议之前）
    for p in range(start, min(end, 2600)):
        if '报考建议' in pages.get(p, ''):
            candidates.append(p)
            if p - 1 >= start:
                candidates.append(p - 1)
    return sorted(set(candidates))


def main():
    data = json.load(open(PARSED, encoding='utf-8'))
    targets = sys.argv[1:]
    schools = [s for s in data if not s.get('scorelines')]
    if targets:
        schools = [s for s in schools if s['school'] in targets]
    print(f'待 OCR 学校: {len(schools)}', flush=True)

    os.makedirs(BASE, exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding='utf-8'):
            try:
                o = json.loads(line)
                done.add((o['school'], o['page']))
            except Exception:
                pass
    print(f'已完成页: {len(done)}，跳过', flush=True)

    svc = OCRService(device='cpu')
    doc = fitz.open(PDF)
    fout = open(OUT, 'a', encoding='utf-8')
    processed_schools = 0
    for i, s in enumerate(data):
        if s not in schools:
            continue
        school = s['school']
        start = s['pages'][0]
        idx = data.index(s)
        end = data[idx + 1]['pages'][0] if idx + 1 < len(data) else 2600
        pages = find_scoreline_pages(school, start, end)
        if not pages:
            print(f'[skip] {school}: 未定位分数线页 (range {start}-{end})', flush=True)
            continue
        for pno in pages:
            if (school, pno) in done:
                continue
            try:
                pix = doc[pno - 1].get_pixmap(dpi=200)
                tmp = os.path.join(BASE, f'_ocr_tmp_{pno}.png')
                pix.save(tmp)
                lines = svc.recognize_lines(tmp)
                os.remove(tmp)
                items = []
                text = []
                for it in lines:
                    items.append({'text': it['text'], 'box': it.get('box'), 'score': it.get('score')})
                    text.append(it['text'])
                rec = {
                    'school': school,
                    'page': pno,
                    'items': items,
                    'text': '\n'.join(text),
                }
                fout.write(json.dumps(rec, ensure_ascii=False) + '\n')
                fout.flush()
                done.add((school, pno))
                print(f'[ok] {school} p{pno} blocks={len(items)}', flush=True)
            except Exception as e:  # noqa: BLE001
                print(f'[err] {school} p{pno}: {e}', flush=True)
        processed_schools += 1
        if processed_schools % 10 == 0:
            print(f'--- 进度 {processed_schools}/{len(schools)} ---', flush=True)
    doc.close()
    fout.close()
    print('OCR 抽取完成', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())