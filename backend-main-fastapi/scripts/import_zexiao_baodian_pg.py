# -*- coding: utf-8 -*-
"""《27考研电子通信考研择校宝典》解析结果入库。

输入：D:\\平台\\data_sources\\kaoyan-zexiao-baodian\\parsed_schools.json（237 校）
写入：
- kaoyan_schools     : intro / tags(学科评估) 增量更新
- kaoyan_colleges    : 学院（ON CONFLICT (school_id,name) UPDATE）
- kaoyan_majors      : 专业（ON CONFLICT (school_id,college_id,code,name) UPDATE）
- kaoyan_admissions  : 2026 拟录取数据（ON CONFLICT (school_id,major_id,year) UPDATE）
- kaoyan_scorelines  : 近三年复试线（ON CONFLICT (school_id,major_id,year,line_type) UPDATE）

幂等，可重复运行。
"""
import json
import os
import re
import sys

import psycopg

PARSED = r'D:\平台\data_sources\kaoyan-zexiao-baodian\parsed_schools.json'
DATA_SOURCE = 'kaoyan_zexiao_baodian_2027'

conn = psycopg.connect(
    host='127.0.0.1', port=5432, user='kaoyan', password='kaoyan_dev_2026', dbname='kaoyan'
)
cur = conn.cursor()


def school_id_by_name(name):
    cur.execute('SELECT id, intro, tags FROM kaoyan_schools WHERE name=%s', (name,))
    row = cur.fetchone()
    if not row:
        return None, None, None
    return row[0], row[1], row[2]


def upsert_college(school_id, name):
    cur.execute("""
        INSERT INTO kaoyan_colleges (school_id, name)
        VALUES (%s, %s)
        ON CONFLICT (school_id, name) DO UPDATE SET name=EXCLUDED.name
        RETURNING id
    """, (school_id, name))
    return cur.fetchone()[0]


def upsert_major(school_id, college_id, code, name, degree_type, research_direction, exam_subjects):
    cur.execute("""
        INSERT INTO kaoyan_majors (school_id, college_id, code, name, degree_type,
                                   research_direction, exam_subjects)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (school_id, college_id, code, name)
        DO UPDATE SET degree_type=EXCLUDED.degree_type,
                      research_direction=EXCLUDED.research_direction, exam_subjects=EXCLUDED.exam_subjects
        RETURNING id
    """, (school_id, college_id, code, name, degree_type, research_direction, json.dumps(exam_subjects, ensure_ascii=False)))
    return cur.fetchone()[0]


def find_major(school_id, college_name, code, name):
    """在已导入的本校专业中查找 major_id（按学院+代码+名称前缀优先，再代码+名称前缀）。"""
    if college_name:
        cur.execute("""
            SELECT m.id FROM kaoyan_majors m
            JOIN kaoyan_colleges c ON m.college_id=c.id
            WHERE m.school_id=%s AND c.name=%s AND m.code=%s
              AND (m.name=%s OR %s LIKE m.name || '%%' OR m.name LIKE %s || '%%')
            LIMIT 1
        """, (school_id, college_name, code, name, name, name))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute("""
        SELECT m.id FROM kaoyan_majors m
        WHERE m.school_id=%s AND m.code=%s
          AND (m.name=%s OR %s LIKE m.name || '%%' OR m.name LIKE %s || '%%')
        LIMIT 1
    """, (school_id, code, name, name, name))
    row = cur.fetchone()
    return row[0] if row else None


