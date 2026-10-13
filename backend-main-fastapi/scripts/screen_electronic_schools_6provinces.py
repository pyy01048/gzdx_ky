# -*- coding: utf-8 -*-
"""6 省（云南/贵州/广西/广东/四川/重庆）电子电气通信光学强校候选池筛选。

用户原话：「重点关注云南、贵州、广西、广东、四川、重庆几个省的重点做，
并且院校是电子电气通信光学强的院校」。

筛选口径（三级，全部来自实测，不引入外部臆测）
------------------------------------------------
A. **level 硬门槛**：985 / 211 / 双一流 全部入选，不因关键词漏掉。
B. **intro 关键词补充**：在 `intro` 里匹配电子信息类学科特征词。
   ⚠️ 实测发现 `tags` 字段只有 `{"yz_schid": "..."}` 一个研招网 ID，
   **不含任何学科/行业关键词**，所以 tags 不能用作筛选依据
   （这一点和早期「level 回填」诊断是同一个结论）。
C. **已知行业强校兜底**：用一份人工核对过的校名清单兜底
   （邮电/电子/理工/信息类行业校），即使 level 为 NULL 也纳入。

本脚本**只读**，不写库、不抓取。
"""
from __future__ import annotations

import re
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

DB = r"D:\平台\database\kaoyan.db"

PROVINCES = ["云南", "贵州", "广西", "广东", "四川", "重庆"]

#: 强信号词：直接指向电子信息类学科主业。
STRONG_KW = ["电子", "电气", "通信", "光电", "光学", "邮电", "半导体", "集成电路", "微电子"]
#: 弱信号词：「信息」单独出现既可能是「信息科学与工程学院」（真学科），
#: 也可能是「研究生招生信息网」「详细信息」（噪声）。已剔噪后仍只剩「信息」的，
#: 归入「待人工确认」，不直接断言为电子信息强校。
WEAK_KW = ["信息"]
KW = STRONG_KW + WEAK_KW

#: intro 关键词的**噪声上下文**：这些词组里的关键词与学科实力无关，
#: 必须剔除，否则会把「电子图书」「研究生招生信息网」当成电子信息强校。
#: 实测误判实例：遵义医科大学命中「电子」实为「电子馆藏133万余册」；
#: 西南科技大学命中「电子」实为「电子图书798万余册」；
#: 西南政法大学命中「信息」实为 intro 是「请点击：西南政法大学院校简…」的截断模板。
NOISE_CTX = [
    "电子图书", "电子馆藏", "电子文献", "电子资源",
    "招生信息网", "信息交互", "信息化建设", "信息公开",
    "信息管理", "信息技术应用", "信息工作",
    # 西南政法大学的 intro 是被截断的导航模板（"请点击：西南政法大学院校简介"），
    # 不是学校介绍，整段剔除。
    "请点击",
]

#: 学科语境后缀：关键词只有落进这些语境才算「学科实力信号」。
DISCIPLINE_CTX = ["学院", "工程", "科学", "技术", "专业", "学科", "系", "实验室",
                  "研究院", "中心", "一级学科", "优势", "特色", "重点", "援建",
                  "世界一流学科", "学位"]

#: 行业强校兜底清单（校名精确匹配）。level 为 NULL 也纳入。
#: 收录依据：① 校名即行业属性（电子/邮电/信息）② 工信/电子信息类行业强校。
#: 已剔除早期误收的师范/体育/美术类院校（四川师范大学、云南师范大学等）。
KNOWN_STRONG = {
    "桂林电子科技大学", "桂林理工大学", "成都信息工程大学", "重庆邮电大学",
    "重庆理工大学", "广东工业大学", "深圳大学", "南方科技大学",
    "昆明理工大学", "西南科技大学", "东莞理工学院",
}

#: 已知非电子信息类的名校（医/法/农/财/师范/综合）。
#: 按用户「level 硬门槛」仍入选候选池，但标注为「名校但非电子信息」，
#: 供用户决定是否纳入关注清单。
NON_ICT_ELITE = {
    "广州医科大学", "广州中医药大学", "南方医科大学", "遵义医科大学",
    "贵州医科大学", "广西医科大学", "桂林医科大学", "昆明医科大学",
    "重庆医科大学", "成都中医药大学", "贵州中医药大学", "广西中医药大学",
    "云南中医药大学", "广东药科大学", "广东医科大学", "右江民族医学院",
    "陆军军医大学", "西南政法大学", "西南财经大学", "四川农业大学",
    "华南农业大学", "华南师范大学", "云南师范大学", "贵州师范大学",
    "广西师范大学", "南宁师范大学", "重庆师范大学", "西华师范大学",
    "四川师范大学", "云南民族大学", "贵州民族大学", "广西民族大学",
    "西南民族大学", "西藏大学", "青海大学",
}


