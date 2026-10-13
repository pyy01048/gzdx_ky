# -*- coding: utf-8 -*-
"""入库前内容闸门验证脚本（不入库、不改数据）。

跑法::

    C:\\Users\\33884\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe \\
        scripts/verify_quiz_content_gate.py

三段验证：
  A. 单元级：8 条真实样本（讲义/PPT/教材段落/OCR噪声 vs 真题）直接过 ``admit()``
  B. 管线级：构造一篇"讲义正文 + 真题"混合文档，走 ``extract_questions()``，
     证明讲义被拦、真题通过
  C. 存量回放：从真库只读取样，跑一遍新闸门，统计"若当初有闸门会拦掉多少"
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")

from services import qbank_builder as qb  # noqa: E402
from services import quiz_content_gate as gate  # noqa: E402

FAIL = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global FAIL
    mark = "PASS" if cond else "FAIL"
    if not cond:
        FAIL += 1
    print(f"  [{mark}] {label} {extra}")


# --------------------------------------------------------------------------- #
# A. 单元级样本：全部取自真库/知识库真实文本
# --------------------------------------------------------------------------- #
SAMPLES: list[tuple[str, str, str, str, list, str | None, bool]] = [
    # (标签, content, source, section_type, options, answer, 期望放行)
    (
        "讲义正文/PPT条目：设计步骤说明",
        "4.1 同步时序逻辑电路的设计方法 设计关键：根据设计要求→确定状态转换的规律→求出各 "
        "触发器的驱动方程。 一、设计步骤：（先简单介绍，通过以下的举例后，再进 行总结，"
        "特别再点出设计关键）",
        "知识库:【电子技术基础-数字部分】康华光 精华教案与复习.txt",
        "设计", [], None, False,
    ),
    (
        "讲义正文：知识点段落",
        "四种接法的比较：电路参数理想对称条件下 输入方式：Ri均为2(Rb+rbe)；"
        "双端输入时无共模信号输入，单端输入时有共模信号输入。 输出方式：Q点、Ad、Ac、"
        "KCMR、Ro均与之有关。",
        "知识库:【电子技术基础-模拟部分】康华光 精品复习课件.txt",
        "", [], None, False,
    ),
    (
        "教材段落：定义+推导叙述",
        "单电源供电的乙类输出级（OTL电路）：采用单电源供电，输出端通过 大电容与负载耦合。"
        "其主要性能与OCL 电路类似，只需将OCL 公式中的 V_CC 换成V_CC/2。因此最大效率仍为"
        "78.5%。最大输出功率P_om = (V_CC^2)/(8 R_L)。",
        "知识库:【电子技术基础-模拟部分】康华光 全章节总结.txt",
        "", [], None, False,
    ),
    (
        "PPT残留：版式噪声",
        "返回下页继续放映第 12 页，共 30 页，本页内容盛要是触发器的分类，请点击查看",
        "知识库:某课件.ppt", "", [], None, False,
    ),
    (
        "答案体被当成题干",
        "答案：B。因为与非门的逻辑表达式为 Y=(AB)'，故选择 B 项。",
        "真题:某真题", "", [], None, False,
    ),
    (
        "OCR乱码",
        "触发器的电路结构形式、逻辑功能、触发方式这三者之间的关系 һ 第五章 半导体存储电路",
        "知识库:某教材.txt", "", [], None, False,
    ),
    (
        "★ 真题题干：填空",
        "在RS触发器中，当 R=1、S=0 时，Q 端的输出为 ____。",
        "真题:贵州大学电子技术基础真题", "填空", [], "0", True,
    ),
    (
        "★ 真题题干：选择题（带选项）",
        "下列关于同步时序逻辑电路的说法，正确的是（ ）。A、各触发器的状态在同一时刻更新 "
        "B、CP到来时所有触发器同时翻转 C、不受CP控制 D、只能由组合逻辑构成",
        "真题:某大学2016真题", "选择",
        ["A、各触发器的状态在同一时刻更新", "B、CP到来时所有触发器同时翻转",
         "C、不受CP控制", "D、只能由组合逻辑构成"], "B", True,
    ),
    (
        "★ 真题题干：判断题",
        "多级放大电路中电信号在各级传输过程中应不发生失真现象。（  ）",
        "真题:模拟电子技术真题", "判断", [], "对", True,
    ),
    (
        "★ 真题题干：简答/计算",
        "已知放大电路中 U_CC=12V，R_C=2kΩ，求静态集电极电流 I_CQ 和静态电压 U_CEQ。",
        "真题:2018年真题", "计算", [], "I_CQ=3mA，U_CEQ=6V", True,
    ),
    (
        "★ 真题题干：概念简答",
        "简述触发器的逻辑功能与触发方式之间的关系，并说明二者的区别。",
        "真题:数字电子技术真题", "简答", [], "见解析", True,
    ),
    (
        "★ 真题声称但内容是讲义段落（加严样本）",
        "因此答案：因为场效应管是一种电压控制型器件，输入电阻很高，因此所谓场效应管"
        "放大电路的电压增益较大；综上，设计时通常选择较大的静态工作点以提高动态范围。",
        "真题:某真题（实际为讲义页）", "", [], "x", False,
    ),
]


def part_a() -> None:
    print("\n===== A. 单元级样本过闸门（期望：非题全拦、真题全过）=====")
    for label, content, source, sect, opts, ans, expect_ok in SAMPLES:
        gate.gate_reset_stats()
        ok, reason = gate.admit(
            content, options=opts, answer=ans, source=source, section_type=sect,
        )
        check(
            label,
            ok == expect_ok,
            f"→ {'放行' if ok else '拦截'} [{reason}]",
        )


# --------------------------------------------------------------------------- #
# B. 管线级：一篇混合文档走 extract_questions
# --------------------------------------------------------------------------- #
MIXED_DOC = """一、选择题
1. 已知放大电路 U_CC=12V，R_C=2kΩ，求静态集电极电流 I_CQ 和静态电压 U_CEQ。
A、3mA 6V
B、6mA 3V
C、1mA 9V
D、9mA 1V
答案：A
2. 简述触发器的逻辑功能与触发方式之间的关系，并说明二者的区别。
答案：逻辑功能相同的触发器可由不同电路结构构成，触发方式随结构而定。

