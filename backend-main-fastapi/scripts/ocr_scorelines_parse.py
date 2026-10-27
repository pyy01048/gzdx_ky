# -*- coding: utf-8 -*-
"""OCR 分数线文本结构化解析（第二阶段 v2）。

只接受「6 位专业代码锚点」的行，分数限 250~450（复试线合理区间），
用「变化 = 26线 - 25线」校验三元组。输出 ocr_scorelines_parsed.json。

置信度：
  high —— 变化短语存在且三连校验误差 ≤2
  mid  —— 有分数三连但无变化/无法校验
  low  —— 只有专业锚点无分数
"""
import json
import os
import re

BASE = r'D:\平台\data_sources\kaoyan-zexiao-baodian'
RAW = os.path.join(BASE, 'ocr_scorelines_raw.jsonl')
OUT = os.path.join(BASE, 'ocr_scorelines_parsed.json')

KEYWORD_RE = re.compile(r'分数线|复试线|单科线|录取线')
HEADING_RE = re.compile(r'[一二三四五六七八九十]+\s*[、.]?\s*近?[一二三四五]?年?(?:录取分数线|复试分数线|复试线|分数线)变化情况')
SECTION_END_RE = re.compile(r'[一二三四五六七八九十]+\s*[、.]?\s*(报考建议|目标分数|常见问题|就业分析|复试备考|总结)')
CHANGE_RE = re.compile(r'(上升|上涨|提高|下降|降低|下跌|持平|不变)\s*(\d{1,3})?\s*分?')
# 6 位代码锚点：仅接受学科专业代码（07~15 开头）+ 2 个以上汉字
VALID_CODE_PREFIX = ('07', '08', '09', '10', '11', '12', '13', '14', '15')
CODE_RE = re.compile(r'[（(]?\s*(\d{6})\s*[）)]?\s*([\u4e00-\u9fa5]{2,20}(?:[（(][^)]{0,12}[)）])?[\u4e00-\u9fa5A-Za-z0-9]{0,14})')
NUM_RE = re.compile(r'(2[5-9]\d|3\d{2}|4\d{2}|5\d{2})')
COLLEGE_RE = re.compile(r'([\u4e00-\u9fa5]{2,12}(?:学院|研究院|学部|中心))')


def valid_code(code):
    return code[:2] in VALID_CODE_PREFIX and len(code) == 6


def norm(s):
    return re.sub(r'\s+', '', s or '')


def clean_name(raw):
    name = norm(raw)
    # 去掉方向编号 (01) /（01）及研究方向上残缺片段
    name = re.sub(r'[（(]\d{2}[）)]$', '', name)
    name = re.sub(r'[（(]\d{2}[）)].*$', '', name)
    # 去掉常见杂讯尾缀
    name = re.sub(r'(考研|咨询|交流|群|学长|学姐|老师|微信|QQ|抖音|知乎|B站|复试|拟录取).*$', '', name)
    return name.strip()[:40]


def scoreline_slices(pages):
    """返回分数线标题之后的文本切片列表（到下一章节标题前）。"""
    slices = []
    for rec in pages:
        t = rec.get('text', '')
        for hm in HEADING_RE.finditer(t):
            start = hm.end()
            em = SECTION_END_RE.search(t, start)
            end = em.start() if em else len(t)
            slice_text = t[start:end]
            if slice_text.strip():
                slices.append(slice_text)
    return slices


def split_lines_with_anchors(text):
    """按代码锚点切分，每段边界取相邻锚点中点，避免串行。"""
    segs = [(m.start(), m.group(1), m.group(2)) for m in CODE_RE.finditer(text)]
    segs = [(pos, code, raw) for pos, code, raw in segs if valid_code(code)]
    if not segs:
        return []
    lines = []
    for i, (pos, code, raw_name) in enumerate(segs):
        seg_start = (segs[i - 1][0] + pos) // 2 if i > 0 else max(0, pos - 60)
        seg_end = (pos + segs[i + 1][0]) // 2 if i + 1 < len(segs) else len(text)
        segment = text[seg_start:seg_end]
        lines.append((code, clean_name(raw_name), segment))
    return lines


def find_change(segment):
    best = None
    for m in CHANGE_RE.finditer(segment):
        if best is None or m.start() < best[0]:
            best = (m.start(), m.group(1), m.group(2))
    return best


