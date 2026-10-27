# -*- coding: utf-8 -*-
"""《27考研电子通信考研择校宝典》结构化解析。

输入：D:\\平台\\data_sources\\kaoyan-zexiao-baodian\\text_pages.jsonl（2491 页）
输出：D:\\平台\\data_sources\\kaoyan-zexiao-baodian\\parsed_schools.json

每校结构：
{
  "school": "南京大学",
  "pages": [371, 381],
  "intro": "...",
  "rankings": {"信息与通信工程": "B", "电子科学与技术": "A-"},
  "colleges": [{"name": "电子科学与工程学院", "majors": [{"code": "080902", "name": "电路与系统", "degree_type": "学硕/专硕",
                "research_direction": "...", "enroll_count": 2, "enroll_note": "不变",
                "exam_subjects": ["(201)英语（一）", "(301)数学（一）", "(851)信号与系统"],
                "retest_subject": "数字图像处理"}]}],
  "admissions": [{"college": "物理学院", "major_code": "085400", "major_name": "电子信息",
                  "year": 2026, "admit_count": 8, "retest_count": 11, "retest_ratio": 1.4,
                  "max_score": 428, "min_score": 378, "median_score": 399, "avg_score": 399.5,
                  "subject_max": 132, "subject_avg": 114.3, "subject_min": 101, "math_avg": 133.8}],
  "scorelines": [{"college": "电子科学与工程学院", "major_name": "电路与系统",
                  "y2024": 305, "y2025": 341, "y2026": 382, "change": "上涨41分"}]
}
"""
import json
import os
import re

JSONL = r'D:\平台\data_sources\kaoyan-zexiao-baodian\text_pages.jsonl'
OUT = r'D:\平台\data_sources\kaoyan-zexiao-baodian\parsed_schools.json'

# 学科评估关键词
RANK_KEYS = ['信息与通信工程', '电子科学与技术', '计算机科学与技术', '软件工程', '集成电路科学与工程', '控制科学与工程', '仪器科学与技术', '光学工程']
# 页眉宣传语（每页前 2 行，解析时跳过）
HEADER_MARKERS = ['电子通信考研择校目标院校免费真题索取与择校咨询', '高水平电子通信考研辅导班', 'B站:', '抖音：', '小红书：', '扫描二维码获取最新']
# 项目符号/私用区字符（pdfplumber 会输出 • ■  等前缀）
BULLET_PREFIX = r'[\s\uE000-\uF8FF•■►▶>›»·]'


def clean_lines(text: str):
    lines = []
    for ln in (text or '').splitlines():
        s = ln.strip()
        if not s:
            continue
        # 跳过页眉/页脚宣传行
        if any(m in s for m in HEADER_MARKERS):
            continue
        # 跳过页码行
        if re.fullmatch(r'第 \d+ 页 共 \d+ 页', s):
            continue
        lines.append(s)
    return lines


def find_schools(pages):
    """返回 [(page_no, school_name), ...]"""
    schools = []
    for p in pages:
        text = p.get('text') or ''
        if '院校基本信息' not in text:
            continue
        lines = clean_lines(text)
        for i, line in enumerate(lines[:8]):
            if re.search(r'^(中国)?[^\s]{2,12}(大学|学院)$', line) and len(line) <= 15:
                schools.append((p['page'], line))
                break
    return schools


def parse_rankings(lines):
    rankings = {}
    for ln in lines:
        for key in RANK_KEYS:
            m = re.search(re.escape(key) + r'[:：]\s*([ABC][+-]?)', ln)
            if m:
                rankings[key] = m.group(1)
    return rankings


def parse_intro(lines):
    """学校简介：'院校基本信息' 之后到 '第四轮学科评估排名' 之前（两栏排版会打乱顺序）"""
    out = []
    started = False
    for ln in lines:
        if '第四轮学科评估排名' in ln:
            break
        if '院校基本信息' in ln:
            started = True
            continue
        if started:
            if ln == '学校简介':
                continue
            # 两栏排版导致学科评估行插在简介中间：遇到「XX：等级」即停止
            if len(ln) < 40 and re.search(r'^(信息与通信工程|电子科学与技术|计算机科学与技术|软件工程|集成电路科学与工程|控制科学与工程|仪器科学与技术|光学工程)[:：]', ln):
                break
            out.append(ln)
    return ''.join(out).strip('； ') if out else None


