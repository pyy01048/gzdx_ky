# -*- coding: utf-8 -*-
"""txkyer.cn 通信电子类考研数据全量导入。

数据源：http://www.txkyer.cn/data/kaoyan_data.js
（已下载缓存到 D:\\平台\\data_sources\\txkyer_kaoyan_data.js）

记录结构（columns）：
    province, school, college, majorCode, majorName,
    enterNum(进复试), admitNum(拟录取), ratio(复录比),
    enterMax/Min/Mid/Avg(进复试分数分布), admitMax/Min/Avg/Mid(录取分数分布),
    courseMax/Min/Avg/Mid(专业课分布), mathAvg(数学平均),
    math, english, course2(初试科目), tier(985/211/双一流/双非)

写入：
- kaoyan_colleges  : 学院（剥离 (NNN) 前缀）
- kaoyan_majors    : 专业（ON CONFLICT (school_id,college_id,code,name)）
- kaoyan_admissions: 2026 拟录取（extra 存全量分数分布；不覆盖已入库的 PDF 宝典数据）

幂等，可重复运行。
"""
import json
import os
import re
import sys

import psycopg

DB = dict(host='127.0.0.1', port=5432, user='kaoyan', password='kaoyan_dev_2026', dbname='kaoyan')
DATA_SOURCE = 'txkyer_cn'
CACHE = r'D:\平台\data_sources\txkyer_kaoyan_data.js'
REMOTE = 'http://www.txkyer.cn/data/kaoyan_data.js'
YEAR = 2026

# PDF 宝典导入源（优先保留，不覆盖）
KEEP_SOURCE = 'kaoyan_zexiao_baodian_2027'

SUBJECT_RE = re.compile(r'^\((\d{3})\)\s*(.*)$')


def load_records():
    if not os.path.exists(CACHE):
        import urllib.request
        req = urllib.request.Request(REMOTE, headers={'User-Agent': 'Mozilla/5.0'})
        js = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore')
        open(CACHE, 'w', encoding='utf-8').write(js)
    else:
        js = open(CACHE, encoding='utf-8').read()
    m = re.search(r'window\.KAOYAN_DATA\s*=\s*(\{.*?\})\s*;?\s*$', js, re.S)
    if not m:
        raise RuntimeError('未找到 KAOYAN_DATA')
    return json.loads(m.group(1))['records']


def clean_college(name):
    return re.sub(r'^\(\d{3}\)\s*', '', name or '').strip()


def clean_code(code):
    """清洗专业代码：'None'/空/NaN → None，其余返回字符串。"""
    if code is None:
        return None
    if isinstance(code, float) and code != code:
        return None
    s = str(code).strip()
    return s if s and s.lower() != 'none' else None


def num(v):
    """把 JS 的 NaN/Infinity 清洗为 None；普通数值原样返回。"""
    if isinstance(v, float) and (v != v or v in (float('inf'), float('-inf'))):
        return None
    return v


CODE_IN_NAME_RE = re.compile(r'^\((\d{6})\)\s*(.*)$')


def parse_subject(s):
    if not s:
        return None
    m = SUBJECT_RE.match(s.strip())
    if m:
        return {'code': m.group(1), 'name': m.group(2).strip()}
    return {'code': None, 'name': s.strip()}


def upsert_school(cur, name, province, tier):
    cur.execute("SELECT id FROM kaoyan_schools WHERE name=%s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("""
        INSERT INTO kaoyan_schools (name, province, level, data_source)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (name, province, tier if tier in ('985', '211', '双一流', '双非') else None, DATA_SOURCE))
    return cur.fetchone()[0]


def upsert_college(cur, school_id, name):
    cur.execute("""
        INSERT INTO kaoyan_colleges (school_id, name)
        VALUES (%s, %s)
        ON CONFLICT (school_id, name) DO UPDATE SET name=EXCLUDED.name
        RETURNING id
    """, (school_id, name))
    return cur.fetchone()[0]


