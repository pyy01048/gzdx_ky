# -*- coding: utf-8 -*-
"""
扩充 kaoyan_schools 院校数据脚本
从 818 所扩充到 1000+ 所

数据来源:
1. open-edu-data 开源数据集 (data/china-universities.csv, 1308 所中国高校)
   GitHub: https://github.com/luhuadong/open-edu-data
2. 手工整理的科研院所清单（中科院系统 / 地方社科院 / 部委研究院）

运行方式:
  C:/Users/33884/.workbuddy/binaries/python/versions/3.13.12/python.exe scripts/expand_schools_pg.py
"""

import csv
import json
import os
import sys

import psycopg

# ---------------------------------------------------------------------------
# 数据库连接
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "user": "kaoyan",
    "password": "kaoyan_dev_2026",
    "dbname": "kaoyan",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "data", "china-universities.csv")

# 非 211 的双一流高校名单（用于 level 字段标记）
SHUANGYILIU = set(
    """
    首都师范大学 外交学院 中国人民公安大学 中国音乐学院 中央美术学院 中央戏剧学院
    中国美术学院 天津工业大学 天津中医药大学 上海海洋大学 上海中医药大学 上海体育大学
    上海音乐学院 南京信息工程大学 南京林业大学 南京医科大学 南京中医药大学 南京邮电大学
    成都理工大学 成都中医药大学 西南石油大学 广州医科大学 华南农业大学 南方科技大学
    宁波大学 山西大学 湘潭大学 上海科技大学 河南大学
    """.split()
)

# ---------------------------------------------------------------------------
# 手工整理的科研院所清单 (name, province, city)
# 参照研招网招生单位，覆盖中科院系统 / 地方社科院 / 部委研究院
# ---------------------------------------------------------------------------
KY_LIST = [
    # --- 中科院系统 ---
    ("中国科学院物理研究所", "北京", "北京"),
    ("中国科学院化学研究所", "北京", "北京"),
    ("中国科学院数学与系统科学研究院", "北京", "北京"),
    ("中国科学院高能物理研究所", "北京", "北京"),
    ("中国科学院半导体研究所", "北京", "北京"),
    ("中国科学院国家天文台", "北京", "北京"),
    ("中国科学院上海硅酸盐研究所", "上海", "上海"),
    ("中国科学院上海药物研究所", "上海", "上海"),
    ("中国科学院上海光学精密机械研究所", "上海", "上海"),
    ("中国科学院上海天文台", "上海", "上海"),
    ("中国科学院南京地质古生物研究所", "江苏", "南京"),
    ("中国科学院南京土壤研究所", "江苏", "南京"),
    ("中国科学院紫金山天文台", "江苏", "南京"),
    ("中国科学院武汉岩土力学研究所", "湖北", "武汉"),
    ("中国科学院广州地球化学研究所", "广东", "广州"),
    ("中国科学院华南植物园", "广东", "广州"),
    ("中国科学院成都生物研究所", "四川", "成都"),
    ("中国科学院水利部成都山地灾害与环境研究所", "四川", "成都"),
    ("中国科学院昆明动物研究所", "云南", "昆明"),
    ("中国科学院昆明植物研究所", "云南", "昆明"),
    ("中国科学院云南天文台", "云南", "昆明"),
    ("中国科学院西双版纳热带植物园", "云南", "西双版纳"),
    ("中国科学院西安光学精密机械研究所", "陕西", "西安"),
    ("中国科学院地球环境研究所", "陕西", "西安"),
    ("中国科学院国家授时中心", "陕西", "西安"),
    ("中国科学院兰州化学物理研究所", "甘肃", "兰州"),
    ("中国科学院西北生态环境资源研究院", "甘肃", "兰州"),
    ("中国科学院新疆生态与地理研究所", "新疆", "乌鲁木齐"),
    ("中国科学院新疆理化技术研究所", "新疆", "乌鲁木齐"),
    ("中国科学院东北地理与农业生态研究所", "吉林", "长春"),
    ("中国科学院沈阳应用生态研究所", "辽宁", "沈阳"),
    ("中国科学院沈阳自动化研究所", "辽宁", "沈阳"),
    ("中国科学院大连化学物理研究所", "辽宁", "大连"),
    ("中国科学院合肥物质科学研究院", "安徽", "合肥"),
    ("中国科学院福建物质结构研究所", "福建", "福州"),
    ("中国科学院海洋研究所", "山东", "青岛"),
    ("中国科学院青岛生物能源与过程研究所", "山东", "青岛"),
    ("中国科学院天津工业生物技术研究所", "天津", "天津"),
    ("中国科学院重庆绿色智能技术研究院", "重庆", "重庆"),
    ("中国科学院深圳先进技术研究院", "广东", "深圳"),
    # --- 地方社科院 ---
    ("天津市社会科学院", "天津", "天津"),
    ("河北省社会科学院", "河北", "石家庄"),
    ("山西省社会科学院", "山西", "太原"),
    ("辽宁省社会科学院", "辽宁", "沈阳"),
    ("吉林省社会科学院", "吉林", "长春"),
    ("江苏省社会科学院", "江苏", "南京"),
    ("浙江省社会科学院", "浙江", "杭州"),
    ("安徽省社会科学院", "安徽", "合肥"),
    ("福建省社会科学院", "福建", "福州"),
    ("江西省社会科学院", "江西", "南昌"),
    ("山东省社会科学院", "山东", "济南"),
    ("河南省社会科学院", "河南", "郑州"),
    ("湖南省社会科学院", "湖南", "长沙"),
    ("广西社会科学院", "广西", "南宁"),
    ("海南省社会科学院", "海南", "海口"),
    ("重庆市社会科学院", "重庆", "重庆"),
    ("贵州省社会科学院", "贵州", "贵阳"),
    ("云南省社会科学院", "云南", "昆明"),
    ("陕西省社会科学院", "陕西", "西安"),
    ("甘肃省社会科学院", "甘肃", "兰州"),
    ("宁夏社会科学院", "宁夏", "银川"),
    ("新疆社会科学院", "新疆", "乌鲁木齐"),
    # --- 部委 / 行业研究院 ---
    ("中国气象科学研究院", "北京", "北京"),
    ("中国计量科学研究院", "北京", "北京"),
    ("中国信息通信研究院", "北京", "北京"),
    ("中国水产科学研究院", "北京", "北京"),
    ("中国热带农业科学院", "海南", "海口"),
    ("中国航天科技集团第一研究院", "北京", "北京"),
    ("中国航天科技集团第五研究院", "北京", "北京"),
    ("中国电子科技集团电子科学研究院", "北京", "北京"),
]

