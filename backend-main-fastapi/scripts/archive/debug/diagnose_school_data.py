# -*- coding: utf-8 -*-
"""
院校数据中心数据质量诊断（只读）。

诊断范围严格限定在：
  kaoyan_schools / kaoyan_colleges / kaoyan_majors / kaoyan_admissions / school_aliases
不读 quiz_questions / kaoyan_notices 的内容（只统计行数用于判断可回填来源）。

**本脚本完全只读**：只走 sqlite3.connect("file:...?mode=ro")，绝不写入。

用法：
  python scripts/diagnose_school_data.py
  python scripts/diagnose_school_data.py --section3   # 只看院校层级错标
"""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

DB_URI = "file:D:/平台/database/kaoyan.db?mode=ro"
CONN = sqlite3.connect(DB_URI, uri=True)
CONN.row_factory = sqlite3.Row


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def q(sql: str, params: tuple = ()) -> list:
    return CONN.execute(sql, params).fetchall()


# ============================================================ 0. 总览
def section0():
    hr("0. 表规模总览")
    for t in ["kaoyan_schools", "kaoyan_colleges", "kaoyan_majors",
              "kaoyan_admissions", "school_aliases"]:
        n = q(f"SELECT COUNT(*) c FROM {t}")[0]["c"]
        print(f"  {t:22s} {n:6d} 行")

    print("\n  level 分布：")
    for r in q("SELECT COALESCE(level,'<NULL>') lv, COUNT(*) c FROM kaoyan_schools GROUP BY 1 ORDER BY c DESC"):
        print(f"    {r['lv']:<10s} {r['c']:5d}")

    print("\n  字段填充率 kaoyan_schools：")
    cols = [r[1] for r in q("PRAGMA table_info(kaoyan_schools)")]
    total = q("SELECT COUNT(*) c FROM kaoyan_schools")[0]["c"]
    for c in cols:
        n = q(f"SELECT COUNT(*) c FROM kaoyan_schools WHERE {c} IS NOT NULL AND TRIM({c})<>''")[0]["c"]
        print(f"    {c:16s} {n:5d}/{total}  {n*100.0/total:5.1f}%")


# ============================================================ 1. level NULL
def section1():
    hr("1. level 为 NULL 的 214 条：能否从现有字段回填")
    rows = q("""SELECT id,name,type,region,tags,province,city,official_url,intro,data_source
                FROM kaoyan_schools WHERE level IS NULL OR TRIM(level)=''""")
    print(f"  NULL level 行数：{len(rows)}")

    print("\n  这些行的 type / region / tags 组合分布：")
    comb = Counter((r["type"], r["region"]) for r in rows)
    for (t, rg), c in comb.most_common(20):
        print(f"    type={str(t):<12s} region={str(rg):<12s} -> {c}")

    print("\n  tags 是否有非空值：")
    tagcnt = Counter()
    for r in rows:
        tg = (r["tags"] or "").strip()
        if tg:
            for t in re.split(r"[,，;；/、|]", tg):
                if t.strip():
                    tagcnt[t.strip()] += 1
    if tagcnt:
        for t, c in tagcnt.most_common(30):
            print(f"    tag={t:<20s} {c}")
    else:
        print("    （tags 全部为空，无法据此判断层级）")

    print("\n  前 60 条明细（id / name / type / region / tags）：")
    for r in rows[:60]:
        print(f"    {r['id']:<5d} {r['name'][:30]:<32s} type={str(r['type'])[:10]:<11s} "
              f"region={str(r['region'])[:10]:<11s} tags={str(r['tags'])[:30]}")


# ============================================================ 2. 官网缺失
def section2():
    hr("2. official_url 缺失 382 所：data_source 里有没有官网线索")
    miss = q("""SELECT id,name,level,data_source,type,region,tags
                FROM kaoyan_schools
                WHERE official_url IS NULL OR TRIM(official_url)=''""")
    print(f"  缺官网行数：{len(miss)}")

    print("\n  全表 data_source 分布（对比）：")
    for r in q("SELECT COALESCE(data_source,'<NULL>') ds, COUNT(*) c FROM kaoyan_schools GROUP BY 1 ORDER BY c DESC LIMIT 30"):
        print(f"    {r['ds'][:60]:<62s} {r['c']:5d}")

    print("\n  缺官网院校的 data_source 分布：")
    for r in q("""SELECT COALESCE(data_source,'<NULL>') ds, COUNT(*) c FROM kaoyan_schools
                   WHERE official_url IS NULL OR TRIM(official_url)='' GROUP BY 1 ORDER BY c DESC LIMIT 20"""):
        print(f"    {r['ds'][:60]:<62s} {r['c']:5d}")

    # data_source 里含 edu.cn 的
    hit = [r for r in miss if r["data_source"] and "edu.cn" in r["data_source"]]
    print(f"\n  data_source 中含 'edu.cn' 的缺官网院校：{len(hit)}")
    for r in hit[:20]:
        print(f"    {r['id']:<5d} {r['name'][:26]:<28s} ds={r['data_source'][:50]}")

    # name 里含已知高校简称 + 是否有 tags 提示
    print("\n  缺官网院校 level 分布：")
    for r in q("""SELECT COALESCE(level,'<NULL>') lv, COUNT(*) c FROM kaoyan_schools
                   WHERE official_url IS NULL OR TRIM(official_url)='' GROUP BY 1 ORDER BY c DESC"""):
        print(f"    {r['lv']:<10s} {r['c']:5d}")


