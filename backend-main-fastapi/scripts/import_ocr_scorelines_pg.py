# -*- coding: utf-8 -*-
"""OCR 识别的图片型复试线入库（幂等，v2）。

读取 ocr_scorelines_parsed_boxes.json：
- 导入 high 行（有「变化」校验）全部；
- 仅当学校没有任何 high 行时，导入该学校 mid 行（备注「未校验」）
- 专业匹配：先按 (校, 代码) 用库内规范名，找不到再按 (校, 名称)；
  均无则用 OCR 名新建（代码为空也支持，如复旦「电子信息-通信工程」）
- line_type='复试线'，source='kaoyan_zexiaobao_ocr'，source_id=ocr:{school_id}:{major_id}:{year}
- ON CONFLICT (school_id, major_id, year, line_type) 只覆盖自己此前导入的
  OCR 行，不覆盖 kaoyan.cn / 宝典文本行。
"""
import json
import os
import sys
import re

import psycopg

DB = dict(host='127.0.0.1', port=5432, user='kaoyan', password='kaoyan_dev_2026', dbname='kaoyan')
PARSED = r'D:\平台\data_sources\kaoyan-zexiao-baodian\ocr_scorelines_parsed_boxes.json'
SOURCE = 'kaoyan_zexiaobao_ocr'
LINE_TYPE = '复试线'

BAD_MAJOR_RE = re.compile(r'届毕业生|就业情况|分数线上涨|分数线下|招生人数|录取中位数|平均数|福利局|今年')


def clean_major_name(name):
    name = re.sub(r'\s+', '', name or '')
    name = re.sub(r'[（(]\d{2,3}[）)].*$', '', name)
    name = re.sub(r'(考研|咨询|交流|群|学长|学姐|老师|微信|QQ|抖音|知乎|B站|复试|拟录取|分析).*$', '', name)
    return name.strip()[:60]


def find_or_create_major(cur, school_id, code, name):
    """优先用库内规范专业名；找不到再创建。返回 (major_id, canonical_code, canonical_name)。"""
    name = clean_major_name(name)
    if not name:
        return None, None, None
    # 1) 按代码找（库内规范名）
    if code:
        cur.execute("""
            SELECT id, code, name FROM kaoyan_majors
            WHERE school_id=%s AND code=%s AND name IS NOT NULL
            ORDER BY id LIMIT 1
        """, (school_id, code))
        row = cur.fetchone()
        if row:
            return row[0], row[1], row[2]
        # 2) 按 (代码, 名称) 找
        cur.execute("""
            SELECT id, code, name FROM kaoyan_majors
            WHERE school_id=%s AND code=%s AND name=%s
            ORDER BY id LIMIT 1
        """, (school_id, code, name))
        row = cur.fetchone()
        if row:
            return row[0], row[1], row[2]
    # 3) 按名称找（精确 + 前缀，兼容 OCR 截断名）
    cur.execute("""
        SELECT id, code, name FROM kaoyan_majors
        WHERE school_id=%s AND (name=%s OR name LIKE %s)
        ORDER BY (name=%s) DESC, (code IS NOT NULL) DESC, length(name) DESC, id LIMIT 1
    """, (school_id, name, name + '%', name))
    row = cur.fetchone()
    if row:
        return row[0], row[1], row[2]
    if BAD_MAJOR_RE.search(name) or len(name) < 3:
        return None, None, None
    degree_type = 'professional' if str(code or '').startswith('085') else 'academic'
    cur.execute("""
        INSERT INTO kaoyan_majors (school_id, college_id, code, name, degree_type)
        VALUES (%s, NULL, %s, %s, %s)
        ON CONFLICT (school_id, college_id, code, name)
        DO UPDATE SET degree_type=EXCLUDED.degree_type
        RETURNING id, code, name
    """, (school_id, code, name, degree_type))
    r = cur.fetchone()
    return r[0], r[1], r[2]


def upsert_scoreline(cur, school_id, major_id, year, total_line, major_code, major_name,
                     depart_name, note):
    if major_id is None:
        return False
    source_id = f'ocr:{school_id}:{major_id}:{year}'
    cur.execute("""
        INSERT INTO kaoyan_scorelines (school_id, major_id, year, total_line, line_type,
                                       source, major_code, major_name, depart_name, note, source_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (school_id, major_id, year, line_type)
        DO UPDATE SET total_line=EXCLUDED.total_line, major_code=EXCLUDED.major_code,
                      major_name=EXCLUDED.major_name, depart_name=EXCLUDED.depart_name,
                      note=EXCLUDED.note, source_id=EXCLUDED.source_id
        WHERE kaoyan_scorelines.source = %s
    """, (school_id, major_id, year, total_line, LINE_TYPE, SOURCE, major_code, major_name,
          depart_name, note, source_id, SOURCE))
    return True


def main():
    rows = json.load(open(PARSED, encoding='utf-8'))
    conn = psycopg.connect(**DB)
    cur = conn.cursor()

    # 学校是否有 high 行
    school_has_high = {}
    for r in rows:
        if r.get('confidence') == 'high':
            school_has_high[r['school']] = True

    stats = {'scorelines': 0, 'high_rows': 0, 'mid_rows': 0, 'schools': set(), 'skipped_no_major': 0}
    for r in rows:
        if r.get('confidence') == 'high':
            ok = True
        elif r.get('confidence') == 'mid' and not school_has_high.get(r['school']):
            ok = True
        else:
            continue
        if not ok:
            continue
        vals = [r.get(k) for k in ('y2024', 'y2025', 'y2026')]
        if not any(v is not None for v in vals):
            continue
        cur.execute("SELECT id FROM kaoyan_schools WHERE name=%s", (r['school'],))
        srow = cur.fetchone()
        if not srow:
            print('  [skip] 未找到学校:', r['school'])
            continue
        school_id = srow[0]
        ocr_code = r.get('major_code')
        ocr_name = (r.get('major_name') or '').strip()[:60]
        major_id, can_code, can_name = find_or_create_major(cur, school_id, ocr_code, ocr_name)
        if major_id is None:
            stats['skipped_no_major'] += 1
            continue
        code = can_code or ocr_code
        name = can_name or ocr_name
        stats['schools'].add(school_id)
        note = 'OCR自动识别，误差±5分' if r['confidence'] == 'high' else 'OCR自动识别，未校验'
        for ykey, col in (('y2024', 2024), ('y2025', 2025), ('y2026', 2026)):
            v = r.get(ykey)
            if v is None:
                continue
            if upsert_scoreline(cur, school_id, major_id, col, int(v), code, name,
                                r.get('college'), note):
                stats['scorelines'] += 1
        if r['confidence'] == 'high':
            stats['high_rows'] += 1
        else:
            stats['mid_rows'] += 1
        conn.commit()
    conn.commit()
    print('OCR 分数线导入完成:')
    print('  schools:', len(stats['schools']))
    print('  high 专业行:', stats['high_rows'], '| mid 专业行:', stats['mid_rows'])
    print('  scoreline 行:', stats['scorelines'])
    print('  跳过（无有效专业名）:', stats['skipped_no_major'])
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())