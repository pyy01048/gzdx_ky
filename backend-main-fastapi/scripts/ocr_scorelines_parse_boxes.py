# -*- coding: utf-8 -*-
"""OCR 分数线表格解析 v3（基于文本框坐标）。

支持：
- 三连（24/25/26）与二连（24/25，复旦等近两年表）
- 6 位代码锚点 + 「电子信息-xx」名称锚点
- 名称/数值跨视觉行时自动合并修复
输出 ocr_scorelines_parsed_boxes.json
"""
import json
import os
import re

BASE = r'D:\平台\data_sources\kaoyan-zexiao-baodian'
RAW = os.path.join(BASE, 'ocr_scorelines_raw_boxes.jsonl')
OUT = os.path.join(BASE, 'ocr_scorelines_parsed_boxes.json')

VALID_CODE_PREFIX = ('07', '08', '09', '10', '11', '12', '13', '14', '15')
CODE_RE = re.compile(r'[（(]?\s*(\d{6})\s*[）)]?\s*(?:[（(]\d{1,2}[）)])?\s*([\u4e00-\u9fa5]{2,24})')
CHANGE_RE = re.compile(r'(上升|上涨|提高|下降|降低|下跌|持平|不变)\s*(\d{1,3})?\s*分?')
NUM_RE = re.compile(r'(?<!\d)(2[5-9]\d|3\d{2}|4\d{2})(?!\d)')
COLLEGE_RE = re.compile(r'([\u4e00-\u9fa5]{2,12}(?:学院|研究院|学部|中心))')
NAME_RE = re.compile(r'电子信息-([\u4e00-\u9fa5A-Za-z0-9（）()\-]{2,24})')
BAD_NAME_RE = re.compile(
    r'届毕业生|就业情况|重点单位|分数线上涨|分数线下|招生人数|录取中位数|平均数|'
    r'建议|一些|全国|方向也|福利局|暴涨|暴跌|学长|学姐|华哥|东坡哥|公众号|'
    r'知乎|B站|抖音|小红书|微信|QQ|群|交流|咨询')

TOL = 5  # 变化差值 OCR 误差容差


def plausible_name(name):
    if not name or len(name) < 3:
        return False
    if BAD_NAME_RE.search(name):
        return False
    return True


def norm(s):
    return re.sub(r'\s+', '', s or '')


def clean_name(raw, strip_prefix=True):
    name = norm(raw)
    if strip_prefix:
        name = re.sub(r'^电子信息-', '', name)
    name = re.sub(r'[（(]\d{2,3}[）)].*$', '', name)
    name = re.sub(r'(考研|咨询|交流|群|学长|学姐|老师|微信|QQ|抖音|知乎|B站|复试|拟录取|分析|福利局|一些|全国|建议|方向也|中位数|平均数|今年).*$', '', name)
    name = re.sub(r'^方向|方向$', '', name)
    return name.strip()[:36]


def group_rows(items):
    """按 y 中心聚类成行（容差 24px）。"""
    rows = []
    cur = []
    cur_mean = 0.0
    for it in items:
        yc = it['ycenter']
        if not cur or abs(yc - cur_mean) <= 24:
            cur.append(it)
        else:
            rows.append(cur)
            cur = [it]
        cur_mean = sum(i['ycenter'] for i in cur) / len(cur)
    if cur:
        rows.append(cur)
    return rows


def row_text(row):
    row.sort(key=lambda it: it['xleft'])
    return ' | '.join(it['text'] for it in row)


def repair_rows(rows):
    """如果一行只有名称、下一行只有数值，则合并。"""
    out = []
    i = 0
    while i < len(rows):
        cur = rows[i]
        if i + 1 < len(rows):
            t_cur = row_text(cur)
            t_next = row_text(rows[i + 1])
            has_num_cur = bool(NUM_RE.search(t_cur))
            has_num_next = bool(NUM_RE.search(t_next))
            has_name_cur = bool(CODE_RE.search(t_cur) or NAME_RE.search(t_cur))
            has_name_next = bool(CODE_RE.search(t_next) or NAME_RE.search(t_next))
            if has_name_cur and not has_num_cur and not has_name_next and has_num_next:
                merged = cur + rows[i + 1]
                out.append(merged)
                i += 2
                continue
        out.append(cur)
        i += 1
    return out