REGION_MAP = {
    "北京": "华北", "天津": "华北", "河北": "华北", "山西": "华北", "内蒙古": "华北",
    "辽宁": "东北", "吉林": "东北", "黑龙江": "东北",
    "上海": "华东", "江苏": "华东", "浙江": "华东", "安徽": "华东", "福建": "华东",
    "江西": "华东", "山东": "华东",
    "河南": "华中", "湖北": "华中", "湖南": "华中",
    "广东": "华南", "广西": "华南", "海南": "华南",
    "重庆": "西南", "四川": "西南", "贵州": "西南", "云南": "西南", "西藏": "西南",
    "陕西": "西北", "甘肃": "西北", "青海": "西北", "宁夏": "西北", "新疆": "西北",
}


def normalize(name: str) -> str:
    """规范化院校名称：全角括号转半角，去除空白字符。"""
    return name.replace("（", "(").replace("）", ")").replace(" ", "").strip()


def judge_level(project_985: str, project_211: str, name: str) -> str:
    if project_985.strip() == "1":
        return "985"
    if project_211.strip() == "1":
        return "211"
    if normalize(name) in SHUANGYILIU:
        return "双一流"
    return "双非"


def judge_type(name: str) -> str:
    """根据院校名称判断院校类型。"""
    n = name
    if "师范" in n:
        return "师范"
    if any(k in n for k in ("医科", "医药", "中医药", "医学", "药科", "医学院")):
        return "医药"
    if any(k in n for k in ("农林", "农业", "林业", "畜牧", "水产")):
        return "农林"
    if any(k in n for k in ("财经", "金融", "经济", "经贸", "工商", "商业")):
        return "财经"
    if any(k in n for k in ("政法", "公安", "警察", "司法", "警官")):
        return "政法"
    if any(k in n for k in ("外国语", "语言", "外语")):
        return "语言"
    if any(k in n for k in ("艺术", "音乐", "美术", "戏剧", "舞蹈", "传媒", "电影", "戏曲")):
        return "艺术"
    if "体育" in n:
        return "体育"
    if "民族" in n:
        return "民族"
    if any(k in n for k in ("军事", "国防", "陆军", "海军", "空军", "武警", "火箭军", "战略支援", "军医")):
        return "军事"
    if any(k in n for k in (
            "理工", "工业", "科技", "工程", "交通", "邮电", "电力", "建筑", "化工", "航空",
            "航天", "矿业", "石油", "地质", "信息", "电子", "机械", "冶金", "纺织", "轻工",
            "水利", "海事", "铁道", "车辆", "船舶", "能源", "材料", "测绘", "统计", "计量", "海关")):
        return "理工"
    return "综合"


def judge_region(province: str) -> str:
    return REGION_MAP.get(province, "")