def split_section(lines, start_re, end_re):
    """截取 [start, end) 之间的行；start_re/end_re 为编译后的正则（search）"""
    out = []
    started = False
    for ln in lines:
        if started and end_re.search(ln):
            break
        if not started and start_re.search(ln):
            started = True
            continue
        if started:
            out.append(ln)
    return out


RE_CATALOG_START = re.compile(r'二、\s*\d+\s*考研初复试介绍')
RE_CATALOG_END = re.compile(r'[三四五六]、\s*\d+\s*考研拟录取分析')
RE_ADM_START = re.compile(r'[三四五六]、\s*\d+\s*考研拟录取分析')
RE_ADM_END = re.compile(r'[四五六七]、\s*近[一二三四五]?年?\s*(?:录取分数线|复试线|复试分数线|分数线)')
RE_SCORE_START = re.compile(r'[四五六七]、\s*近[一二三四五]?年?\s*(?:录取分数线|复试线|复试分数线|分数线)')
RE_SCORE_END = re.compile(r'报考建议')


# 考试科目代码（初试）
SUBJECT_CODE_RE = re.compile(r'\((101|199|201|202|203|204|301|302|303|306|307|311|312|313|314|315|396|397|398|408|\d{3})\)([^（）()]+[（(][一二][)）])?')


def parse_college_majors(lines):
    """解析 '二、27 考研初复试介绍' 段落 → colleges 列表

    结构：
    (023)电子科学与工程学院
    (080902)电路与系统
    研究方向 统招人数 初试科目 复试笔试科目
    (201)英语（一）
    2人
    (00)不区分研究方向 (301)数学（一） 数字图像处理
    （不变）
    (851)信号与系统
    ...
    初复试专业课介绍
    """
    college_re = re.compile(rf'^{BULLET_PREFIX}*(?:\(\d{{3}}\)|\d{{3}})\s*([^\n]{{1,40}}?(?:学院|研究院|研究所|中心))$')
    major_re = re.compile(r'^(?:\((\d{6})\)|(\d{6}))\s*(?:\((?:专业|学术)学位\)\s*)?([^\n]+)$')
    direction_re = re.compile(r'\((\d{2})\)\s*([^\s]{1,30}(?:研究方向|集成电路工程|不区分方向)?)')
    enroll_re = re.compile(r'(\d+)\s*人')
    note_re = re.compile(r'（(不变|缩招\d+人|扩招\d+人)）')

    colleges = []
    cur_college = None
    cur_major = None

    i = 0
    while i < len(lines):
        ln = lines[i]
        m = college_re.match(ln)
        if m:
            cur_college = {'name': m.group(1).strip(), 'majors': []}
            colleges.append(cur_college)
            cur_major = None
            i += 1
            continue
        m = major_re.match(ln)
        if m and cur_college is not None:
            code = m.group(1) or m.group(2)
            name = m.group(3).strip()
            # 学硕/专硕：代码 08 开头为学硕，09 为专硕；或名称含「(专业学位)」标记
            degree = '专硕' if '专业学位' in ln or code.startswith('09') else '学硕'
            cur_major = {
                'code': code,
                'name': name,
                'degree_type': degree,
                'research_direction': None,
                'enroll_count': None,
                'enroll_note': None,
                'exam_subjects': [],
                'retest_subject': None,
            }
            cur_college['majors'].append(cur_major)
            i += 1
            continue
        # 在 major 块内收集细节
        if cur_major is not None:
            if '初复试专业课介绍' in ln or '总成绩' in ln:
                # 该 major 块结束（后续属公共段落）
                cur_major = None
                i += 1
                continue
            # 统招人数
            em = enroll_re.search(ln)
            if em and cur_major['enroll_count'] is None:
                cur_major['enroll_count'] = int(em.group(1))
            nm = note_re.search(ln)
            if nm and cur_major['enroll_note'] is None:
                cur_major['enroll_note'] = nm.group(1)
            # 研究方向
            dm = direction_re.match(ln)
            if dm and cur_major['research_direction'] is None:
                cur_major['research_direction'] = dm.group(2)
            # 初试科目：行内含科目代码 + 科目名（如 (851)信号与系统 / (201)英语（一））
            sm = re.search(r'\((\d{3})\)([^\s]{2,20})', ln)
            if sm and sm.group(1) not in [x[0] for x in cur_major['exam_subjects']]:
                cur_major['exam_subjects'].append((sm.group(1), sm.group(2)))
            # 复试笔试科目：同一行内数学科目之后剩余的文本（如 "(301)数学（一） 数字图像处理"）
            if cur_major['retest_subject'] is None:
                # 跳过表头行
                if '研究方向' in ln and '统招人数' in ln and '复试笔试科目' in ln:
                    pass
                else:
                    # 去掉行首研究方向段
                    rest = direction_re.sub('', ln).strip()
                    # 去掉所有初试科目代码段
                    for code, _name in cur_major['exam_subjects']:
                        rest = re.sub(rf'\({code}\)[^\s]{{2,20}}', '', rest)
                    rest = rest.strip(' |｜·、，。')
                    if rest and len(rest) < 30 and not re.search(r'人$|^（', rest):
                        cur_major['retest_subject'] = rest
        i += 1
    return colleges


