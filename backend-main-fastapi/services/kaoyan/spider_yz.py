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
import logging
import re, time, random, json, ssl, urllib.request, urllib.parse
from pathlib import Path

YZ_BASE = "https://yz.chsi.com.cn"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

# 断点续爬状态落在 data/ 运行时目录，**不放在包目录**。
# 历史故障（2026-10-18）：部署包夹带一份全量 completed 的 checkpoint.json，
# 全新库 0 所院校，爬虫却把 31 省 × 13 门类全部当"跳过已完成"，
# 采集永远返回 0 行、毫无报错。运行时状态必须与代码分离，
# 部署只更新代码，不覆盖状态。
SPIDER_STATE_DIR = Path(__file__).resolve().parents[2] / "data" / "spider_state"


def _checkpoint_path() -> Path:
    SPIDER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return SPIDER_STATE_DIR / "yz_checkpoint.json"

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


def load_checkpoint(db_session=None):
    """C2: 加载断点续爬记录。

    Args:
        db_session: 可选 SQLAlchemy 会话。传入时启用自愈校验。

    自愈（2026-10-18 生产故障复盘）：checkpoint 是运行时状态，可能因
    部署包夹带而"声称已完成"但库里其实一所院校都没有——症状是采集
    永远 0 行且不报错。此时以库为准：院校表为空即重置 checkpoint，
    保证"库空即可重爬"，不依赖人工去删文件。
    """
    path = _checkpoint_path()
    cp = {"completed": []}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("completed"), list):
                cp = data
        except Exception as _exc:  # noqa: BLE001
            # 不静默：保留「不阻塞主流程」语义，仅补留痕
            logging.getLogger(__name__).warning(
                '%s 处异常已忽略（不阻塞主流程）: %s', __name__, str(_exc)[:200]
            )
    if cp.get("completed") and db_session is not None:
        try:
            from models import KaoyanSchool
            if db_session.query(KaoyanSchool).count() == 0:
                logging.getLogger(__name__).warning(
                    "checkpoint 声称已完成 %d 项但院校库为空，判定过期并重置（以库为准）",
                    len(cp["completed"]),
                )
                cp = {"completed": []}
                save_checkpoint(cp)
        except Exception as _exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "checkpoint 自愈检查失败（不阻塞主流程）: %s", str(_exc)[:200]
            )
    return cp


def save_checkpoint(cp):
    """C2: 保存断点续爬记录。"""
    path = _checkpoint_path()
    path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")


# 关键词穷举池（规避"每页10条且匿名翻页失效"）。
# 空串先取第 1 页基线，再按"大学/学院/研究所"等机构后缀 + 省市名 + 校名特征字拆分结果集。
# 覆盖约 60 个关键词：机构后缀、省级行政区、校名高频词。
KEYWORDS = [
    # —— 机构类型后缀 ——
    "", "大学", "学院", "研究所", "科学院", "研究院", "中心", "学部", "分校", "校区",
    # —— 省级行政区名（弥补部分院校名称含地名）——
    "北京", "天津", "河北", "山西", "内蒙", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    # —— 校名高频前缀/词 ——
    "中国", "中华", "国家", "国防", "人民",
    # —— 行业特征词 ——
    "工业", "理工", "科技", "师范", "农业", "林业", "医科", "医药", "中医药", "财经",
    "政法", "交通", "航空", "航天", "邮电", "电子", "海事", "海洋", "石油", "地质",
    "矿业", "电力", "水利", "建筑", "民族", "外国语", "国际", "对外", "铁道", "工程",
]


def fetch_schools(province_code, subject_code="08", max_pages=50, keywords=None):
    """C1: 抓取某省某学科的全部院校（关键词穷举版）。

    背景：研招网新版接口 `zsml/rs/dws.do` 每页固定返回 10 条，且匿名翻页失效
    （pageno 任意值均返回第 1 页；start= 参数会触发"请登录"）。但 `dwmc`
    （单位名称模糊搜索）参数**匿名可用且有效**，故改为关键词穷举：对每个
    关键词请求一次 pageno=1，按 dwdm（单位代码）去重合并，即可突破 10 条上限。

    Args:
        province_code: 省份代码，如 "11"（北京）。
        subject_code: 学科门类代码，如 "08"（工学）。保留以兼容旧调用。
        max_pages: 兼容旧调用保留；穷举模式下不再翻页，仅记录为摘要字段。
        keywords: 关键词列表；为空时使用内置 KEYWORDS 池。

    Returns:
        list[dict]: 去重后的院校列表，每项含 dwdm/dwmc/szss/zhx/bs/syl 等原始字段。
    """
    kw_list = list(keywords) if keywords else list(KEYWORDS)
    merged = {}          # dwdm -> 原始 item（保序，首次出现为准）
    no_code = []         # 无 dwdm 的兜底条目（极少数），按名称去重
    seen_no_code = set()
    fail_streak = 0      # 连续失败计数，避免网络异常时死循环

    for i, kw in enumerate(kw_list):
        params = {
            "ssdm": province_code,
            "xxfs": "1",
            "pageno": "1",
        }
        if kw:
            params["dwmc"] = kw
        # 注意：不再传 yjxkdm；该接口对学科筛选无效，传了反而可能干扰结果集。
        url = f"{YZ_BASE}/zsml/rs/dws.do?{urllib.parse.urlencode(params)}"
        body = fetch(url, retries=2)
        if not body:
            fail_streak += 1
            # 网络异常：连续 2 个关键词均失败则提前退出（不做无意义重试）
            if fail_streak >= 2:
                print(f"  [WARN] 连续 {fail_streak} 次请求失败，提前结束本次穷举")
                break
            continue
        fail_streak = 0
        try:
            j = json.loads(body)
        except json.JSONDecodeError:
            # 非 JSON（如"请登录"/"参数错误"页面），跳过该关键词，不计失败
            continue
        msg = j.get("msg")
        if not isinstance(msg, dict):
            # msg 非 dict 表示接口返回异常（如未登录），跳过
            continue
        page_list = msg.get("list") or []
        for it in page_list:
            dm = (it.get("dwdm") or "").strip()
            name = (it.get("dwmc") or "").strip()
            if dm:
                if dm not in merged:
                    merged[dm] = it
            elif name and name not in seen_no_code:
                # 极少数条目缺 dwdm，按名称兜底去重
                seen_no_code.add(name)
                no_code.append(it)
        # 礼貌延迟：沿用 C2 的 2-5s 随机间隔
        polite_delay()

    result = list(merged.values()) + no_code
    print(f"  [穷举] 省={province_code} 关键词={len(kw_list)} 去重后={len(result)}")
    return result


def crawl(province_codes=None, subject_codes=None, all_provinces=False, reset_checkpoint=False):
    """C1+C2: 爬取研招网院校专业目录。"""
    from database import SessionLocal
    from models import KaoyanSchool

    db = SessionLocal()
    try:
        # C2: 断点续爬（带 db 以启用"库空即重置"自愈）
        cp = {"completed": []} if reset_checkpoint else load_checkpoint(db)

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
                        # 注意：研招网接口返回的 schId 是「学校数字ID」，不是官网 URL。
                        # 历史 bug：曾把 schId 直接写进 official_url，导致官网字段被
                        # 数字 ID 污染（前端点开是死链）。研招网不提供官网地址，
                        # 故 official_url 留空，待后续按院校名回填真实官网。
                        school = KaoyanSchool(
                            name=name,
                            province=province,
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