def is_zhiye(row: dict) -> bool:
    """判断是否为职业本科院校（非研究生招生主力，排除）。职业师范类保留。"""
    nm = normalize(row["name"])
    if "职业技术师范" in nm or "职业师范" in nm:
        return False
    if "职业技术大学" in nm or "职业大学" in nm:
        return True
    return False


def load_csv_universities() -> list:
    """从开源 CSV 中筛选待插入的公办本科院校。"""
    if not os.path.exists(CSV_PATH):
        print(f"[错误] CSV 文件不存在: {CSV_PATH}")
        return []

    with open(CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    selected = []
    for r in rows:
        if r.get("nature", "").strip() != "公办":
            continue
        nm = normalize(r["name"])
        if is_zhiye(r):
            continue
        selected.append({
            "name": nm,
            "province": r["province"].strip(),
            "city": r["city"].strip(),
            "level": judge_level(r.get("project_985", ""), r.get("project_211", ""), nm),
            "type": judge_type(nm),
            "region": judge_region(r["province"].strip()),
            "official_url": r.get("website", "").strip(),
            "tags": [],
            "data_source": "open_dataset",
        })
    return selected


def load_ky_universities() -> list:
    """生成科研院所插入数据。"""
    result = []
    for name, province, city in KY_LIST:
        result.append({
            "name": name,
            "province": province,
            "city": city,
            "level": "双非",
            "type": "科研院所",
            "region": judge_region(province),
            "official_url": "",
            "tags": [],
            "data_source": "manual",
        })
    return result


def main():
    # 1. 读取现有库院校名称（规范化后），用于去重
    conn = psycopg.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT name FROM kaoyan_schools")
    existing_names = set()
    for (name,) in cur.fetchall():
        existing_names.add(normalize(name))
    print(f"[1] 当前库院校数: {len(existing_names)}")

    # 2. 构建待插入数据
    universities = load_csv_universities()
    ky = load_ky_universities()
    candidates = universities + ky
    print(f"[2] 开源CSV筛选公办本科: {len(universities)} 所, 科研院所: {len(ky)} 所, 合计候选: {len(candidates)} 所")

    # 3. 去重（与现有库 + 候选内部去重）
    seen = set(existing_names)
    to_insert = []
    skipped = 0
    for item in candidates:
        nm = normalize(item["name"])
        if nm in seen:
            skipped += 1
            continue
        seen.add(nm)
        to_insert.append(item)
    print(f"[3] 去重后待插入: {len(to_insert)} 所, 跳过已存在: {skipped} 所")

    # 4. 幂等插入
    sql = """
        INSERT INTO kaoyan_schools
            (name, level, province, city, logo_url, intro, tags, official_url,
             data_source, type, region, created_at, updated_at, enabled, deleted_at)
        VALUES
            (%(name)s, %(level)s, %(province)s, %(city)s, NULL, NULL, %(tags)s::jsonb,
             %(official_url)s, %(data_source)s, %(type)s, %(region)s, now(), now(), TRUE, NULL)
        ON CONFLICT (name) DO NOTHING
    """
    inserted = 0
    for item in to_insert:
        try:
            cur.execute(sql, {
                "name": item["name"],
                "level": item["level"],
                "province": item["province"],
                "city": item["city"],
                "tags": json.dumps(item["tags"], ensure_ascii=False),
                "official_url": item["official_url"] or None,
                "data_source": item["data_source"],
                "type": item["type"],
                "region": item["region"],
            })
            inserted += 1
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            continue
        except Exception as e:
            conn.rollback()
            print(f"[错误] 插入失败 {item['name']}: {e}")
            raise
    conn.commit()
    print(f"[4] 实际插入: {inserted} 所")

    # 5. 验证
    cur.execute("SELECT count(*) FROM kaoyan_schools")
    total = cur.fetchone()[0]
    print(f"\n===== 验证结果 =====")
    print(f"kaoyan_schools 总行数: {total}")

    cur.execute("""
        SELECT province, count(*) FROM kaoyan_schools
        GROUP BY province ORDER BY count(*) DESC
    """)
    print("\n省份分布:")
    for province, cnt in cur.fetchall():
        print(f"  {province}: {cnt}")

    cur.execute("""
        SELECT name, count(*) FROM kaoyan_schools
        GROUP BY name HAVING count(*) > 1
    """)
    dups = cur.fetchall()
    print(f"\n重复名称检查: {len(dups)} 条重复")
    for d in dups:
        print("  ", d)

    # 新增院校数据来源统计
    cur.execute("""
        SELECT data_source, count(*) FROM kaoyan_schools
        GROUP BY data_source ORDER BY count(*) DESC
    """)
    print("\ndata_source 分布:")
    for ds, cnt in cur.fetchall():
        print(f"  {ds}: {cnt}")

    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()