# ============================================================ 3. 层级错标
# 权威名单复用 school_level_truth（单一事实来源），不再内嵌硬编码名单。
# 历史 bug：本文件曾内嵌一份错误的 985/211 名单（误标 5 所 985、漏标 6 所 985），
# 导致误报「29 所错标」。现已改为直接调用 school_level_truth.truth_level()。
from school_level_truth import truth_level  # noqa: E402


def section3():
    hr("3. 院校层级错标（最关键 —— 直接误导择校）")
    rows = q("SELECT id,name,level,province,city,region,type,tags FROM kaoyan_schools")

    matched = 0
    mis = []
    for r in rows:
        hit = truth_level(r["name"])
        if hit is None:
            continue
        matched += 1
        lv = (r["level"] or "").strip()
        if lv != hit:
            mis.append((r, hit))

    print(f"  可用权威名单交叉验证的院校：{matched} 所")
    print(f"  其中 level 与权威名单不一致：{len(mis)} 所")

    dist = Counter((r["level"] or "<NULL>", exp) for r, exp in mis)
    print("\n  (库内level -> 权威level) 错标分布：")
    for (cur, exp), c in dist.most_common():
        print(f"    {cur:<10s} -> 应为 {exp:<6s} : {c}")

    print(f"\n  全部错标院校名单：")
    for r, exp in sorted(mis, key=lambda x: (x[1], x[0]["name"])):
        print(f"    {r['id']:<5d} {r['name'][:30]:<32s} 库内={str(r['level'] or '<NULL>'):<8s} 应为={exp}")

    # 单独看双非里名字明显是重点的
    print("\n  --- 反向检查：level='双非' 但命中 985/211 名单 ---")
    for r, exp in mis:
        if (r["level"] or "").strip() == "双非":
            print(f"    {r['id']:<5d} {r['name'][:32]:<34s} 应为={exp}")

    # 名字含重点关键字但在双非/None 里（未命中名单，供人工判断）
    print("\n  --- 关键字疑似（省会有 师范/科技/工业/交通/财经/医科 等，但库内为双非/NULL 且未命中名单）---")
    KW = ["师范", "科技大学", "工业大学", "交通大学", "财经大学", "医科大学",
          "中医药", "石油大学", "矿业大学", "航空", "海洋大学", "林业大学",
          "农业大学", "电子科技", "理工大学", "建筑大学", "钢铁", "纺织"]
    prov_capital = {"北京", "上海", "天津", "重庆", "广州", "深圳", "杭州", "南京",
                    "成都", "武汉", "西安", "长沙", "郑州", "济南", "青岛", "合肥",
                    "福州", "厦门", "南昌", "昆明", "贵阳", "兰州", "太原", "石家庄",
                    "哈尔滨", "长春", "沈阳", "大连", "苏州", "无锡", "宁波"}
    susp = []
    for r in rows:
        lv = (r["level"] or "").strip()
        if lv not in ("双非", ""):
            continue
        nm = r["name"]
        if truth_level(nm) is not None:
            continue
        if not any(k in nm for k in KW):
            continue
        if r["city"] in prov_capital or r["province"] in prov_capital:
            susp.append(r)
    print(f"  计数：{len(susp)}")
    for r in susp[:60]:
        print(f"    {r['id']:<5d} {r['name'][:30]:<32s} level={str(r['level'] or '<NULL>'):<8s} "
              f"city={str(r['city']):<8s} type={str(r['type'])[:10]}")
    return mis, susp