def upsert_admission(school_id, major_id, year, enroll_count, admit_count, retest_count,
                     retest_ratio, admit_avg_score, major_avg_score, extra=None):
    cur.execute("""
        INSERT INTO kaoyan_admissions (school_id, major_id, year, enroll_count,
                                       retest_count, admit_count, admit_avg_score,
                                       major_avg_score, retest_ratio, data_source, extra)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (school_id, major_id, year)
        DO UPDATE SET enroll_count=EXCLUDED.enroll_count, retest_count=EXCLUDED.retest_count,
                      admit_count=EXCLUDED.admit_count, admit_avg_score=EXCLUDED.admit_avg_score,
                      major_avg_score=EXCLUDED.major_avg_score, retest_ratio=EXCLUDED.retest_ratio,
                      data_source=EXCLUDED.data_source, extra=EXCLUDED.extra
    """, (school_id, major_id, year, enroll_count, retest_count, admit_count,
          admit_avg_score, major_avg_score, retest_ratio, DATA_SOURCE,
          json.dumps(extra, ensure_ascii=False) if extra else None))


def upsert_scoreline(school_id, major_id, year, total_line, major_name, depart_name=None, line_type='复试线'):
    import hashlib
    digest = hashlib.md5(f'{school_id}:{year}:{major_name}'.encode('utf-8')).hexdigest()
    source_id = f'{DATA_SOURCE}:{digest}'
    if major_id is None:
        # NULL major_id 无法触发 ON CONFLICT，手动幂等
        cur.execute("""
            SELECT id FROM kaoyan_scorelines
            WHERE school_id=%s AND major_id IS NULL AND year=%s AND line_type=%s AND major_name=%s
        """, (school_id, year, line_type, major_name))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE kaoyan_scorelines SET total_line=%s, source=%s, depart_name=%s, source_id=%s
                WHERE id=%s
            """, (total_line, DATA_SOURCE, depart_name, source_id, row[0]))
            return
    cur.execute("""
        INSERT INTO kaoyan_scorelines (school_id, major_id, year, total_line, line_type,
                                       source, major_name, depart_name, source_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (school_id, major_id, year, line_type)
        DO UPDATE SET total_line=EXCLUDED.total_line, source=EXCLUDED.source,
                      major_name=EXCLUDED.major_name, depart_name=EXCLUDED.depart_name,
                      source_id=EXCLUDED.source_id
    """, (school_id, major_id, year, total_line, line_type, DATA_SOURCE,
          major_name, depart_name, source_id))


def clean_major_name(name):
    name = re.sub(r'^\((?:专业|学术)学位\)\s*', '', name or '')
    # 去掉方向后缀，如 "信息与通信工程(01)通信与信息系统" → "信息与通信工程"
    return re.sub(r'\(\d{2}\)[^（()]*$', '', name).strip()


def main():
    with open(PARSED, encoding='utf-8') as fh:
        schools = json.load(fh)

    stats = {'schools': 0, 'colleges': 0, 'majors': 0, 'admissions': 0, 'scorelines': 0}
    for si, school in enumerate(schools, 1):
        sname = school['school']
        school_id, intro, tags = school_id_by_name(sname)
        if school_id is None:
            # 未匹配到现有院校则新建（当前全量已匹配）
            cur.execute("""
                INSERT INTO kaoyan_schools (name, data_source)
                VALUES (%s, %s) RETURNING id
            """, (sname, DATA_SOURCE))
            school_id = cur.fetchone()[0]
            intro, tags = None, None
        stats['schools'] += 1

        # 1) 更新学校简介/学科评估
        new_intro = school.get('intro')
        rankings = school.get('rankings') or {}
        tags_dict = tags if isinstance(tags, dict) else {}
        if rankings:
            tags_dict['学科评估'] = rankings
        if new_intro:
            if not intro:
                intro = new_intro
            tags_dict['zexiao_baodian'] = True
            cur.execute(
                'UPDATE kaoyan_schools SET intro=%s, tags=%s WHERE id=%s',
                (intro, json.dumps(tags_dict, ensure_ascii=False) if tags_dict else None, school_id),
            )
        elif tags_dict:
            cur.execute(
                'UPDATE kaoyan_schools SET tags=%s WHERE id=%s',
                (json.dumps(tags_dict, ensure_ascii=False), school_id),
            )

        # 2) 学院 + 专业目录
        catalog_major_ids = {}  # (code, name) -> major_id
        catalog_enroll = {}  # (code, name) -> enroll_count
        for college in school.get('colleges') or []:
            cname = college['name']
            college_id = upsert_college(school_id, cname)
            stats['colleges'] += 1
            for mj in college.get('majors') or []:
                code = mj.get('code')
                name = clean_major_name(mj.get('name'))
                if not code or not name:
                    continue
                degree = 'academic' if mj.get('degree_type') == '学硕' else 'professional'
                subjects = [
                    {'code': c, 'name': n} for c, n in mj.get('exam_subjects') or []
                ]
                major_id = upsert_major(
                    school_id, college_id, code, name, degree,
                    mj.get('research_direction'), subjects,
                )
                catalog_major_ids[(code, name)] = major_id
                catalog_enroll[(code, name)] = mj.get('enroll_count')
                stats['majors'] += 1

        # 3) 2026 拟录取数据
        for adm in school.get('admissions') or []:
            code = adm.get('major_code')
            name = clean_major_name(adm.get('major_name'))
            college_name = adm.get('college')
            major_id = find_major(school_id, college_name, code, name)
            if major_id is None and code and name:
                # 目录中无此专业：用拟录取信息补建专业（确保可关联）
                college_id = None
                if college_name:
                    college_id = upsert_college(school_id, college_name)
                major_id = upsert_major(
                    school_id, college_id, code, name, 'professional',
                    None, [],
                )
                stats['majors'] += 1
            # 统招人数：从同校同专业目录取
            enroll_count = catalog_enroll.get((code, name))
            extra = {
                'enter_max': adm.get('max_score'),
                'enter_min': adm.get('min_score'),
                'enter_mid': adm.get('median_score'),
                'enter_avg': adm.get('avg_score'),
                'course_max': adm.get('subject_max'),
                'course_min': adm.get('subject_min'),
                'course_avg': adm.get('subject_avg'),
                'math_avg': adm.get('math_avg'),
                'source': DATA_SOURCE,
            }
            upsert_admission(
                school_id, major_id, 2026,
                enroll_count,
                adm.get('admit_count'),
                adm.get('retest_count'),
                adm.get('retest_ratio'),
                adm.get('avg_score'),
                adm.get('subject_avg'),
                extra,
            )
            stats['admissions'] += 1

        # 4) 近三年复试线
        for sl in school.get('scorelines') or []:
            code = None  # 分数线行没有专业代码
            major_name = clean_major_name(sl.get('major_name'))
            college_name = sl.get('college')
            major_id = None
            if major_name:
                # 按学院+名称前缀匹配
                if college_name:
                    cur.execute("""
                        SELECT m.id FROM kaoyan_majors m
                        JOIN kaoyan_colleges c ON m.college_id=c.id
                        WHERE m.school_id=%s AND c.name=%s
                          AND (m.name=%s OR %s LIKE m.name || '%%' OR m.name LIKE %s || '%%')
                        LIMIT 1
                    """, (school_id, college_name, major_name, major_name, major_name))
                    row = cur.fetchone()
                    if row:
                        major_id = row[0]
                if major_id is None:
                    cur.execute("""
                        SELECT m.id FROM kaoyan_majors m
                        WHERE m.school_id=%s
                          AND (m.name=%s OR %s LIKE m.name || '%%' OR m.name LIKE %s || '%%')
                        LIMIT 1
                    """, (school_id, major_name, major_name, major_name))
                    row = cur.fetchone()
                    if row:
                        major_id = row[0]
            for year_key, year in (('y2024', 2024), ('y2025', 2025), ('y2026', 2026)):
                val = sl.get(year_key)
                if val:
                    upsert_scoreline(school_id, major_id, year, val,
                                      major_name, college_name)
                    stats['scorelines'] += 1

        if si % 40 == 0:
            print(f'processed {si}/{len(schools)} schools', flush=True)
        conn.commit()

    conn.commit()
    print('DONE:', stats)


if __name__ == '__main__':
    sys.exit(main())