def parse_row(text):
    """解析一行：返回 dict 或 None。"""
    m = CODE_RE.search(text)
    if m:
        code = m.group(1)
        if code[:2] not in VALID_CODE_PREFIX:
            return None
        name = clean_name(m.group(2))
        if not plausible_name(name):
            return None
        major_code = code
    else:
        nm = NAME_RE.search(text)
        if not nm:
            return None
        name = clean_name(nm.group(1))
        if not plausible_name(name):
            return None
        major_code = None

    nums = [int(x) for x in NUM_RE.findall(text)]
    cm = CHANGE_RE.search(text)
    change = None
    if cm:
        cdir = cm.group(1)
        cn = cm.group(2) or '0'
        if cdir in ('持平', '不变'):
            cn = '0'
        change = (cdir, cn)

    triple = None
    confidence = 'low'
    if len(nums) >= 3:
        candidates = []
        for i in range(len(nums) - 2):
            t = tuple(nums[i:i + 3])
            err = None
            if change:
                cdir, cn = change
                if cdir in ('上升', '上涨', '提高'):
                    err = abs((t[2] - t[1]) - int(cn))
                elif cdir in ('下降', '降低', '下跌'):
                    err = abs((t[1] - t[2]) - int(cn))
                else:
                    err = abs(t[2] - t[1])
            if err is not None and err <= TOL:
                candidates.append((err, t))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            triple = candidates[0][1]
            confidence = 'high'
        elif change is None:
            # 无变化列，取紧邻三连
            triple = tuple(nums[0:3])
            confidence = 'mid'
    elif len(nums) == 2:
        # 近两年表
        t = (nums[0], nums[1])
        err = None
        if change:
            cdir, cn = change
            if cdir in ('上升', '上涨', '提高'):
                err = abs((t[1] - t[0]) - int(cn))
            elif cdir in ('下降', '降低', '下跌'):
                err = abs((t[0] - t[1]) - int(cn))
            else:
                err = abs(t[1] - t[0])
        if err is not None and err <= TOL:
            triple = (t[0], t[1], None)
            confidence = 'high'
        elif change is None:
            triple = (t[0], t[1], None)
            confidence = 'mid'

    college = None
    cm2 = COLLEGE_RE.search(text)
    if cm2:
        college = cm2.group(1)

    return {
        'major_code': major_code,
        'major_name': name,
        'y2024': triple[0] if triple else None,
        'y2025': triple[1] if triple else None,
        'y2026': triple[2] if triple else None,
        'change': f'{change[0]}{change[1]}分' if change else None,
        'college': college,
        'confidence': confidence,
    }


def main():
    schools = {}
    for line in open(RAW, encoding='utf-8'):
        rec = json.loads(line)
        schools.setdefault(rec['school'], []).append(rec)

    all_rows = []
    for school, recs in schools.items():
        items = []
        for rec in recs:
            for it in rec.get('items', []):
                box = it.get('box') or []
                if len(box) >= 4:
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    items.append({
                        'text': it['text'],
                        'xleft': min(xs),
                        'ycenter': (min(ys) + max(ys)) / 2.0,
                        'score': it.get('score'),
                    })
        items.sort(key=lambda it: (it['ycenter'], it['xleft']))
        raw_rows = group_rows(items)
        raw_rows = repair_rows(raw_rows)
        for row in raw_rows:
            text = row_text(row)
            parsed = parse_row(text)
            if parsed and parsed['major_name'] and (parsed['major_code'] is not None or parsed['y2024'] is not None):
                parsed['school'] = school
                parsed['pages'] = sorted({r['page'] for r in recs})
                all_rows.append(parsed)

    # 去重
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
    print(f'解析完成：{len(schools)} 校 -> {len(unique)} 行')
    print('confidence:', dict(conf))
    print('\nhigh 示例：')
    shown = 0
    for r in unique:
        if r['confidence'] == 'high':
            print(' ', r['school'], r['major_code'], r['major_name'], r['y2024'], r['y2025'], r['y2026'], r['change'])
            shown += 1
            if shown >= 25:
                break
    return 0


if __name__ == '__main__':
    main()