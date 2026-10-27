# -*- coding: utf-8 -*-
"""研招网招生单位采集（关键词穷举版）。

背景：研招网新版接口 `zsml/rs/dws.do` 每页固定返回 10 条，翻页需要登录态（返回"请登录"）。
但 `dwmc`（单位名称模糊搜索）参数**匿名可用**，故用关键词穷举拆分结果集，规避登录。

用法:
  python fetch_yz_units2.py                 # 全量 31 省
  python fetch_yz_units2.py --province 52   # 只抓贵州
  python fetch_yz_units2.py --resume        # 在已有 yz_units.json 基础上续补

合规: 请求间隔 0.4~0.9s，带 UA，失败跳过；逐省落盘，可中断续跑。
输出: yz_units.json（含 dwdm 单位代码 / dwmc 名称 / province / zhx 自划线 / bs 博士点 / syl 双一流）
"""
import json, ssl, sys, time, random, urllib.parse, urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
SSL_CTX = ssl.create_default_context(); SSL_CTX.check_hostname = False; SSL_CTX.verify_mode = ssl.CERT_NONE
BASE = "https://yz.chsi.com.cn/zsml/rs/dws.do"
OUT = Path(__file__).parent / "yz_units.json"

PROVINCES = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏", "65": "新疆",
}

# 关键词穷举池：覆盖"大学/学院/研究所"及常见校名特征字
KEYWORDS = [
    "", "大学", "学院", "研究所", "科学院", "研究院", "中心", "学部", "分校", "校区",
    "北京", "天津", "河北", "山西", "内蒙", "辽宁", "吉林", "黑龙江", "上海", "江苏",
    "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "广西",
    "海南", "重庆", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
    "中国", "中华", "国家", "国防", "人民",
    "工业", "理工", "科技", "师范", "农业", "林业", "医科", "医药", "中医药", "财经",
    "政法", "交通", "航空", "航天", "邮电", "电子", "海事", "海洋", "石油", "地质",
    "矿业", "电力", "水利", "建筑", "民族", "外国语", "国际", "对外", "铁道", "工程",
]


def fetch(ssdm, dwmc=""):
    url = f"{BASE}?ssdm={ssdm}&xxfs=1&pageno=1"
    if dwmc:
        url += "&dwmc=" + urllib.parse.quote(dwmc)
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=12, context=SSL_CTX) as r:
                j = json.loads(r.read().decode("utf-8", "ignore"))
            m = j.get("msg")
            if isinstance(m, dict):
                return m.get("list") or []
            return []  # 非 dict（如"参数错误"/"请登录"）
        except Exception:
            time.sleep(0.8)
    return []


def crawl_province(ssdm, name):
    got = {}
    for kw in KEYWORDS:
        for it in fetch(ssdm, kw):
            dm = it.get("dwdm")
            if dm:
                got[dm] = {
                    "dwdm": dm, "dwmc": it.get("dwmc"),
                    "province_code": it.get("szssm"), "province": it.get("szss") or name,
                    "zhx": it.get("zhx"), "bs": it.get("bs"), "syl": it.get("syl"),
                }
        time.sleep(random.uniform(0.4, 0.9))
    return got


def main():
    args = sys.argv[1:]
    provs = PROVINCES
    if "--province" in args:
        c = args[args.index("--province") + 1]
        provs = {c: PROVINCES.get(c, c)}

    all_units = {}
    if OUT.exists():
        try:
            for u in json.loads(OUT.read_text(encoding="utf-8")):
                if u.get("dwdm"):
                    all_units[u["dwdm"]] = u
            print(f"续跑：已有 {len(all_units)} 所", flush=True)
        except Exception:
            pass

    for code, name in provs.items():
        got = crawl_province(code, name)
        for k, v in got.items():
            all_units[k] = v
        OUT.write_text(json.dumps(list(all_units.values()), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{code} {name}] 本省 {len(got)} → 累计 {len(all_units)}", flush=True)

    print(f"\n完成 {len(all_units)} 所 → {OUT}", flush=True)


if __name__ == "__main__":
    main()