# ============================================================ 4. 年份
def section4():
    hr("4. 录取数据年份分布")
    print("  年份分布：")
    for r in q("SELECT year, COUNT(*) c FROM kaoyan_admissions GROUP BY 1 ORDER BY 1"):
        print(f"    {r['year']}: {r['c']}")

    print("\n  data_source / source 分布：")
    for col in ("data_source", "source"):
        print(f"   --{col}--")
        for r in q(f"SELECT COALESCE({col},'<NULL>') v, COUNT(*) c FROM kaoyan_admissions GROUP BY 1 ORDER BY c DESC LIMIT 15"):
            print(f"      {str(r['v'])[:60]:<62s} {r['c']:5d}")

    print("\n  每年覆盖的院校数：")
    for r in q("SELECT year, COUNT(DISTINCT school_id) s, COUNT(DISTINCT major_id) m FROM kaoyan_admissions GROUP BY 1 ORDER BY 1"):
        print(f"    {r['year']}: 院校 {r['s']}, 专业 {r['m']}")

    print("\n  是否存在往年复试线/分数线文本可供回填（只统计，不动 notices 内容）：")
    for kw in ("复试线", "分数线", "国家线", "院校线", "复试名单", "拟录取"):
        n = q("SELECT COUNT(*) c FROM kaoyan_notices WHERE title LIKE ?", (f"%{kw}%",))[0]["c"]
        print(f"    notices.title 含 '{kw}': {n}")
    for kw in ("复试线", "分数线", "国家线"):
        n = q("SELECT COUNT(*) c FROM knowledge_chunks WHERE text LIKE ?", (f"%{kw}%",))[0]["c"]
        print(f"    knowledge_chunks.text 含 '{kw}': {n}")


# ============================================================ 5. 孤儿引用
def section5():
    hr("5. 孤儿引用 / 冗余")
    tot_maj = q("SELECT COUNT(*) c FROM kaoyan_majors")[0]["c"]
    orphan_col = q("""SELECT COUNT(*) c FROM kaoyan_majors m
                      WHERE m.college_id IS NOT NULL
                        AND NOT EXISTS(SELECT 1 FROM kaoyan_colleges c WHERE c.id=m.college_id)""")[0]["c"]
    null_col = q("SELECT COUNT(*) c FROM kaoyan_majors WHERE college_id IS NULL")[0]["c"]
    print(f"  kaoyan_majors 总数 {tot_maj}")
    print(f"    college_id 为 NULL          : {null_col}")
    print(f"    college_id 指向不存在的college: {orphan_col}")

    tot_adm = q("SELECT COUNT(*) c FROM kaoyan_admissions")[0]["c"]
    orphan_maj = q("""SELECT COUNT(*) c FROM kaoyan_admissions a
                      WHERE a.major_id IS NOT NULL
                        AND NOT EXISTS(SELECT 1 FROM kaoyan_majors m WHERE m.id=a.major_id)""")[0]["c"]
    null_maj = q("SELECT COUNT(*) c FROM kaoyan_admissions WHERE major_id IS NULL")[0]["c"]
    print(f"  kaoyan_admissions 总数 {tot_adm}")
    print(f"    major_id 为 NULL            : {null_maj}")
    print(f"    major_id 指向不存在的major  : {orphan_maj}")

    # school 级孤儿
    for tbl, col in [("kaoyan_colleges", "school_id"), ("kaoyan_majors", "school_id"),
                     ("kaoyan_admissions", "school_id"), ("school_aliases", "school_id")]:
        n = q(f"""SELECT COUNT(*) c FROM {tbl} t WHERE t.{col} IS NOT NULL
                  AND NOT EXISTS(SELECT 1 FROM kaoyan_schools s WHERE s.id=t.{col})""")[0]["c"]
        tot = q(f"SELECT COUNT(*) c FROM {tbl}")[0]["c"]
        print(f"  {tbl}.{col} 孤儿: {n} / {tot}")

    # major 与 college 的school 不一致
    mism = q("""SELECT COUNT(*) c FROM kaoyan_majors m
                JOIN kaoyan_colleges c ON c.id=m.college_id
                WHERE m.school_id <> c.school_id""")[0]["c"]
    print(f"  major.school_id 与 college.school_id 不一致: {mism}")

    # admissions 的 major 与 school 不一致
    mism2 = q("""SELECT COUNT(*) c FROM kaoyan_admissions a
                 JOIN kaoyan_majors m ON m.id=a.major_id
                 WHERE a.school_id <> m.school_id""")[0]["c"]
    print(f"  admission.school_id 与 major.school_id 不一致: {mism2}")

    # 别名表质量
    print("\n  school_aliases alias_type 分布：")
    for r in q("SELECT COALESCE(alias_type,'<NULL>') t, COUNT(*) c FROM school_aliases GROUP BY 1 ORDER BY c DESC"):
        print(f"    {r['t']:<16s} {r['c']}")
    bad_alias = q("""SELECT COUNT(*) c FROM school_aliases a
                      WHERE NOT EXISTS(SELECT 1 FROM kaoyan_schools s WHERE s.id=a.school_id)""")[0]["c"]
    print(f"  别名指向不存在学校: {bad_alias}")