def parse_admissions(lines):
    """解析 '三、26 考研拟录取分析' → admissions 列表"""
    college_re = re.compile(rf'^{BULLET_PREFIX}*(?:\(\d{{3}}\)|\d{{3}})\s*([^\n]{{1,30}}?(?:学院|研究院|研究所|中心))\s*(?:.*?年一志愿)?')
    major_re = re.compile(r'^[■•►▶·\s]*(?:\((\d{6})\)|(\d{6}))\s*(?:\((?:专业|学术)学位\)\s*)?([^\n]+)$')
    four_num_re = re.compile(r'^([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$')
    ratio_re = re.compile(r'^(\d+)/(\d+)\s*\(\s*([\d.]+)\s*\)\s*$')
    heji_re = re.compile(r'^合计\s+(\d+)\s+(\d+)\s+(\d+)')

    admissions = []
    cur_college = None
    cur_adm = None
    phase = 0  # 0=等待分数, 1=等待复录比, 2=等待专业课分数

    i = 0
    while i < len(lines):
        ln = lines[i]
        m = college_re.match(ln)
        if m:
            cur_college = m.group(1).strip()
            cur_adm = None
            i += 1
            continue
        m = major_re.match(ln)
        if m:
            cur_adm = {
                'college': cur_college,
                'major_code': m.group(1) or m.group(2),
                'major_name': m.group(3).strip(),
                'year': 2026,
            }
            admissions.append(cur_adm)
            phase = 0
            i += 1
            continue
        if cur_adm is not None:
            # 四列分数
            fm = four_num_re.match(ln)
            if fm:
                vals = [float(v) for v in fm.groups()]
                if phase == 0:
                    cur_adm['max_score'], cur_adm['min_score'], cur_adm['median_score'], cur_adm['avg_score'] = vals
                    phase = 1
                elif phase == 2:
                    cur_adm['subject_max'], cur_adm['subject_avg'], cur_adm['subject_min'], cur_adm['math_avg'] = vals
                    phase = 3
                i += 1
                continue
            rm = ratio_re.match(ln)
            if rm:
                cur_adm['admit_count'] = int(rm.group(1))
                cur_adm['retest_count'] = int(rm.group(2))
                cur_adm['retest_ratio'] = float(rm.group(3))
                phase = 2
                i += 1
                continue
            hm = heji_re.match(ln)
            if hm and 'admit_count' not in cur_adm:
                # 若复录比行未解析到，用合计行补齐
                cur_adm['retest_count'] = int(hm.group(1))
                cur_adm['admit_count'] = int(hm.group(2))
                i += 1
                continue
        i += 1
    return admissions


