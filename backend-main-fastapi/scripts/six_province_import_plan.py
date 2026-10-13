# -*- coding: utf-8 -*-
"""六省电子电气强校「补导清单」——按「用户现在就能动手」重排。

触发条件（team-lead 2026-10-12 采纳）
------------------------------------
**招生核心类 = 0** 比「通知数 = 0」更准。

实测依据：桂林电子科技大学有 48 条通知，但全是节气/人名/节日祝福/栏目名/
赛事活动噪声（detect_notice_noise.py 实测 42 条新增噪声），招生核心类 = 0
—— 看着有通知，实际零招生信息。所以「46 所有通知」里藏着这类假覆盖。

招生核心类口径（保守，宁漏勿误，详见 is_core_notice docstring）
--------------------------------------------------------------
两种判据取并集，排除五类非核心：
1. ``notice_type`` ∈ {简章, 目录, 大纲, 调剂, 录取, 复试}（非「公告」的类型）；
2. 标题含招生核心词（ADMISSION_WORDS 剔除「在读/毕业后」词）；
排除：
3. 导航项（裸栏目标签，如「吉林大学招生网」「研究生院」「硕士研究生报名」）；
4. 纯博士内容（与 notice_rules.yaml 既有降级规则同口径）；
5. 本科招生（用户是硕士考生）；
6. 赛事活动报名（如「数学建模竞赛报名」）。

为什么口径要反复精修：先用 notice_type 单口径得 8 所、并集得 6 所、
宽词表得 5 所都不对——分别漏了/错了不同的学校。最终口径实测
全库 46 所有通知的学校中 8 所「招生核心类 = 0」：
桂电(48条全噪声)、燕大(24条全在读事务)、复旦(10条全导航)、
北理工(6条无真招生)、南大(4条全系统/博士)、吉大(4条含招生网导航)、
河海(10条)、南理工(1条)。

候选池口径复用 ``screen_electronic_schools_6provinces.py``（A/W/B 三级），
不重新发明筛选规则。

本脚本**只读**，不写库、不抓取。
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from screen_electronic_schools_6provinces import (  # noqa: E402
    KNOWN_STRONG,
    NON_ICT_ELITE,
    PROVINCES,
    STRONG_KW,
    load,
)

DB = r"D:\平台\database\kaoyan.db"

#: notice_type 口径的招生核心类（与 detect_notice_noise.py 的 CORE 一致）。
CORE_TYPES = ("简章", "目录", "大纲", "调剂", "录取", "复试")

#: 标题口径招生核心词 = detect_notice_noise.ADMISSION_WORDS **剔除「在读/毕业后」词**。
#: 为什么不能直接用宽口径 ADMISSION_WORDS：实测它把三所「零招生信息」的学校
#: 错误救活 —— 燕山大学 24 条全是在读事务，命中「专业学位」「培养方案」；
#: 北理工「硕士学位论文盲评系统」命中「硕士学位」（实为系统导航链接）。
#: 学费/学制/奖助/成绩/查分/培养方案 是入学后事务，对**硕士考生**不是招生信息。
POST_ENROLLMENT_WORDS = {
    "培养方案", "学费", "学制", "奖助", "成绩", "查分",
    "专业学位", "学术学位", "硕士学位", "博士学位", "研究生院", "研招办",
}

#: 导航项：整条标题就是「XX招生网 / 硕士研究生报名」这类**裸栏目标签**
#: （无「关于/年份/校名」等通知特征），不是通知本体。
#: 实例：id=1289「吉林大学招生网」、id=1057 复旦「研究生院」、
#: id=1179 北理工「硕士研究生报名」——不排除会把这些学校错判成"已有招生信息"。
#: 全库共 11+ 条（西电/上交/南大/哈工大/吉大/北科大/江南大/河北工业/复旦/北理工）。
NAV_TITLE_RE = re.compile(
    r"^(.+招生网|.+研招网|.+学位与研究生教育|"
    r"研究生院|.+研究生院|"
    r"(硕士|博士)研究生(招生|报名)|"
    r".+招生办公室|.+迎新系统)$"
)
#: 纯博士内容：与 notice_rules.yaml「纯博士相关」降级规则同口径
#: （keywords ["博士"] + not_contains ["硕士","本硕","工程硕博士"]）。
#: 实例：id=1074 南京大学「博士生答辩公示平台」（类型=录取，但是博士内容，
#: 对硕士考生不是招生核心信息）。
PHD_EXCLUDE = ["硕士", "本硕", "工程硕博士"]
#: 本科招生：用户是**硕士考生**，本科招生信息不在范围内。
#: 实例：id=1688 江南大学「本科招生办公室」。
#: 注意不能用「本科+招生」一刀切——id=369 重邮「接收优秀应届本科毕业生免试攻读
#: 研究生…招生录取工作办法」是推免（硕士生源），必须保留。
UNDERGRAD_RE = re.compile(r"本科(生)?招生")
#: 赛事活动报名不是招生报名。
#: 实例：id=1178 北理工「研究生数学建模竞赛报名及培训」命中「报名」但是竞赛。
COMPETITION_RE = re.compile(r"竞赛|大赛|挑战赛|锦标赛|联赛")


def _core_title_words() -> list[str]:
    """招生核心词表（运行时从 ADMISSION_WORDS 派生，保持单一事实来源）。"""
    from detect_notice_noise import ADMISSION_WORDS
    return [w for w in ADMISSION_WORDS if w not in POST_ENROLLMENT_WORDS]


def is_core_notice(title: str | None, notice_type: str | None) -> bool:
    """硕士考生视角的「招生核心类」判定。

    判定顺序（先排非核心，再认核心）：
    1. 导航项（NAV_TITLE_RE）→ 非核心；
    2. 纯博士内容 → 非核心（与 notice_rules.yaml 既有降级同口径）；
    3. 本科招生 → 非核心；
    4. ``notice_type`` ∈ 核心类型 → 核心（类型是强信号，优先于标题判据）；
    5. 赛事活动 → 非核心；
    6. 标题含招生核心词（ADMISSION_WORDS 剔在读词）→ 核心。

    设计原则：**漏报代价低、误报代价高**。漏报（真有核心信息却触发补导）
    只是用户白跑一趟；误报（全是噪声/导航却判"已有核心"）会直接漏掉院校
    招生信息——桂电 48 条全噪声就是最痛的实例。所以标题侧判据从宽，
    但「在读事务/裸导航/赛事」三类实测误救必须排除。
    """
    t = (title or "").strip()
    if NAV_TITLE_RE.match(t):
        return False
    if "博士" in t and not any(x in t for x in PHD_EXCLUDE):
        return False
    if UNDERGRAD_RE.search(t):
        return False
    if notice_type in CORE_TYPES:
        return True
    if COMPETITION_RE.search(t):
        return False
    return any(w in t for w in _core_title_words())

#: 行业属性校名后缀/词（电子/邮电/信息/理工/科技类行业校的校名特征）。
NAME_INDUSTRY_WORDS = ["电子", "邮电", "信息", "理工", "科技", "航空", "交通"]

#: intro 已知脏数据的学校（team-lead 2026-10-12 裁定）。
#: 这些校的 ``intro`` 是截断模板/校长简历/藏书统计等非学科内容，却恰好命中
#: ``STRONG_KW``（如「电子图书」「研究生招生信息网」），会让 kw_hits 误报强信号，
#: 虚高 T2 评分。因此它们**不计 intro 强信号分（+2）**，只用其它维度评分。
#: 实例：重庆理工 intro 是校长简历（含「电气/电子」措辞）、重庆邮电/遵义医科/西南科大/
#: 西南政法 同理（详见 screen_electronic_schools_6provinces.NOISE_CTX 注释）。
DIRTY_INTRO_SCHOOLS = {
    "重庆理工大学", "重庆邮电大学", "遵义医科大学", "西南科技大学", "西南政法大学",
}

#: official_url 指向判定模式（与 screen 脚本保持一致）。
URL_PATTERNS = {
    "研究生院/招生网": r"yjs|/yz|yz\.|grs|yzb|graduate",
    "研招网": r"yz\.chsi\.com\.cn",
    "学校官网首页": r"^https?://www\.[a-z0-9-]+\.edu\.cn/?$",
}
SCHID_RE = re.compile(r"^\d+$")


def classify_url(url: str | None) -> str:
    """把 official_url 分类为：研究生院/招生网、研招网、学校官网首页、数字schid、无。"""
    u = (url or "").strip()
    if not u:
        return "无"
    if SCHID_RE.match(u):
        return "数字schid"
    for label, pat in URL_PATTERNS.items():
        if re.search(pat, u, re.I):
            return label
    return "其它"


def load_notice_stats(conn: sqlite3.Connection) -> dict[int, dict]:
    """按 school_id 聚合通知统计：总数、核心数（并集口径）、噪声数。"""
    rows = conn.execute(
        "SELECT school_id, title, notice_type, importance_reason "
        "FROM kaoyan_notices WHERE school_id IS NOT NULL"
    ).fetchall()
    stats: dict[int, dict] = {}
    for sid, title, ntype, reason in rows:
        s = stats.setdefault(sid, {"total": 0, "core": 0, "noise": 0})
        s["total"] += 1
        if is_core_notice(title, ntype):
            s["core"] += 1
        # 噪声口径与 detect_notice_noise.py 对齐：现有规则降级 + 新增判据
        from detect_notice_noise import EXISTING_NOISE_REASONS, classify_noise
        r = reason or ""
        if any(k in r for k in EXISTING_NOISE_REASONS):
            s["noise"] += 1
        elif classify_noise(title)[0]:
            s["noise"] += 1
    return stats


def ict_score(s: dict) -> tuple[int, list[str]]:
    """电子信息强度评分（用于 T2 排序），返回 (分数, 加分理由)。

    评分维度（分数仅用于排序，不代表学科实力官方排名）：
      +3 人工核对过的行业强校清单（KNOWN_STRONG，level 为 NULL 也纳入）
      +2 intro 有电子信息强信号词（已剔「电子图书」类噪声上下文）
      +1 level 是 985/211/双一流（用户「level 硬门槛」要求）
      +1 校名含行业属性词（电子/邮电/信息/理工/科技/航空/交通）

    防污染（team-lead 2026-10-12）：``DIRTY_INTRO_SCHOOLS`` 里的学校，其 intro 是
    截断模板/校长简历/藏书统计等非学科内容，却恰好命中 STRONG_KW 虚高评分，
    因此**不计 intro 强信号分**——只用行业强校/level/校名属性等可靠维度计分。
    """
    score, why = 0, []
    if s["name"] in KNOWN_STRONG:
        score += 3
        why.append("行业强校+3")
    if s.get("kw_strong"):
        if s["name"] in DIRTY_INTRO_SCHOOLS:
            why.append("intro有信号但已知脏数据不计分")
        else:
            score += 2
            why.append("intro强信号+2")
    if s["level"] in ("985", "211", "双一流"):
        score += 1
        why.append(f"level={s['level']}+1")
    if any(w in s["name"] for w in NAME_INDUSTRY_WORDS):
        score += 1
        why.append("校名行业属性+1")
    return score, why


def build_pool(conn: sqlite3.Connection) -> list[dict]:
    """六校候选池（A/W/B 三级），附通知统计。逻辑与 screen 脚本一致。"""
    from screen_electronic_schools_6provinces import kw_hits

    schools = load(conn)
    stats = load_notice_stats(conn)
    pool = []
    for s in schools:
        reasons, tier = [], ""
        strong, weak = kw_hits(s["intro"])
        if s["level"] in ("985", "211", "双一流"):
            if s["name"] in NON_ICT_ELITE:
                tier = "B"
                reasons.append(f"level={s['level']}（名校但非电子信息类）")
            else:
                tier = "A"
                reasons.append(f"level={s['level']}")
        if strong:
            if not tier:
                tier = "A"
            reasons.append("intro强信号:" + "/".join(strong[:4]))
        elif weak and not tier:
            tier = "W"
            reasons.append("intro仅弱信号「信息」")
        if s["name"] in KNOWN_STRONG:
            tier = "A"
            reasons.append("行业强校")
        if not reasons:
            continue
        st = stats.get(s["id"], {"total": 0, "core": 0, "noise": 0})
        s = dict(s)
        s.update({
            "reasons": reasons, "kw_strong": strong, "tier": tier,
            "core_cnt": st["core"], "noise_cnt": st["noise"],
            "url_kind": classify_url(s["official_url"]),
        })
        pool.append(s)
    return pool


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        pool = build_pool(conn)
        all6 = load(conn)
        stats = load_notice_stats(conn)
    finally:
        conn.close()

    print("=" * 96)
    print("六省电子电气强校补导清单（触发条件：招生核心类 = 0）")
    print("=" * 96)
    a_pool = [s for s in pool if s["tier"] == "A"]
    print(f"  6 省共 {len(all6)} 所 → A 类候选 {len(a_pool)} 所"
          f"（W {len([s for s in pool if s['tier']=='W'])} / "
          f"B {len([s for s in pool if s['tier']=='B'])}）")

    # ---- 补导触发复算 ----
    need = [s for s in a_pool if s["core_cnt"] == 0]
    fake = [s for s in a_pool if s["core_cnt"] == 0 and s["notice_cnt"] > 0]
    print(f"  A 类中「招生核心类 = 0」需补导: {len(need)} 所"
          f"（其中「有通知但全是噪声」的假覆盖 {len(fake)} 所）")
    for s in sorted(fake, key=lambda x: -x["notice_cnt"]):
        print(f"    ⚠ 假覆盖: {s['province']} {s['name']} 通知={s['notice_cnt']} "
              f"噪声={s['noise_cnt']} 核心=0")

    # ---- 分三档 ----
    t1 = [s for s in need if s["url_kind"] in ("研究生院/招生网", "研招网", "其它")
          and (s["official_url"] or "").startswith("http")]
    t1b = [s for s in need if s["url_kind"] == "数字schid"]
    t2 = [s for s in need if s["url_kind"] == "无"]
    t3 = [s for s in a_pool if s["core_cnt"] > 0]

    print()
    print("=" * 96)
    print(f"T1  可立即补导（核心=0 + official_url 可直接定位通知列表页）—— {len(t1)} 所")
    print("=" * 96)
    for s in t1:
        print(f"  {s['province']:3s} | {s['name'][:18]:20s} | {str(s['level'] or 'NULL'):5s} "
              f"| 通知={s['notice_cnt']:<3d} | {s['url_kind']}")
        print(f"        URL: {s['official_url']}")
        print(f"        入选理由: {'; '.join(s['reasons'])}")

    print()
    print("=" * 96)
    print(f"T1b schid 修正后可补导（核心=0 + official_url 是数字 schid，"
          f"fix_official_url_schid.py 修完即可）—— {len(t1b)} 所")
    print("=" * 96)
    for s in t1b:
        print(f"  {s['province']:3s} | {s['name'][:18]:20s} | {str(s['level'] or 'NULL'):5s} "
              f"| 通知={s['notice_cnt']:<3d} | schid={s['official_url']}"
              f" → https://yz.chsi.com.cn/sch/{s['official_url']}.jhtml")

    print()
    print("=" * 96)
    print(f"T2  需先补「院校→研究生院URL」映射（核心=0 + 无 official_url）"
          f"—— {len(t2)} 所，按电子信息强度排序")
    print("=" * 96)
    scored = []
    for s in t2:
        sc, why = ict_score(s)
        scored.append((sc, s, why))
    scored.sort(key=lambda x: (-x[0],
                               {"985": 0, "211": 1, "双一流": 2, "双非": 3}.get(x[1]["level"], 4),
                               x[1]["name"]))
    for rank, (sc, s, why) in enumerate(scored, 1):
        print(f"  {rank:2d}. [{sc}分] {s['province']:3s} | {s['name'][:18]:20s} "
              f"| {str(s['level'] or 'NULL'):5s} | 通知={s['notice_cnt']:<3d} "
              f"| {'/'.join(why)}")
        print(f"        入选理由: {'; '.join(s['reasons'])}")

    print()
    print("=" * 96)
    print(f"T3  已有招生核心通知（无需补导）—— {len(t3)} 所")
    print("=" * 96)
    for s in sorted(t3, key=lambda x: -x["core_cnt"]):
        print(f"  {s['province']:3s} | {s['name'][:18]:20s} | {str(s['level'] or 'NULL'):5s} "
              f"| 通知={s['notice_cnt']:<3d} 核心={s['core_cnt']:<3d} 噪声={s['noise_cnt']}")

    # ---- 3a 修正前后可补导数 ----
    print()
    print("=" * 96)
    print("official_url 数字 schid 修正（fix_official_url_schid.py）前后对比")
    print("=" * 96)
    # 全库口径：修正后可立即补导 = 核心=0 且 official_url 修正后可点开
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sch_rows = conn.execute(
            "SELECT s.id, s.name, s.level, s.official_url FROM kaoyan_schools s"
        ).fetchall()
    finally:
        conn.close()
    before = after = 0
    after_new = []
    for sid, name, level, url in sch_rows:
        st = stats.get(sid, {"total": 0, "core": 0, "noise": 0})
        if st["core"] > 0:
            continue
        u = (url or "").strip()
        if u.startswith("http"):
            before += 1
            after += 1
        elif SCHID_RE.match(u):
            after += 1
            after_new.append((name, u))
    print(f"  修正前可立即补导（核心=0 + http URL）        : {before} 所")
    print(f"  修正后可立即补导（+ 数字 schid 拼成 chsi URL）: {after} 所"
          f"（新增 {len(after_new)} 所）")
    print(f"  其中六省 A 类: 修正前 {len(t1)} 所 → 修正后 {len(t1) + len(t1b)} 所")

    print()
    print("=" * 96)
    print("汇总")
    print("=" * 96)
    print(f"  T1  可立即补导            {len(t1):3d} 所")
    print(f"  T1b schid 修正后可补导    {len(t1b):3d} 所")
    print(f"  T2  需先补 URL 映射       {len(t2):3d} 所")
    print(f"  T3  已有核心通知无需补    {len(t3):3d} 所")
    print(f"  A 类候选合计              {len(a_pool):3d} 所")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