# ============================================================ 6. 专业字段质量
def section6():
    hr("6. kaoyan_majors 字段填充率与内容质量")
    tot = q("SELECT COUNT(*) c FROM kaoyan_majors")[0]["c"]
    for c in ["code", "name", "research_direction", "subject_code", "exam_subjects",
              "reference_books", "degree_type"]:
        n = q(f"SELECT COUNT(*) c FROM kaoyan_majors WHERE {c} IS NOT NULL AND TRIM({c})<>''")[0]["c"]
        print(f"    {c:20s} {n:5d}/{tot}  {n*100.0/tot:5.1f}%")

    print("\n  degree_type 分布：")
    for r in q("SELECT COALESCE(degree_type,'<NULL>') d, COUNT(*) c FROM kaoyan_majors GROUP BY 1 ORDER BY c DESC LIMIT 15"):
        print(f"    {str(r['d'])[:40]:<42s} {r['c']:5d}")

    print("\n  exam_subjects 抽样 15 条：")
    for r in q("SELECT id,name,exam_subjects FROM kaoyan_majors WHERE exam_subjects IS NOT NULL AND TRIM(exam_subjects)<>'' LIMIT 15"):
        print(f"    {r['id']:<6d} {r['name'][:24]:<26s} => {r['exam_subjects'][:80]}")
    print("\n  exam_subjects 内容形态分布（是否含'政治/英语/数学'）：")
    forms = Counter()
    for r in q("SELECT exam_subjects FROM kaoyan_majors WHERE exam_subjects IS NOT NULL AND TRIM(exam_subjects)<>''"):
        v = r["exam_subjects"]
        key = ("含'英语'" if "英语" in v else "") + ("+政治" if "政治" in v else "") + ("+数学" if "数学" in v else "") or "其他"
        forms[key] += 1
    for k, c in forms.most_common():
        print(f"    {k:<24s} {c}")

    print("\n  reference_books 抽样 10 条：")
    for r in q("SELECT id,name,reference_books FROM kaoyan_majors WHERE reference_books IS NOT NULL AND TRIM(reference_books)<>'' LIMIT 10"):
        print(f"    {r['id']:<6d} {r['name'][:22]:<24s} => {r['reference_books'][:100]}")

    print("\n  name 疑似脏值（含模板占位/未解析）：")
    for r in q("""SELECT id,school_id,name,code FROM kaoyan_majors
                  WHERE name LIKE '%{unknown}%' OR name LIKE '%}%' OR name LIKE '%请%'
                     OR name LIKE '%专业名称%' OR name IS NULL OR TRIM(name)='' LIMIT 30"""):
        print(f"    {r['id']:<6d} school={r['school_id']:<5d} name={str(r['name'])[:50]} code={r['code']}")

    print("\n  学校去重：同校多条 major 记录但 code 空的比例：")
    print("   ", q("SELECT COUNT(*) c FROM kaoyan_majors WHERE code IS NULL OR TRIM(code)=''")[0]["c"])

    print("\n  录取表字段填充率：")
    ta = q("SELECT COUNT(*) c FROM kaoyan_admissions")[0]["c"]
    for c in ["enroll_count", "retest_count", "admit_count", "admit_avg_score",
              "major_avg_score", "retest_ratio"]:
        n = q(f"SELECT COUNT(*) c FROM kaoyan_admissions WHERE {c} IS NOT NULL")[0]["c"]
        print(f"    {c:20s} {n:5d}/{ta}  {n*100.0/ta:5.1f}%")


# ============================================================ 7. 省份/城市/region 写法
def section7():
    hr("7. province / city / region 写法标准化空间")
    for col in ("province", "city", "region"):
        print(f"\n  {col} 全表取值数：{q(f'SELECT COUNT(DISTINCT {col}) c FROM kaoyan_schools')[0]['c']}")
        vals = q(f"SELECT COALESCE({col},'<NULL>') v, COUNT(*) c FROM kaoyan_schools GROUP BY 1 ORDER BY c DESC LIMIT 45")
        print("   ", " | ".join(f"{r['v']}:{r['c']}" for r in vals))

    print("\n  疑似带后缀的写法（'省'/'市'结尾）：")
    for col in ("province",):
        for r in q(f"SELECT {col} v, COUNT(*) c FROM kaoyan_schools WHERE {col} LIKE '%省' OR {col} LIKE '%市' GROUP BY 1 ORDER BY c DESC"):
            print(f"    {col}={r['v']:<12s} {r['c']}")

    print("\n  province/city 不匹配的抽样（city 名的省份前缀对不上）：")
    m = q("""SELECT province, city, COUNT(*) c FROM kaoyan_schools
             WHERE city IS NOT NULL AND province IS NOT NULL
             GROUP BY 1,2 HAVING c>0 ORDER BY c DESC LIMIT 50""")
    for r in m:
        print(f"    {str(r['province']):<10s} {str(r['city']):<14s} {r['c']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--section3", action="store_true")
    args = ap.parse_args()
    if args.section3:
        section3()
        return
    section0()
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    section7()


if __name__ == "__main__":
    main()