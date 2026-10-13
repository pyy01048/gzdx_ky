# -*- coding: utf-8 -*-
"""L2 49 组人工裁决表（逐组判定，理由可复核）。

判定分档（严格按 team-lead 要求，不为凑数而猜）：
  可判定  —— 存在学科/数学事实可唯一确定正确侧，给出正确侧 id
  需隔离  —— 两侧答案均不可用（错答 / 题干残留 / 波形图不可得 / 选项缺失）
  无需处置 —— 两答案实质等价（同义表述），处置任一侧都会造成损失

同时统计根因信号，判断问题是否属于「切题源头质量」而非「判重」。
只读脚本，不写库。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

sys.path.insert(0, r"D:\平台\backend-main-fastapi")

JSON = r"D:\平台\backend-main-fastapi\data\diagnostics\l2_adjudicate.json"

# 组号 -> (判定, 正确侧id或None, 依据)
VERDICT: dict[str, tuple[str, int | None, str]] = {
    "L01": ("可判定", 38, "最基本三种逻辑运算是「与、或、非」。#26 答「与非门/或非门/异或门」是三种门电路，非三种运算"),
    "L02": ("可判定", 1568, "#145 答案=「四、简答题（共4题每题6分）」是题型标题残留；#1568 给出化简定义，正确"),
    "L03": ("需隔离", None, "题干问「列举2种常见负反馈类型」，两侧答案都在讲性能影响，均未答题干"),
    "L04": ("可判定", 203, "简述交流负反馈对性能影响，#203 列出稳定Q点/缩通频带/减小非线性失真等5条；#244 只答相位差基本不变，不完整"),
    "L05": ("可判定", 266, "按结构分类为「结型、绝缘栅型」，电压控制性。#266「绝缘栅极；电压」正确；#1851「MOSFET；GTO；电压或电流」把器件型号当分类且多出第三空"),
    "L06": ("需隔离", None, "事实可判：2.7−2=0.7V→B=2V、E=2.7V、C=6V，硅管 NPN。但 #276 答「B；PNP」类型错，#353 仅「D」为选项字母无选项，无法采用"),
    "L07": ("需隔离", None, "设计题答案均为「如图10-5/10-6所示」，图不可得，对刷题无价值"),
    "L08": ("可判定", 8064, "工频50Hz属低频干扰需高通滤除、高频干扰需低通。#8064「高通；低通」与其 analysis 一致；#289「低通、高通」反了"),
    "L09": ("需隔离", None, "题干 OCR 残缺「若，则可完成…」，无选项无图，条件不可判"),
    "L10": ("可判定", 8078, "按结构划分为电感三点式、电容三点式。#8078 正确；#308「RC型；石英晶体管式」是按选频元件分类，非按结构"),
    "L11": ("需隔离", None, "波形题依赖图，题干截断且选项不全"),
    "L12": ("需隔离", None, "(10100011.11)₂ = 128+32+4+2+0.75 = 166.75。#488 答 163.75、#1644 答 375.625，两侧均算错"),
    "L13": ("需隔离", None, "TTL 扇出：高电平 0.5mA/20μA=25，低电平 10mA/1mA=10，取小=10。#515 答 12、#522 答 16 均错，且 #522 analysis 自陈「可驱动6个」与答案自相矛盾"),
    "L14": ("可判定", 546, "第(1)问触发方式应答「电平触发」；#1082 把触发方式答成「D触发器」（器件而非方式），#546 三问齐全且(1)正确"),
    "L15": ("需隔离", None, "#638 答案16 但其 analysis 自称「最多驱动5个」；#639 analysis 讲「图3-21」「或非门」与题干「图3-20 与非门」不符，两侧均不可靠"),
    "L16": ("需隔离", None, "画波形题；#685 答案为「答案：」空值，#684「见下图（或用文字描述）」空洞"),
    "L17": ("需隔离", None, "画Q、Q′波形题，答案给的是「Q′=0.3V；Q=0.7V」电压值而非波形，且依赖图"),
    "L18": ("需隔离", None, "#713/#715 答案为「D触发器的驱动方程为」等残句，#714/#718 答案是题干复述，四条均为切题残骸"),
    "L19": ("需隔离", None, "多选题，选项缺失，无法核对 AB / C 哪个正确"),
    "L20": ("可判定", 934, "TTL 输入端悬空等效高电平，多余端应接高电平或并接；#935「接地或接低电平」是 CMOS 做法，会使与非门输出恒高"),
    "L21": ("可判定", 8143, "按动作特点分「基本型、同步型、主从型、边沿型」。#8143 正确；#1072「主动型」不是触发器分类"),
    "L22": ("需隔离", None, "题干为「N个触发器」泛指，#1712 答「10」无依据且 analysis 是串题 OCR；#1118 答「Ｂ」为选项字母无选项"),
    "L23": ("需隔离", None, "多选题，PROM/PAL 结构选项缺失，无法核对 AD / C"),
    "L24": ("需隔离", None, "77×0.02=1.54V，#1254 analysis 自洽但答案是选项字母无选项；#1438/#1807 analysis 的码值与题干 01001101 不符，属串题"),
    "L25": ("可判定", 1263, "DAC 分辨率即输入位数，12位→12。#7931 analysis 讲「8位DAC」且答 D，与题干 12 位不符"),
    "L26": ("需隔离", None, "正弦波转同频矩形波应用微分型；#1323 答积分型、#1430 答多谐振荡器，均非正解；题干还串入「进制的计数器」"),
    "L27": ("可判定", 1404, "JK 特性方程 Qn+1 = J'·Qn + K'·Qn'。#1404 正确；#1809「J+K'·Q」缺 J'Qn 项且形式不完整"),
    "L28": ("需隔离", None, "A/D 中并行(Flash)最快、计数型最慢，#1411 analysis 判错；但两者答案均为选项字母，无选项不可核"),
    "L29": ("需隔离", None, "输入输出波形判电路，依赖图；#1412/#1819 均为选项字母且指向不同结论（施密特 vs 单稳）"),
    "L30": ("需隔离", None, "74LS138 输出低电平有效，A2A1A0=101 时仅 Y5 有效、余输出高电平；两侧均为选项字母无选项，不可核"),
    "L31": ("需隔离", None, "8K=2¹³→地址线13条。#1806 答「12条」明确错；#1437 答「C」无选项。无可用正确侧"),
    "L32": ("无需处置", None, "命题「CMOS功耗随频率变大而减小」为假，两侧分别答 F 与 ×，均为「错」，实质等价，非冲突"),
    "L33": ("需隔离", None, "三极管截止时 BE 结无电流应等效「断开」，不是闭合开关，命题本身错；#1585 答「正确」判错，#1618 答「三极管截止」是残骸非判断答案"),
    "L34": ("需隔离", None, "22分大题，题干参数 OCR 残缺（rb=1002、41k2 等），两答案均依赖完整电路图"),
    "L35": ("可判定", 1822, "1个触发器存1位，存8位需8个。#1822「两个；八个」正确；#1841「两个；16」错"),
    "L36": ("需隔离", None, "题干为 OCR 公式碎片「01µF uO UCC S ln[(0)/(0/3)]…」，不可读"),
    "L37": ("可判定", 6242, "#5379 答案「第8 音拓展习题」是教材页眉噪声；#6242 给出 OTL 电路判断，切题且正确"),
    "L38": ("可判定", 6248, "同 L37：#5385 答案为「第8 音拓展习题」页眉噪声；#6248 切题作答"),
    "L39": ("需隔离", None, "题干含「东坡哥微信:haidongpo8 微信公众号」广告残留且 OCR 破碎，#7732/#7733 结论完全不同（异或门 vs D触发器）"),
    "L40": ("需隔离", None, "题干「UcEs <Uc <Vcc 东坡哥微信…」为 OCR 碎片+广告，两答案无关联"),
    "L41": ("可判定", 8712, "#8060 答案「必须写在答题纸上否则后果自负！）」是试卷通知；#8712 给出完整驱动方程/状态方程"),
    "L42": ("需隔离", None, "题干是知识点陈述残片，答案为选项字母，选项缺失"),
    "L43": ("需隔离", None, "题干已含结论「∴为NPN硅管」，#8353 答「C」、#8355 答「NPN硅管」，选项缺失不可核"),
    "L44": ("需隔离", None, "共基极电压增益大、电流增益≈1，命题正确；但 #8363/#8364 均为选项字母且 #8364 analysis 自陈「题目表述存在矛盾」"),
    "L45": ("无需处置", None, "#8393 与 #8693 均答「对应放大区、电流放大系数β高」，实质等价，非冲突"),
    "L46": ("无需处置", None, "竞争/冒险定义与解决方法的两种表述，内容等价，非冲突"),
    "L47": ("需隔离", None, "选项缺失。#8494 analysis 指向 A（双向输入数据非其功能），#8495 analysis 把 C（回差电压）当作「不具有」却又在解析里说是核心特性，自相矛盾"),
    "L48": ("需隔离", None, "提高CMRR＝增大差模增益或减小共模增益，#8684 表述正确但答案是内容而非题目所求选项；#8651 答「B」无选项"),
    "L49": ("需隔离", None, "题干「A 科目代码：834 科目名称：电子技术基础 第 44 页」是试卷页眉，根本不是题"),
}

#: 根因信号：答案其实是「非答案」的标记
NOISE_ANSWER = re.compile(
    r"^\s*(第\s*\d+\s*[章音]|[A-Za-z]?\s*科目代码|必须写在答题纸|答案[:：]\s*$|见下图|如图\s*\d|"
    r"如图\d+所示|本页|查看答案|知识点)")
OPTION_ONLY = re.compile(r"^\s*([A-Z]{1,3}|[A-Z]|[ABCD]|[\(（]?[A-D][\)）]?)\s*$")


def main() -> int:
    data = json.load(open(JSON, encoding="utf-8"))
    print(f"[adj] 材料组数 = {len(data)}；判定表覆盖 = {len(VERDICT)}")
    missing = [g["组号"] for g in data if g["组号"] not in VERDICT]
    extra = [k for k in VERDICT if k not in {g["组号"] for g in data}]
    if missing or extra:
        print(f"[adj] ⚠ 未覆盖={missing} 多余={extra}")

    buckets: Counter[str] = Counter()
    by_subj: Counter[str] = Counter()
    keep_ids, junk_ids = [], []
    for g in data:
        gid = g["组号"]
        kind, keep, why = VERDICT[gid]
        buckets[kind] += 1
        for it in g["选项"]:
            by_subj[it["subject"] or "(空)"] += 1
        ids = g["全部id"]
        if kind == "可判定":
            keep_ids.append(keep)
            junk_ids += [i for i in ids if i != keep]
        elif kind == "需隔离":
            junk_ids += ids

    print(f"\n[adj] 判定分布: {dict(buckets)}")
    print(f"[adj] 学科分布（按条）: {dict(by_subj.most_common())}")
    total = sum(by_subj.values())
    for s, n in by_subj.most_common():
        print(f"        {s}: {n} 条 ({n/total*100:.1f}%)")

    # ---- 根因信号统计 ----
    opt_only = noise = ans_len_le10 = 0
    for g in data:
        for it in g["选项"]:
            a = it["ans"].strip()
            if OPTION_ONLY.match(a):
                opt_only += 1
            elif NOISE_ANSWER.search(a):
                noise += 1
            if len(a) <= 10:
                ans_len_le10 += 1
    n_opt = sum(len(g["选项"]) for g in data)
    print(f"\n[rootcause] 答案仅为选项字母（A/B/C/D）= {opt_only}/{n_opt} "
          f"({opt_only/n_opt*100:.1f}%)")
    print(f"[rootcause] 答案为页眉/广告/空值等非答案 = {noise}/{n_opt} "
          f"({noise/n_opt*100:.1f}%)")
    print(f"[rootcause] 答案长度 ≤10 字 = {ans_len_le10}/{n_opt} "
          f"({ans_len_le10/n_opt*100:.1f}%)")

    out = []
    for g in data:
        gid = g["组号"]
        kind, keep, why = VERDICT[gid]
        out.append({
            "组号": gid, "ids": g["全部id"], "题干": g["题干"],
            "答案": {str(it["id"]): it["ans"] for it in g["选项"]},
            "学科": [it["subject"] for it in g["选项"]],
            "来源": [it["source"] for it in g["选项"]],
            "判定": kind, "正确侧": keep, "依据": why,
        })

    op = r"D:\平台\backend-main-fastapi\data\diagnostics\l2_verdicts.json"
    with open(op, "w", encoding="utf-8") as f:
        json.dump({"summary": {"分布": dict(buckets), "学科": dict(by_subj),
                               "根因_选项字母": opt_only, "根因_非答案": noise,
                               "总条数": n_opt},
                   "组": out}, f, ensure_ascii=False, indent=1)

    print(f"\n[adj] 可判定 {len(keep_ids)} 组 → 保留 {sorted(keep_ids)}")
    print(f"[adj] 需隔离 → 两侧共 "
          f"{sum(len(g['全部id']) for g in data if VERDICT[g['组号']][0]=='需隔离')} 条")
    print(f"[adj] 无需处置 {buckets['无需处置']} 组（两侧实质等价，不处置）")
    print(f"\n[saved] {op}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