二、设计题
3. 设计步骤：（先简单介绍，通过以下的举例后，再进行总结，特别再点出设计关键）
4. 设计关键：根据设计要求→确定状态转换的规律→求出各触发器的驱动方程。
5. 四种接法的比较：电路参数理想对称条件下输入方式：Ri均为2(Rb+rbe)。
6. 输出电压只有L足够大，才能升压；只有C足够大，输出电压交流分量才足够小! 讨论
"""


def part_b() -> None:
    print("\n===== B. 管线级：一篇讲义+真题混合文档走 extract_questions =====")
    print("  输入文档：一、选择题(2道真题目) + 二、设计题(4条讲义正文)")
    for hint in ("某真题卷.txt", "康华光 精品复习课件.txt"):
        gate.gate_reset_stats()
        qs = qb.extract_questions(MIXED_DOC, source_hint=hint)
        print(f"\n  --- source_hint = {hint!r} → 抽出 {len(qs)} 条")
        for q in qs:
            print(f"      · [{q['section_type']}] {q['content'][:60]}")
        print("      闸门计数:", gate.gate_stats_snapshot())
        if "真题" in hint:
            check("真题文档：2 道真题全部通过", len(qs) == 2)
        else:
            check("讲义文档：4 条讲义正文全部拦截", len(qs) == 2)

    # 闸门关闭开关验证
    os.environ["QUIZ_CONTENT_GATE"] = "0"
    try:
        gate.gate_reset_stats()
        qs_off = qb.extract_questions(MIXED_DOC, source_hint="康华光 精品复习课件.txt")
        check("QUIZ_CONTENT_GATE=0 可回退到旧行为（放行 6 条）", len(qs_off) == 6,
              f"→ 实际 {len(qs_off)} 条")
    finally:
        os.environ.pop("QUIZ_CONTENT_GATE", None)


# --------------------------------------------------------------------------- #
# C. 存量回放（只读）
# --------------------------------------------------------------------------- #
def part_b2() -> None:
    print("\n===== B2. source 敏感性：同一候选、不同 source 必须判定不同 =====")
    print("  （防回归：source_hint 传参链断裂 / 加严规则变成死代码 时会红）")

    # 先证明 source_hint 真的传到了 admit()
    seen: list[str] = []
    orig = qb._gate_admit

    def _spy(content, **kw):
        seen.append(kw.get("source") or "")
        return orig(content, **kw)

    qb._gate_admit = _spy
    try:
        logging.disable(logging.INFO)
        qb.extract_questions(MIXED_DOC, source_hint="2024年考研真题.pdf")
        logging.disable(logging.NOTSET)
    finally:
        qb._gate_admit = orig
    check(
        "source_hint 一路传到 admit()（未在链路中丢失）",
        any("2024年考研真题" in s for s in seen),
        f"→ 实收 {sorted(set(seen))}",
    )

    # 判别性样本：必须出现"真题更严 / 讲义更松"的分叉
    discriminative = [
        # (标签, content, section_type, answer, options, 期望 真题, 期望 讲义)
        (
            "灰区A：靠陈述式兜底、无问号无选项",
            "译码器在工作时不存在竞争冒险现象，输出是唯一确定的逻辑电平。",
            "判断", "错误", [], False, True,
        ),
        (
            "灰区B：带问号的叙述体段",
            "如何理解二极管的伏安特性？所谓理想二极管是指正向电阻为零、反向电流为零的"
            "一种理想模型，因此在分析整流电路时通常可以忽略导通压降。",
            "选择", None, [], False, False,
        ),
    ]
    for label, content, sect, ans, opts, exp_real, exp_lecture in discriminative:
        r_real = gate.admit(content, options=opts, answer=ans,
                            source="2024年考研数学一真题.pdf", section_type=sect)[0]
        r_lec = gate.admit(content, options=opts, answer=ans,
                           source="某某讲义.pdf", section_type=sect)[0]
        print(f"  · {label}")
        print(f"      真题源 → {'放行' if r_real else '拦截'}   "
              f"讲义源 → {'放行' if r_lec else '拦截'}")
        check(f"  {label}·真题源判定符合预期", r_real == exp_real)
        check(f"  {label}·讲义源判定符合预期", r_lec == exp_lecture)

    check(
        "存在至少一条'真题拦 / 讲义放'的分叉样本（证明加严非死代码）",
        any(
            not gate.admit(c, options=o, answer=a,
                           source="2024年考研真题.pdf", section_type=s)[0]
            and gate.admit(c, options=o, answer=a,
                           source="某某讲义.pdf", section_type=s)[0]
            for _, c, s, a, o, er, el in discriminative if er != el
        ),
    )


def part_c() -> None:
    print("\n===== C. 存量回放（只读真库，统计闸门若当初存在会拦掉多少）=====")
    import sqlite3
    db = os.path.abspath(os.path.join(BASE_DIR, "..", "database", "kaoyan.db"))
    if not os.path.exists(db):
        print("  [SKIP] 真库不存在:", db)
        return
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT content, answer, source, question_type, options FROM quiz_questions"
    ).fetchall()
    con.close()
    gate.gate_reset_stats()
    kept = 0
    for content, answer, source, qtype, options in rows:
        opts = []
        if options:
            try:
                import json
                opts = json.loads(options) or []
            except Exception:
                opts = []
        ok, _ = gate.admit(content or "", options=opts, answer=answer,
                           source=source or "")
        if ok:
            kept += 1
    snap = gate.gate_stats_snapshot()
    rejected = sum(v for k, v in snap.items() if k.startswith("reject:"))
    print(f"  存量总数 {len(rows)} → 新闸门放行 {kept}，拦截 {rejected}"
          f"（拦截率 {rejected / max(1, len(rows)):.1%}）")
    for k, v in sorted(snap.items(), key=lambda x: -x[1]):
        if k.startswith("reject:"):
            print(f"    {k[7:]:<24} {v}")
    check("闸门在存量上确实拦掉了大量非题", rejected > 1000)


if __name__ == "__main__":
    part_a()
    part_b()
    part_b2()
    part_c()
    print("\n===== 结果：", "全部通过 IS_PASS=YES" if FAIL == 0 else f"{FAIL} 项失败 IS_PASS=NO", "=====")
    sys.exit(1 if FAIL else 0)
