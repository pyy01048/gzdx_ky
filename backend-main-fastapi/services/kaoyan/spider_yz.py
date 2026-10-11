# -*- coding: utf-8 -*-
"""研招网爬虫（适配新版接口）—— C1 完整爬取 + C2 合规与断点续爬。

接口: https://yz.chsi.com.cn/zsml/rs/dws.do
参数: ssdm(省份), yjxkdm(学科门类), xxfs(学习方式1=全日制), pageno(页码)
返回: JSON, 数据在 msg.list

使用方式：
    cd backend-main-fastapi
    # 试点3省
    python -c "from services.kaoyan.spider_yz import crawl; crawl()"
    # 指定省份
    python -c "from services.kaoyan.spider_yz import crawl; crawl(province_codes=['11','12','13'])"
    # 全量
    python -c "from services.kaoyan.spider_yz import crawl; crawl(all_provinces=True)"
"""
import re, time, random, json, ssl, urllib.request, urllib.parse
from pathlib import Path

YZ_BASE = "https://yz.chsi.com.cn"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
CHECKPOINT_FILE = Path(__file__).parent / "checkpoint.json"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# 省份代码→名称
PROVINCES = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏",
    "65": "新疆",
}

# 学科门类代码→名称
SUBJECT_CATEGORIES = {
    "01": "哲学", "02": "经济学", "03": "法学", "04": "教育学",
    "05": "文学", "06": "历史学", "07": "理学", "08": "工学",
    "09": "农学", "10": "医学", "11": "军事学", "12": "管理学",
    "13": "艺术学",
}


def fetch(url, retries=3, data=None, method="GET"):
    """带重试的请求。"""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA, method=method)
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  [retry {i+1}/{retries}] {url[:60]}: {e}")
            time.sleep(random.uniform(2, 5))
    return ""


def polite_delay():
    """C2: 2-5s 随机延迟。"""
    time.sleep(random.uniform(2, 5))


ROBOTS_CACHE = {}


def check_robots(force=False):
    """C2: 检查研招网 robots.txt 合规性。

    返回 True 表示允许采集；返回 False 表示 robots.txt 明确禁止，
    此时不应继续爬取。结果带缓存（进程内一次抓取）。
    """
    global ROBOTS_CACHE
    if ROBOTS_CACHE and not force:
        return ROBOTS_CACHE["allowed"]
    url = f"{YZ_BASE}/robots.txt"
    body = fetch(url, retries=2)
    allowed = True
    robots_text = ""
    if body:
        robots_text = body
        # 简单解析：逐条 User-agent 分组，检查针对 * 或通用 UA 的 Disallow
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        current_ua = None
        disallows = []
        for ln in lines:
            low = ln.lower()
            if low.startswith("user-agent:"):
                current_ua = low.split(":", 1)[1].strip()
            elif low.startswith("disallow:") and current_ua in ("*", "default", ""):
                path = low.split(":", 1)[1].strip()
                disallows.append(path)
        # 研招网关键路径检查
        for d in disallows:
            if d and (d == "/" or "/zsml/" in d or d.startswith("/zsml")):
                allowed = False
                break
    ROBOTS_CACHE = {"allowed": allowed, "text": robots_text}
    if not allowed:
        print("[ROBOTS] robots.txt 禁止采集 zsml 路径，停止爬取")
    else:
        print(f"[ROBOTS] robots.txt 检查通过（{len(robots_text)} 字节）")
    return allowed


def load_checkpoint():
    """C2: 加载断点续爬记录。"""
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"completed": []}


def save_checkpoint(cp):
    """C2: 保存断点续爬记录。"""
    CHECKPOINT_FILE.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_schools(province_code, subject_code="08", max_pages=50):
    """C1: 抓取某省某学科的全部院校。"""
    schools = []
    for page in range(1, max_pages + 1):
        params = urllib.parse.urlencode({
            "ssdm": province_code,
            "yjxkdm": subject_code,
            "xxfs": "1",
            "pageno": str(page),
        })
        url = f"{YZ_BASE}/zsml/rs/dws.do?{params}"
        body = fetch(url)
        if not body:
            break
        try:
            j = json.loads(body)
            msg = j.get("msg", {})
            page_list = msg.get("list", [])
            if not page_list:
                break
            schools.extend(page_list)
            total_page = msg.get("totalPage", 1)
            if page >= total_page:
                break
            polite_delay()
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  [WARN] 解析失败 page={page}: {e}")
            break
    return schools


def crawl(province_codes=None, subject_codes=None, all_provinces=False, reset_checkpoint=False):
    """C1+C2: 爬取研招网院校专业目录。"""
    from database import SessionLocal
    from models import KaoyanSchool

    # C2: 断点续爬
    cp = {"completed": []} if reset_checkpoint else load_checkpoint()

    # C2: robots.txt 合规检查
    if not check_robots():
        print("[C2] robots.txt 禁止采集，放弃本次爬取")
        return {"success": False, "reason": "robots.txt 禁止采集"}

    if all_provinces:
        province_codes = list(PROVINCES.keys())
    elif not province_codes:
        province_codes = list(PROVINCES.keys())[:3]  # 默认3省

    if not subject_codes:
        subject_codes = ["08"]  # 工学

    db = SessionLocal()
    try:
        total_before = db.query(KaoyanSchool).count()
        print(f"开始爬取：{len(province_codes)} 省 × {len(subject_codes)} 学科")
        print(f"当前已有 {total_before} 所院校")

        for pc in province_codes:
            for sc in subject_codes:
                key = f"{pc}_{sc}"
                if key in cp["completed"]:
                    print(f"  跳过已完成: {PROVINCES.get(pc, pc)} {SUBJECT_CATEGORIES.get(sc, sc)}")
                    continue

                print(f"\n爬取: {PROVINCES.get(pc, pc)} - {SUBJECT_CATEGORIES.get(sc, sc)}")
                schools = fetch_schools(pc, sc)
                print(f"  获取 {len(schools)} 所院校")

                added = 0
                for item in schools:
                    name = item.get("dwmc", "").strip()
                    code = item.get("dwdm")
                    province = PROVINCES.get(pc, item.get("szss"))
                    if not name:
                        continue
                    # 去重
                    existing = db.query(KaoyanSchool).filter(KaoyanSchool.name == name).first()
                    if not existing:
                        school = KaoyanSchool(
                            name=name,
                            province=province,
                            official_url=item.get("schId"),
                        )
                        db.add(school)
                        added += 1

                db.commit()
                print(f"  新增 {added} 所")
                cp["completed"].append(key)
                save_checkpoint(cp)

        total_after = db.query(KaoyanSchool).count()
        print(f"\n全部完成。新增 {total_after - total_before} 所，共 {total_after} 所")
    finally:
        db.close()


if __name__ == "__main__":
    crawl()
