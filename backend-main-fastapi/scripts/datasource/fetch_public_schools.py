# -*- coding: utf-8 -*-
"""抓取研招网官方《具有推荐免试攻读硕士研究生资格院校名单》→ 公办院校底表。

来源: https://yz.chsi.com.cn/kyzx/kp/202509/20250918/2293427403.html
      （中国研究生招生信息网，教育部权威发布）
特点: 434 所院校，含「单位名称 + 所在省市」，全部为公办高校（具推免资格即具研究生招生资格）。
用法: python fetch_public_schools.py
输出: public_schools.json
"""
import json, re, ssl, urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
SSL_CTX = ssl.create_default_context(); SSL_CTX.check_hostname = False; SSL_CTX.verify_mode = ssl.CERT_NONE
URL = "https://yz.chsi.com.cn/kyzx/kp/202509/20250918/2293427403.html"
OUT = Path(__file__).parent / "public_schools.json"


def main():
    req = urllib.request.Request(URL, headers=UA)
    html = urllib.request.urlopen(req, timeout=40, context=SSL_CTX).read().decode("utf-8", "ignore")
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    out = []
    for r in rows:
        cells = [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)]
        if len(cells) >= 2 and cells[0] and cells[0] != "单位名称":
            out.append({"name": cells[0], "province": cells[1]})
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"抓取 {len(out)} 所院校 → {OUT}")
    from collections import Counter
    print("省市分布:", len(set(x["province"] for x in out)), "个省市")
    print("前5:", out[:5])


if __name__ == "__main__":
    main()
