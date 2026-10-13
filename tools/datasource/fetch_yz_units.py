# -*- coding: utf-8 -*-
"""从研招网新版接口全量拉取招生单位底表（构建公办院校全集）。

接口: https://yz.chsi.com.cn/zsml/rs/dws.do?ssdm={省码}&xxfs=1&pageno={页码}
字段: dwdm 单位代码 / dwmc 名称 / szss 省市 / zhx 自划线 / bs 博士点 / syl 双一流
用法: python fetch_yz_units.py [--province 52]
合规: 间隔 1.2~2s，UA，重试 2 次，逐省落盘（中断可续）。
"""
import json, ssl, sys, time, random, urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
SSL_CTX = ssl.create_default_context(); SSL_CTX.check_hostname = False; SSL_CTX.verify_mode = ssl.CERT_NONE
OUT = Path(__file__).parent / "yz_units.json"

PROVINCES = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏", "65": "新疆",
}


def fetch(url, retries=2):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            print(f"   [retry {i+1}] {e}", flush=True)
            time.sleep(1.2)
    return None


def crawl_province(ssdm):
    out, page = [], 1
    while page <= 40:
        url = f"https://yz.chsi.com.cn/zsml/rs/dws.do?ssdm={ssdm}&xxfs=1&pageno={page}"
        j = fetch(url)
        if not j:
            break
        lst = (j.get("msg") or {}).get("list") or []
        if not lst:
            break
        for it in lst:
            out.append({"dwdm": it.get("dwdm"), "dwmc": it.get("dwmc"),
                        "province_code": it.get("szssm"), "province": it.get("szss") or PROVINCES.get(ssdm),
                        "zhx": it.get("zhx"), "bs": it.get("bs"), "syl": it.get("syl")})
        if len(lst) < 10:
            break
        page += 1
        time.sleep(random.uniform(1.2, 2.0))
    return out


def main():
    args = sys.argv[1:]
    provs = PROVINCES
    if "--province" in args:
        c = args[args.index("--province") + 1]
        provs = {c: PROVINCES.get(c, c)}
    all_units = {}
    if OUT.exists():  # 续跑：合并已有
        try:
            for u in json.loads(OUT.read_text(encoding="utf-8")):
                if u.get("dwdm"): all_units[u["dwdm"]] = u
            print(f"续跑：已有 {len(all_units)} 所", flush=True)
        except Exception:
            pass
    for code, name in provs.items():
        print(f"[{code} {name}] ...", flush=True)
        units = crawl_province(code)
        for u in units:
            if u["dwdm"]: all_units[u["dwdm"]] = u
        OUT.write_text(json.dumps(list(all_units.values()), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"   [{name}] +{len(units)} → 累计 {len(all_units)}", flush=True)
        time.sleep(random.uniform(1.0, 1.8))
    print(f"\n完成 {len(all_units)} 所 → {OUT}", flush=True)


if __name__ == "__main__":
    main()