def kw_hits(intro: str | None) -> tuple[list[str], list[str]]:
    """返回 (强信号词, 弱信号词)，已剔除行政/藏书类噪声上下文。"""
    if not intro:
        return [], []
    text = intro
    for noise in NOISE_CTX:
        text = text.replace(noise, "")
    strong, weak = [], []
    for k in KW:
        for m in re.finditer(re.escape(k), text):
            window = text[max(0, m.start() - 6):m.end() + 8]
            if any(ctx in window for ctx in DISCIPLINE_CTX):
                (strong if k in STRONG_KW else weak).append(k)
                break
    return strong, weak


def load(conn: sqlite3.Connection) -> list[dict]:
    # 按用户给的省份顺序排序（云南/贵州/广西/广东/四川/重庆），
    # 用 CASE 而非字符串排序，保证输出顺序稳定可读。
    order_case = "CASE s.province " + " ".join(
        f"WHEN ? THEN {i}" for i in range(len(PROVINCES))) + " ELSE 99 END"
    rows = conn.execute(
        "SELECT s.id, s.name, s.province, s.city, s.level, s.type, s.tags, s.intro, "
        "       s.official_url, "
        "       (SELECT COUNT(*) FROM kaoyan_notices n WHERE n.school_id = s.id) AS ncnt "
        "FROM kaoyan_schools s "
        f"WHERE s.province IN ({','.join('?' * len(PROVINCES))}) "
        f"ORDER BY {order_case}, s.id",
        tuple(PROVINCES) + tuple(PROVINCES),
    ).fetchall()
    keys = ["id", "name", "province", "city", "level", "type", "tags", "intro",
            "official_url", "notice_cnt"]
    return [dict(zip(keys, r)) for r in rows]


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        schools = load(conn)
    finally:
        conn.close()

    print("=" * 78)
    print("6 省院校总览")
    print("=" * 78)
    by_prov: dict[str, list[dict]] = {p: [] for p in PROVINCES}
    for s in schools:
        by_prov[s["province"]].append(s)
    for p in PROVINCES:
        lst = by_prov[p]
        elite = [s for s in lst if s["level"] in ("985", "211", "双一流")]
        withn = [s for s in lst if s["notice_cnt"] > 0]
        print(f"  {p:4s} 共 {len(lst):3d} 所 | 名校(985/211/双一流) {len(elite):2d} 所 "
              f"| 有通知 {len(withn):2d} 所")
    print(f"  合计 共 {len(schools)} 所 | 名校 "
          f"{sum(1 for s in schools if s['level'] in ('985','211','双一流'))} 所 | "
          f"有通知 {sum(1 for s in schools if s['notice_cnt'] > 0)} 所")

    # ---- 候选池 ----
    pool = []
    for s in schools:
        reasons = []
        tier = ""
        strong, weak = kw_hits(s["intro"])
        if s["level"] in ("985", "211", "双一流"):
            if s["name"] in NON_ICT_ELITE:
                tier = "B"
                reasons.append(f"level={s['level']}（名校但非电子信息类，按硬门槛纳入）")
            else:
                tier = "A"
                reasons.append(f"level={s['level']}")
        if strong:
            if not tier:
                tier = "A"
            reasons.append("intro强信号:" + "/".join(strong[:4]))
        elif weak and not tier:
            tier = "W"
            reasons.append("intro仅弱信号「信息」，待人工确认")
        if s["name"] in KNOWN_STRONG:
            tier = "A"
            reasons.append("行业强校")
        if reasons:
            s = dict(s)
            s["reasons"] = reasons
            s["kw"] = strong + weak
            s["tier"] = tier
            pool.append(s)

    a_pool = [s for s in pool if s["tier"] == "A"]
    w_pool = [s for s in pool if s["tier"] == "W"]
    b_pool = [s for s in pool if s["tier"] == "B"]
    print()
    print("=" * 78)
    print("候选池（三级筛选结果）")
    print("=" * 78)
    print(f"  6 省共 {len(schools)} 所 → 候选池 {len(pool)} 所")
    print(f"  ├─ A 类 电子信息相关（用户核心目标）        {len(a_pool):2d} 所")
    print(f"  ├─ W 类 仅弱信号「信息」，待人工确认          {len(w_pool):2d} 所")
    print(f"  └─ B 类 名校但非电子信息（按硬门槛纳入）      {len(b_pool):2d} 所")

    zero_url = [s for s in pool if s["notice_cnt"] == 0 and s["official_url"]]
    zero_nourl = [s for s in pool if s["notice_cnt"] == 0 and not s["official_url"]]
    has_notice = [s for s in pool if s["notice_cnt"] > 0]
    print(f"  ├─ 已有通知          {len(has_notice):2d} 所")
    print(f"  ├─ 零通知 + 有URL    {len(zero_url):2d} 所  ← 用户最需要补导（有官网URL 才能手动补导）")
    print(f"  └─ 零通知 + 无URL    {len(zero_nourl):2d} 所  ← 需先补「院校→研究生院URL」映射")

    def block(title: str, lst: list[dict]) -> None:
        print()
        print("-" * 78)
        print(title)
        print("-" * 78)
        for s in lst:
            url = s["official_url"] or "-"
            is_url = url.startswith("http")
            flag = "" if is_url else "  [非URL!]"
            print(f"  {s['tier']} | {s['province']:3s} | {s['name'][:20]:22s} "
                  f"| {str(s['level'] or 'NULL'):5s} | 通知={s['notice_cnt']:<3d} "
                  f"| {url[:44]:46s}{flag}")
            print(f"        理由: {'; '.join(s['reasons'])}")

    block(f"★ A 类·零通知 + 有 official_url（最优先补导，{len([s for s in zero_url if s['tier']=='A'])} 所）",
          [s for s in zero_url if s["tier"] == "A"])
    block(f"A 类·零通知 + 无 official_url（需先补URL映射，{len([s for s in zero_nourl if s['tier']=='A'])} 所）",
          [s for s in zero_nourl if s["tier"] == "A"])
    block(f"A 类·已有通知（{len([s for s in has_notice if s['tier']=='A'])} 所）",
          [s for s in has_notice if s["tier"] == "A"])
    block(f"W 类·仅弱信号待人工确认（{len(w_pool)} 所）", w_pool)
    block(f"B 类·名校但非电子信息（零通知 {len([s for s in zero_url+zero_nourl if s['tier']=='B'])} 所 / "
          f"有通知 {len([s for s in has_notice if s['tier']=='B'])} 所）",
          [s for s in zero_url + zero_nourl + has_notice if s["tier"] == "B"])

    # ---- 可操作比例 ----
    print()
    print("=" * 78)
    print("可操作比例（决定用户手动补导工作量）")
    print("=" * 78)
    a_zero = [s for s in zero_url + zero_nourl if s["tier"] == "A"]
    a_click = [s for s in zero_url if s["tier"] == "A" and s["official_url"].startswith("http")]
    print(f"  A 类零通知候选校         {len(a_zero)} 所")
    print(f"    其中有 official_url   {len([s for s in zero_url if s['tier']=='A'])} 所")
    print(f"      └─ 真 URL 可点开     {len(a_click)} 所")
    print(f"      └─ 非 URL（数字schid）{len([s for s in zero_url if s['tier']=='A']) - len(a_click)} 所")
    print(f"    无 official_url       {len([s for s in zero_nourl if s['tier']=='A'])} 所")
    print()
    print(f"  【可操作院校数 / A类候选院校数】 = {len(a_click)} / {len(a_zero)}"
          f" = {len(a_click) / max(1, len(a_zero)) * 100:.0f}%")

    # ---- official_url 指向分析 ----
    print()
    print("=" * 78)
    print("official_url 指向分析（首页 vs 研究生院/招生网）")
    print("=" * 78)
    pats = {
        "研究生院/招生网(yjs/yz/gs/grs/yzb/graduate)":
            r"yjs|/yz|yz\.|grs|yzb|graduate",
        "学校官网首页(裸域 www.xxx.edu.cn)": r"^https?://www\.[a-z0-9-]+\.edu\.cn/?$",
        "研招网(yz.chsi.com.cn)": r"yz\.chsi\.com\.cn",
    }
    for label, pat in pats.items():
        hit = [s for s in pool if s["official_url"] and re.search(pat, s["official_url"], re.I)]
        print(f"  {label:48s} {len(hit)} 所")
    print()
    print("  指向学校官网首页（非研究生院）的候选校 —— 补导需多点一层：")
    for s in pool:
        u = s["official_url"] or ""
        if re.match(r"^https?://www\.[a-z0-9-]+\.edu\.cn/?$", u, re.I):
            print(f"    {s['tier']} {s['province']:3s} {s['name'][:20]:22s} {u}")
    print()
    print("  A 类零通知校的 official_url 逐一判定：")
    for s in a_zero:
        u = s["official_url"] or ""
        if not u:
            verdict = "无 URL —— 需补映射"
        elif not u.startswith("http"):
            verdict = f"非 URL（数字 schid '{u}'）—— 需拼成 https://yz.chsi.com.cn/sch/{u}.jhtml"
        elif re.search(r"yjs|/yz|yz\.|grs|yzb|graduate", u, re.I):
            verdict = "研究生院/招生网 —— 可直接定位通知列表页 ✓"
        elif re.match(r"^https?://www\.[a-z0-9-]+\.edu\.cn/?$", u, re.I):
            verdict = "学校官网首页 —— 需再点一层进研究生院"
        else:
            verdict = "其它"
        print(f"    {s['tier']} {s['province']:3s} {s['name'][:18]:20s} {u[:40]:42s} → {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
