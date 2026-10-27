# -*- coding: utf-8 -*-
"""txkyer.cn 明细数据全量导入（幂等）。

数据源（已下载到 D:\\平台\\data_sources\\）：
1. zexiaobao_data.js       —— window.ZEXIAO_DATA：225 校逐专业逐人分数明细
   （source_scores 总分 / ref_scores 复试分 / major_scores 专业课 / math_scores 数学 / 考试科目）
2. school_detail_data.js   —— const SCHOOL_DATA_0809：68 校 院校特色/研究方向/就业去向

写入：
- kaoyan_colleges / kaoyan_majors ：按 (校, 学院, 代码, 名称) 幂等
- kaoyan_admission_details        ：逐人分数（data_source 唯一 = zexiaobao_2027:...:r{i}，可重跑）
- kaoyan_schools.tags             ：合并 feature/research/employment 标签

依赖：kaoyan_admissions.extra 已在 txkyer/宝典导入中填充。
"""
import json
import os
import re
import sys

import psycopg

DB = dict(host='127.0.0.1', port=5432, user='kaoyan', password='kaoyan_dev_2026', dbname='kaoyan')
DATA_SOURCE = 'zexiaobao_2027'
BASE = r'D:\平台\data_sources'
ZEXIAO = os.path.join(BASE, 'zexiaobao_data.js')
SCHOOL_DETAIL = os.path.join(BASE, 'school_detail_data.js')

COL_CODE_RE = re.compile(r'^\((\d{3})\)\s*(.*)$')
MAJOR_RE = re.compile(r'^\((\d{6})\)\s*(.*)$')
SCHOOL_DETAIL_CONST_RE = re.compile(r'const\s+SCHOOL_DATA_(\w+)\s*=\s*(\{.*?\})\s*;', re.S)
WINDOW_RE = re.compile(r'window\.ZEXIAO_DATA\s*=\s*(\[.*?\])\s*;?\s*$', re.S)


def load_zexiao():
    js = open(ZEXIAO, encoding='utf-8').read()
    m = WINDOW_RE.search(js)
    if not m:
        raise RuntimeError('ZEXIAO_DATA not found')
    return json.loads(m.group(1), parse_constant=lambda x: None)


def load_school_detail():
    import ast
    js = open(SCHOOL_DETAIL, encoding='utf-8').read()
    m = re.search(r'const\s+SCHOOL_DATA_\w+\s*=\s*(\{)', js)
    if not m:
        raise RuntimeError('SCHOOL_DATA not found')
    start = m.start(1)
    depth = 0
    i = start
    in_str = None  # None / "'" / '"' / '`'
    while i < len(js):
        ch = js[i]
        nxt = js[i + 1] if i + 1 < len(js) else ''
        if in_str:
            if in_str == '`' and ch == '\\':
                i += 2
                continue
            if in_str != '`' and ch == '\\':
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ("'", '"', '`'):
            in_str = ch
            i += 1
            continue
        if ch == '/' and nxt == '/':
            j = js.find('\n', i)
            i = j if j != -1 else len(js)
            continue
        if ch == '/' and nxt == '*':
            j = js.find('*/', i)
            i = j + 2 if j != -1 else len(js)
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                literal = js[start:i + 1]
                return ast.literal_eval(literal)
        i += 1
    raise RuntimeError('SCHOOL_DATA object unbalanced')


def clean_college(name):
    m = COL_CODE_RE.match(name or '')
    if m:
        return m.group(2).strip()
    return (name or '').strip()


def split_major(major):
    """' (085401)新一代电子信息技术（含量子技术等）' → (code, name)"""
    m = MAJOR_RE.match(str(major or '').strip())
    if m:
        return m.group(1), m.group(2).strip()
    return None, str(major or '').strip()


def upsert_college(cur, school_id, name):
    cur.execute("""
        INSERT INTO kaoyan_colleges (school_id, name)
        VALUES (%s, %s)
        ON CONFLICT (school_id, name) DO UPDATE SET name=EXCLUDED.name
        RETURNING id
    """, (school_id, name))
    return cur.fetchone()[0]


def upsert_major(cur, school_id, college_id, code, name):
    degree_type = 'professional' if str(code or '').startswith('085') else 'academic'
    subjects = None
    if not code:
        cur.execute("""
            SELECT id FROM kaoyan_majors
            WHERE school_id=%s AND college_id=%s AND name=%s LIMIT 1
        """, (school_id, college_id, name))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute("""
        INSERT INTO kaoyan_majors (school_id, college_id, code, name, degree_type)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (school_id, college_id, code, name)
        DO UPDATE SET degree_type=EXCLUDED.degree_type
        RETURNING id
    """, (school_id, college_id, code, name, degree_type))
    return cur.fetchone()[0]