def find_triple(segment, change):
    nums = [int(m.group(1)) for m in NUM_RE.finditer(segment)]
    if len(nums) < 3:
        return None
    TOL = 5  # OCR 数字误差容差
    candidates = []
    for i in range(len(nums) - 2):
        t = tuple(nums[i:i + 3])
        if change:
            cdir, cn = change[1], change[2]
            if cdir in ('上升', '上涨', '提高'):
                err = abs((t[2] - t[1]) - int(cn)) if cn else abs(t[2] - t[1])
            elif cdir in ('下降', '降低', '下跌'):
                err = abs((t[1] - t[2]) - int(cn)) if cn else abs(t[1] - t[2])
            else:
                err = abs(t[2] - t[1])
            if err <= TOL:
                candidates.append((err, t))
        else:
            candidates.append((1000, t))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def parse_school(recs):
    pages = [r for r in recs if KEYWORD_RE.search(r.get('text', ''))]
    if not pages:
        return []
    slices = scoreline_slices(pages)
    if not slices:
        return []
    rows = []
    seen_rows = set()

    for text in slices:
        anchors = [(m.start(), m.group(1), m.group(2))
                   for m in CODE_RE.finditer(text) if valid_code(m.group(1))]
        changes = [(m.start(), m.group(1), m.group(2) or '0')
                   for m in CHANGE_RE.finditer(text)]

        # 1) 以变化短语为中心，找满足差值的分数三连，并关联最近代码锚点
        for cpos, cdir, cn in changes:
            if cdir in ('持平', '不变'):
                cn = '0'
            # 最近代码锚点（±120 字符内）
            nearest = None
            for apos, code, raw_name in anchors:
                if abs(apos - cpos) <= 120:
                    if nearest is None or abs(apos - cpos) < abs(nearest[0] - cpos):
                        nearest = (apos, code, raw_name)
            if nearest is None:
                continue
            apos, code, raw_name = nearest
            major_name = clean_name(raw_name)

            # 变化短语邻域内的数字
            lo = max(0, cpos - 70)
            hi = min(len(text), cpos + 70)
            nums = [int(m.group(1)) for m in NUM_RE.finditer(text, lo, hi)]
            best = None
            for i in range(len(nums) - 2):
                t = tuple(nums[i:i + 3])
                if cdir in ('上升', '上涨', '提高'):
                    err = abs((t[2] - t[1]) - int(cn))
                elif cdir in ('下降', '降低', '下跌'):
                    err = abs((t[1] - t[2]) - int(cn))
                else:
                    err = abs(t[2] - t[1])
                if err <= 5:
                    if best is None or err < best[0]:
                        best = (err, t)
            if best is None:
                continue
            y2024, y2025, y2026 = best[1]
            college = None
            cm = COLLEGE_RE.search(text, max(0, apos - 120), apos + 120)
            if cm:
                college = cm.group(1)
            key = (code, major_name, y2024, y2025, y2026)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append({
                'school': recs[0]['school'],
                'major_code': code,
                'major_name': major_name,
                'y2024': y2024,
                'y2025': y2025,
                'y2026': y2026,
                'change': f'{cdir}{cn}分',
                'college': college,
                'confidence': 'high',
                'source_pages': [r['page'] for r in pages],
            })

        # 2) 兜底：有代码锚点但未匹配到变化短语的，取锚点后紧邻三连（mid）
        for apos, code, raw_name in anchors:
            major_name = clean_name(raw_name)
            if any(r['major_code'] == code and r['major_name'] == major_name for r in rows):
                continue
            # 锚点后 90 字符内取紧邻三连
            nums = [int(m.group(1)) for m in NUM_RE.finditer(text, apos, min(len(text), apos + 90))]
            if len(nums) < 3:
                continue
            y2024, y2025, y2026 = nums[0], nums[1], nums[2]
            college = None
            cm = COLLEGE_RE.search(text, max(0, apos - 120), apos + 120)
            if cm:
                college = cm.group(1)
            key = (code, major_name, y2024, y2025, y2026)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append({
                'school': recs[0]['school'],
                'major_code': code,
                'major_name': major_name,
                'y2024': y2024,
                'y2025': y2025,
                'y2026': y2026,
                'change': None,
                'college': college,
                'confidence': 'mid',
                'source_pages': [r['page'] for r in pages],
            })
    return rows


def main():
    groups = {}
    for line in open(RAW, encoding='utf-8'):
        rec = json.loads(line)
        groups.setdefault(rec['school'], []).append(rec)

    all_rows = []
    for school, recs in groups.items():
        all_rows.extend(parse_school(recs))

    # 去重：同校同代码同名同分数
    seen = set()
    unique = []
    for r in all_rows:
        key = (r['school'], r['major_code'], norm(r['major_name']),
               r['y2024'], r['y2025'], r['y2026'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(unique, f, ensure_ascii=False, indent=1)

    from collections import Counter
    conf = Counter(r['confidence'] for r in unique)
    print(f'解析完成：{len(groups)} 校 -> {len(unique)} 行')
    print('confidence:', dict(conf))
    print('\nhigh 示例：')
    shown = 0
    for r in unique:
        if r['confidence'] == 'high':
            print(' ', r['school'], r['major_code'], r['major_name'], r['y2024'], r['y2025'], r['y2026'], r['change'])
            shown += 1
            if shown >= 15:
                break
    return 0


if __name__ == '__main__':
    main()