def parse_scorelines(lines):
    """解析 '四、近三年录取分数线变化情况' → scorelines 列表

    行格式（专业名可能含学院前缀）：
    通信与信息系统 310 305 390 上涨85分
    物理学院 电子信息 - 315 378 上涨63分

    处理：学院名可能跨行（如 "电子科学与工" + "程学院"），先合并短后缀行。
    """
    row_re = re.compile(r'^(.+?)\s+(-|\d+)\s+(-|\d+)\s+(-|\d+)\s+(上涨[\d.]+分|下降[\d.]+分|持平|不变)\s*$')
    college_suffix_re = re.compile(r'^[^\s]{1,30}?(?:学院|研究院|研究所|中心)$')
    frag_re = re.compile(r'^[^\s]{1,4}(?:学院|研究院|研究所|中心)$')

    # 第一步：合并跨行学院片段
    merged_lines = []
    for ln in lines:
        if frag_re.match(ln) and merged_lines:
            prev = merged_lines[-1]
            combined = prev + ln
            # 合并后长度合理且前一行本身不像完整学院/数据行
            if len(combined) <= 32 and not college_suffix_re.match(prev) and not row_re.match(prev):
                merged_lines[-1] = combined
                continue
        merged_lines.append(ln)
    lines = merged_lines

    scorelines = []
    cur_college = None
    for ln in lines:
        if college_suffix_re.match(ln) and '复试线' not in ln and not row_re.match(ln):
            cur_college = ln
            continue
        m = row_re.match(ln)
        if m:
            name_part = m.group(1).strip()
            # 若行首即学院名+专业名，尝试拆出学院
            college = cur_college
            mm = re.match(r'^([^\s]{1,30}?(?:学院|研究院|研究所|中心))\s+(.+)$', name_part)
            if mm:
                college = mm.group(1)
                name_part = mm.group(2)
            scorelines.append({
                'college': college,
                'major_name': name_part,
                'y2024': int(m.group(2)) if m.group(2) != '-' else None,
                'y2025': int(m.group(3)) if m.group(3) != '-' else None,
                'y2026': int(m.group(4)) if m.group(4) != '-' else None,
                'change': m.group(5),
            })
    # 跨行学院单元格出现在后续行：将 None 学院向前传播给同一分组的早期行
    for idx, sl in enumerate(scorelines):
        if sl['college'] is None:
            for nxt in scorelines[idx + 1:idx + 5]:
                if nxt['college'] is not None:
                    sl['college'] = nxt['college']
                    break
    return scorelines


def parse_school(school_name, start_page, end_page, pages_by_no):
    texts = []
    for pno in range(start_page, end_page + 1):
        texts.append(pages_by_no[pno].get('text') or '')
    all_lines = []
    for t in texts:
        all_lines.extend(clean_lines(t))

    school = {
        'school': school_name,
        'pages': [start_page, end_page],
        'intro': parse_intro(all_lines),
        'rankings': parse_rankings(all_lines),
        'colleges': [],
        'admissions': [],
        'scorelines': [],
    }
    # 专业目录段
    catalog_lines = split_section(all_lines, RE_CATALOG_START, RE_CATALOG_END)
    if catalog_lines:
        school['colleges'] = parse_college_majors(catalog_lines)
    # 拟录取段
    adm_lines = split_section(all_lines, RE_ADM_START, RE_ADM_END)
    if adm_lines:
        school['admissions'] = parse_admissions(adm_lines)
    # 分数线段
    sc_lines = split_section(all_lines, RE_SCORE_START, RE_SCORE_END)
    if sc_lines:
        school['scorelines'] = parse_scorelines(sc_lines)
    return school


def main():
    with open(JSONL, encoding='utf-8') as fh:
        pages = [json.loads(line) for line in fh]
    pages_by_no = {p['page']: p for p in pages}
    schools = find_schools(pages)
    print(f'检测到 {len(schools)} 所学校', flush=True)

    parsed = []
    for idx, (page_no, name) in enumerate(schools):
        end_page = schools[idx + 1][0] - 1 if idx + 1 < len(schools) else len(pages)
        s = parse_school(name, page_no, end_page, pages_by_no)
        parsed.append(s)
        if (idx + 1) % 30 == 0:
            print(f'parsed {idx + 1}/{len(schools)}', flush=True)

    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(parsed, fh, ensure_ascii=False, indent=1)
    print(f'wrote {OUT}', flush=True)
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())