def find_admission(cur, school_id, major_id, year):
    cur.execute("""
        SELECT id FROM kaoyan_admissions
        WHERE school_id=%s AND major_id=%s AND year=%s LIMIT 1
    """, (school_id, major_id, year))
    row = cur.fetchone()
    return row[0] if row else None


def clean_score(v):
    """分数清洗：None/NaN/Infinity/超出 numeric(6,2) 范围 → None。"""
    if v is None:
        return None
    if isinstance(v, float) and (v != v or v in (float('inf'), float('-inf'))):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if abs(f) > 9999:
        return None
    return f


def upsert_detail(cur, admission_id, school_id, year, major_name, score_initial,
                  score_retest, score_total, remark, source_id, name='匿名考生'):
    cur.execute("""
        INSERT INTO kaoyan_admission_details (admission_id, school_id, year, name, major_name,
                                              score_initial, score_retest, score_total,
                                              remark, data_source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (data_source)
        DO UPDATE SET admission_id=EXCLUDED.admission_id, major_name=EXCLUDED.major_name,
                      score_initial=EXCLUDED.score_initial, score_retest=EXCLUDED.score_retest,
                      score_total=EXCLUDED.score_total, remark=EXCLUDED.remark,
                      year=EXCLUDED.year
    """, (admission_id, school_id, year, name, major_name, score_initial, score_retest,
          score_total, remark, source_id))


def main():
    conn = psycopg.connect(**DB)
    cur = conn.cursor()

    # ---- 1) 院校特色数据（SCHOOL_DATA_0809）合并进 tags ----
    detail = load_school_detail()
    detail_done = 0
    for name, info in detail.items():
        cur.execute("SELECT id, tags FROM kaoyan_schools WHERE name=%s", (name,))
        row = cur.fetchone()
        if not row:
            print('  [detail] 未找到学校，跳过:', name)
            continue
        school_id, tags = row
        if not isinstance(tags, dict):
            tags = {}
        for key in ('feature', 'research', 'employment'):
            if key in info and info[key]:
                tags[key] = info[key]
        cur.execute("UPDATE kaoyan_schools SET tags=%s WHERE id=%s",
                    (json.dumps(tags, ensure_ascii=False), school_id))
        detail_done += 1
    conn.commit()
    print(f'SCHOOL_DATA 院校特色：{detail_done} 校已合并 tags')

    # ---- 2) ZEXIAO_DATA 逐人分数明细 ----
    data = load_zexiao()
    stats = {'schools': 0, 'majors': 0, 'details': 0, 'skipped_school': 0}
    for si, school in enumerate(data, 1):
        name = school['school']
        cur.execute("SELECT id FROM kaoyan_schools WHERE name=%s", (name,))
        srow = cur.fetchone()
        if not srow:
            print('  [zexiao] 未找到学校，跳过:', name)
            stats['skipped_school'] += 1
            continue
        school_id = srow[0]
        stats['schools'] += 1

        for mj in school.get('majors', []):
            code, major_name = split_major(mj.get('major'))
            college_info = mj.get('college_info') or ''
            college_name = clean_college(college_info.split('/', 1)[-1] if '/' in college_info else college_info)
            college_id = upsert_college(cur, school_id, college_name or '未标注学院')
            major_id = upsert_major(cur, school_id, college_id, code, major_name)
            stats['majors'] += 1

            ym = re.search(r'(20\d{2})', str(mj.get('year') or ''))
            year = int(ym.group(1)) if ym else 2026
            admission_id = find_admission(cur, school_id, major_id, year)
            scores = mj.get('source_scores') or []
            refs = mj.get('ref_scores') or []
            major_scores = mj.get('major_scores') or []
            math_scores = mj.get('math_scores') or []
            for i, total_raw in enumerate(scores):
                total = clean_score(total_raw)
                if total is None:
                    continue  # 脏数据行跳过
                remark = {}
                if i < len(major_scores):
                    remark['major_score'] = clean_score(major_scores[i])
                if i < len(math_scores):
                    remark['math_score'] = clean_score(math_scores[i])
                ref = clean_score(refs[i]) if i < len(refs) else None
                if ref is not None:
                    remark['ref_score'] = ref
                source_id = f'{DATA_SOURCE}:{school_id}:{major_id}:r{i}'
                upsert_detail(cur, admission_id, school_id, year, major_name, None,
                              ref, total,
                              json.dumps(remark, ensure_ascii=False) if remark else None,
                              source_id)
                stats['details'] += 1

        if si % 40 == 0:
            conn.commit()
            print(f'  processed {si}/{len(data)} schools, details={stats["details"]}', flush=True)
        conn.commit()

    print('ZEXIAO_DATA 明细导入完成:')
    print('  schools:', stats['schools'], '| 跳过(未匹配):', stats['skipped_school'])
    print('  majors:', stats['majors'], '| details:', stats['details'])
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())