def upsert_major(cur, school_id, college_id, code, name, degree_type, subjects):
    if not code:
        # NULL 代码无法触发 ON CONFLICT，手动幂等（按 校+院+名 查）
        cur.execute("""
            SELECT id FROM kaoyan_majors
            WHERE school_id=%s AND college_id=%s AND name=%s LIMIT 1
        """, (school_id, college_id, name))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE kaoyan_majors SET degree_type=%s, exam_subjects=%s WHERE id=%s
            """, (degree_type, json.dumps(subjects, ensure_ascii=False), row[0]))
            return row[0]
    cur.execute("""
        INSERT INTO kaoyan_majors (school_id, college_id, code, name, degree_type, exam_subjects)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (school_id, college_id, code, name)
        DO UPDATE SET degree_type=EXCLUDED.degree_type, exam_subjects=EXCLUDED.exam_subjects
        RETURNING id
    """, (school_id, college_id, code, name, degree_type,
          json.dumps(subjects, ensure_ascii=False)))
    return cur.fetchone()[0]


def upsert_admission(cur, school_id, major_id, values, extra, source_id):
    """写入 2026 拟录取；已存在且为 PDF 宝典源时不覆盖。"""
    cur.execute("""
        INSERT INTO kaoyan_admissions (school_id, major_id, year, retest_count, admit_count,
                                      retest_ratio, admit_avg_score, major_avg_score,
                                      data_source, source, extra)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (school_id, major_id, year)
        DO UPDATE SET retest_count=EXCLUDED.retest_count, admit_count=EXCLUDED.admit_count,
                      retest_ratio=EXCLUDED.retest_ratio, admit_avg_score=EXCLUDED.admit_avg_score,
                      major_avg_score=EXCLUDED.major_avg_score, data_source=EXCLUDED.data_source,
                      source=EXCLUDED.source, extra=EXCLUDED.extra
        WHERE kaoyan_admissions.data_source IS DISTINCT FROM %s
    """, (school_id, major_id, YEAR, values['retest_count'], values['admit_count'],
          values['retest_ratio'], values['admit_avg_score'], values['major_avg_score'],
          DATA_SOURCE, source_id, json.dumps(extra, ensure_ascii=False), KEEP_SOURCE))


def main():
    records = load_records()
    conn = psycopg.connect(**DB)
    cur = conn.cursor()
    stats = {'schools': set(), 'colleges': 0, 'majors': 0, 'admissions': 0, 'skipped': 0}
    for i, rec in enumerate(records, 1):
        province, school, college_raw, code_raw, major_name = rec[0], rec[1], rec[2], rec[3], rec[4]
        code = clean_code(code_raw)
        # 部分记录专业代码为空，但专业名形如 "(0829Z3)林业电气化与自动化"（代码内嵌）
        if not code:
            m = CODE_IN_NAME_RE.match(str(major_name or '').strip())
            if m:
                code = m.group(1)
                major_name = m.group(2).strip()
        enter_num = num(rec[5])
        admit_num = num(rec[6])
        ratio = num(rec[7])
        enter_max, enter_min, enter_mid, enter_avg = num(rec[8]), num(rec[9]), num(rec[10]), num(rec[11])
        admit_max, admit_min, admit_avg, admit_mid = num(rec[12]), num(rec[13]), num(rec[14]), num(rec[15])
        course_max, course_min, course_avg, course_mid = num(rec[16]), num(rec[17]), num(rec[18]), num(rec[19])
        math_avg = num(rec[20])
        subjects = [parse_subject(s) for s in (rec[21], rec[22], rec[23])]
        subjects = [s for s in subjects if s and s.get('name')]
        tier = rec[24] if len(rec) > 24 else None

        school_id = upsert_school(cur, school, province, tier)
        stats['schools'].add(school_id)

        college_name = clean_college(college_raw)
        college_id = upsert_college(cur, school_id, college_name)
        stats['colleges'] += 1

        degree_type = 'professional' if str(code or '').startswith('085') else 'academic'
        major_id = upsert_major(cur, school_id, college_id, code, major_name, degree_type, subjects)
        stats['majors'] += 1

        values = {
            'retest_count': int(enter_num) if enter_num else None,
            'admit_count': int(admit_num) if admit_num else None,
            'retest_ratio': float(ratio) if ratio else None,
            'admit_avg_score': float(admit_avg) if admit_avg else None,
            'major_avg_score': float(course_avg) if course_avg else None,
        }
        extra = {
            'enter_max': enter_max, 'enter_min': enter_min, 'enter_mid': enter_mid,
            'enter_avg': enter_avg, 'admit_max': admit_max, 'admit_min': admit_min,
            'admit_avg': admit_avg, 'admit_mid': admit_mid,
            'course_max': course_max, 'course_min': course_min, 'course_avg': course_avg,
            'course_mid': course_mid, 'math_avg': math_avg,
            'college_raw': college_raw, 'major_code': code, 'major_name': major_name,
            'tier': tier, 'province': province, 'source': 'txkyer_cn',
        }
        source_id = f'txkyer:{i}'
        upsert_admission(cur, school_id, major_id, values, extra, source_id)
        stats['admissions'] += 1

        if i % 300 == 0:
            print(f'processed {i}/{len(records)}', flush=True)
        conn.commit()

    conn.commit()
    print('DONE:')
    print('  schools :', len(stats['schools']))
    print('  colleges:', stats['colleges'])
    print('  majors  :', stats['majors'])
    print('  admissions:', stats['admissions'])
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())