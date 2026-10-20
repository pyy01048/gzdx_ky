# -*- coding: utf-8 -*-
"""新增「自动控制原理」科目，并把误标为「数学」的 53 道自控题归位。

背景
----
题库 ``quiz_questions`` 里 id 218–270 这 53 道题来自胡寿松《自动控制原理》
（第 6 版）配套题库（上/下册），但 ``subject`` 被整批写成「数学」，
``question_knowledge_links`` 也全部挂在数学知识点上（行列式 / 无穷大量…）。
这是文档级科目误判：题干公式在抽取时丢失，靠关键词只能召回 33 道，
所以**圈题直接按连续 id 区间 218–270**，不做关键词 SQL。

本脚本一次性完成（全部幂等，可反复执行）：
  1. ``subjects`` / ``subject_config`` 注册「自动控制原理」；
  2. ``subject_chapters`` 建 10 章（ch01..ch10）；
  3. 53 道题改挂 subject / chapter / chapter_id / subject_id；
  4. 补 78 个自控知识点（每章 7/8/8/8/9/7/8/7/8/8）；
  5. 删除旧数学关联（过 ``delete_guard``），按章节 + 关键词重挂新知识点。

安全
----
* 默认 dry-run，只打印清单，不写库；
* ``--apply`` 先调用 ``services.backup_service.create_backup()``；
* 删除旧关联前必须过 ``services.delete_guard.require_physical_delete_enabled``，
  即需要环境变量 ``KAOYAN_ALLOW_PHYSICAL_DELETE=1``；
* 不碰院校域、``routers/``、前端、``quiz_questions.images``、``knowledge_chunks``。

用法
----
    python scripts/add_control_subject.py            # dry-run
    python scripts/add_control_subject.py --apply    # 写库（先备份）
"""
from __future__ import annotations

import argparse
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

SUBJECT = "自动控制原理"
SUBJECT_CODE = "automatic_control"
SHORT_NAME = "自控"
OLD_SUBJECT = "数学"
DESCRIPTION = "自动化与控制类考研专业课，胡寿松《自动控制原理》体系"

#: 圈题范围：连续整批，闭区间。
QUESTION_ID_MIN = 218
QUESTION_ID_MAX = 270

#: 学科门类照抄现有工科科目（电路），不硬编码枚举值。
CATEGORY_REFERENCE_SUBJECT = "电路"

# --------------------------------------------------------------------------- #
# 10 章章节树（胡寿松《自动控制原理》第 6 版）
# --------------------------------------------------------------------------- #
CHAPTER_DEFS: list[tuple[str, str]] = [
    ("ch01", "第1章 自动控制的一般概念"),
    ("ch02", "第2章 控制系统的数学模型"),
    ("ch03", "第3章 线性系统的时域分析法"),
    ("ch04", "第4章 线性系统的根轨迹法"),
    ("ch05", "第5章 线性系统的频域分析法"),
    ("ch06", "第6章 线性系统的校正方法"),
    ("ch07", "第7章 线性离散系统的分析与校正"),
    ("ch08", "第8章 非线性控制系统分析"),
    ("ch09", "第9章 线性系统的状态空间分析与综合"),
    ("ch10", "第10章 动态系统的最优控制方法"),
]
CHAPTER_TITLES = [t for _, t in CHAPTER_DEFS]

_CN = {n: f"第{n}章 " for n in range(1, 11)}
CH1, CH2, CH3, CH4, CH5 = CHAPTER_TITLES[0], CHAPTER_TITLES[1], CHAPTER_TITLES[2], CHAPTER_TITLES[3], CHAPTER_TITLES[4]
CH6, CH7, CH8, CH9, CH10 = CHAPTER_TITLES[5], CHAPTER_TITLES[6], CHAPTER_TITLES[7], CHAPTER_TITLES[8], CHAPTER_TITLES[9]

# --------------------------------------------------------------------------- #
# 逐题章节映射（按题干内容核定；合计 53 道）
#   第1章 4 / 第2章 10 / 第3章 3 / 第4章 11 / 第5章 15
#   第6章 3 / 第7章 3 / 第8章 2 / 第9章 2 / 第10章 0
# 说明：263–270 原挂「第10章」是整批误标，按正文重落：
#   263/268→第2章，264/270→第5章，265/266/269→第4章，267→第9章。
# --------------------------------------------------------------------------- #
QUESTION_CHAPTER: dict[int, str] = {}

for _qid in (218, 219, 220, 250):                       # 开环/闭环/线性系统
    QUESTION_CHAPTER[_qid] = CH1
for _qid in (221, 222, 223, 224, 225, 226, 245, 251, 263, 268):  # 传递函数/增益
    QUESTION_CHAPTER[_qid] = CH2
for _qid in (227, 228, 252):                            # 阶跃响应/脉冲响应
    QUESTION_CHAPTER[_qid] = CH3
for _qid in (229, 230, 231, 232, 233, 234, 235, 253, 265, 266, 269):  # 根轨迹
    QUESTION_CHAPTER[_qid] = CH4
for _qid in (236, 237, 238, 239, 240, 241, 242, 243, 244,
             246, 247, 248, 258, 264, 270):             # 频域/稳定裕度
    QUESTION_CHAPTER[_qid] = CH5
for _qid in (256, 257, 259):                            # 校正
    QUESTION_CHAPTER[_qid] = CH6
for _qid in (249, 254, 260):                            # 采样/脉冲传递
    QUESTION_CHAPTER[_qid] = CH7
for _qid in (261, 262):                                 # 极限环
    QUESTION_CHAPTER[_qid] = CH8
for _qid in (255, 267):                                 # 能控能观/状态转移
    QUESTION_CHAPTER[_qid] = CH9

# --------------------------------------------------------------------------- #
# 78 个知识点：每项 (name, description, keywords)
# 分布 7/8/8/8/9/7/8/7/8/8 = 78
# 约束：name ≥ 3 字；description ≥ 20 字。
# --------------------------------------------------------------------------- #
KP_DEFS: dict[str, list[tuple[str, str, list[str]]]] = {
    CH1: [
        ("开环控制系统",
         "输出量对控制过程不产生影响的系统，结构简单但抗扰能力较差。",
         ["开环", "输出量不影响"]),
        ("闭环控制系统",
         "利用反馈把输出量送回输入端比较并修正偏差的控制系统。",
         ["闭环", "反馈控制"]),
        ("反馈控制系统",
         "通过测量输出并与给定值比较形成偏差信号进行调节的系统。",
         ["反馈", "偏差", "给定"]),
        ("负反馈",
         "反馈信号与输入信号极性相反，用于减小偏差并提高系统稳定性。",
         ["负反馈", "反馈极性"]),
        ("自动控制系统组成",
         "由给定元件、比较元件、放大元件、执行元件和被控对象等部分构成。",
         ["组成", "被控对象", "执行元件"]),
        ("控制系统的分类",
         "按结构分为开环与闭环，按信号性质分为连续系统与离散系统。",
         ["分类", "线性系统", "连续系统"]),
        ("对控制系统的基本要求",
         "要求系统稳定、准确、快速，即通常所说的稳、准、快三项基本性能。",
         ["稳定", "准确", "快速", "要求"]),
    ],
    CH2: [
        ("传递函数",
         "零初始条件下输出与输入拉氏变换之比，描述线性定常系统的动态特性。",
         ["传递函数"]),
        ("结构图",
         "用方框、信号线和综合点表示系统各环节功能及信号传递关系的图形。",
         ["结构图", "方框", "图1", "图5-1", "图3-1"]),
        ("信号流图",
         "由节点和有向支路组成，可借助梅森增益公式求取系统传递函数的图形。",
         ["信号流图", "梅森"]),
        ("梅森增益公式",
         "用前向通路增益与回路增益计算系统闭环传递函数的通用公式。",
         ["梅森", "前向通路", "回路增益"]),
        ("拉普拉斯变换",
         "把时域微分方程转换为复频域代数方程的积分变换方法。",
         ["拉氏变换", "拉普拉斯", "s域"]),
        ("系统的线性化",
         "将非线性特性在工作点附近用泰勒展开的一阶项近似为线性模型。",
         ["线性化", "泰勒", "工作点"]),
        ("典型环节",
         "比例、积分、微分、惯性、振荡和延迟等构成系统的基本环节。",
         ["典型环节", "比例环节", "积分环节", "惯性环节"]),
        ("开环增益",
         "系统开环传递函数化为标准形式后各串联环节增益的乘积。",
         ["开环增益", "增益", "时间常数"]),
    ],
    CH3: [
        ("单位阶跃响应",
         "系统在单位阶跃输入作用下的输出响应，用于评价系统的动态性能。",
         ["阶跃响应", "单位阶跃"]),
        ("一阶系统",
         "传递函数只有一个极点的系统，其响应按指数规律单调变化。",
         ["一阶系统", "一阶"]),
        ("二阶系统",
         "传递函数含一对共轭极点的系统，响应可能振荡，形态由阻尼比决定。",
         ["二阶系统", "二阶"]),
        ("阻尼比",
         "描述二阶系统振荡衰减程度的参数，决定超调量和调节时间的大小。",
         ["阻尼比", "阻尼"]),
        ("超调量",
         "响应峰值超过稳态值的百分比，是衡量系统相对稳定性的重要指标。",
         ["超调"]),
        ("调节时间",
         "响应进入并保持在稳态值允许误差带内所需的最短时间。",
         ["调节时间", "过渡过程"]),
        ("稳态误差",
         "系统进入稳态后输出与期望值之间的差值，反映系统的稳态精度。",
         ["稳态误差"]),
        ("劳斯判据",
         "根据特征方程系数排列劳斯表，由首列符号变化判断系统稳定性。",
         ["劳斯", "特征方程", "稳定"]),
    ],
    CH4: [
        ("根轨迹",
         "开环增益从零变化到无穷时，闭环特征根在复平面上移动形成的轨迹。",
         ["根轨迹"]),
        ("根轨迹方程",
         "由幅值条件和相角条件共同给出的、闭环特征根所满足的方程。",
         ["根轨迹方程", "幅值条件", "相角条件"]),
        ("根轨迹渐近线",
         "开环极点数多于零点数时，根轨迹趋于无穷远所沿的方向线。",
         ["渐近线", "趋于无穷"]),
        ("分离点",
         "根轨迹在实轴上相遇后离开实轴进入复平面所对应的那一点。",
         ["分离点", "离开实轴"]),
        ("会合点",
         "根轨迹从复平面回到实轴并相遇的点，其坐标满足分离点方程。",
         ["会合点", "分离点方程"]),
        ("根轨迹相角条件",
         "根轨迹上任意一点都使开环传递函数的相角等于奇数倍一百八十度。",
         ["相角条件", "相角"]),
        ("主导极点",
         "距虚轴最近且对系统动态响应起决定作用的闭环极点。",
         ["主导极点", "闭环极点", "开环极点", "零极点"]),
        ("零度根轨迹",
         "正反馈或含非最小相位环节时，相角条件取零度所对应的根轨迹。",
         ["0°根轨迹", "零度根轨迹", "正反馈"]),
    ],
    CH5: [
        ("频率特性",
         "系统对正弦输入的稳态响应与输入之比随频率变化的函数关系。",
         ["频率特性", "正弦", "sin", "sint"]),
        ("幅频特性",
         "频率特性幅值随频率变化的规律，反映系统对不同频率信号的增益。",
         ["幅频", "幅值"]),
        ("相频特性",
         "频率特性相角随频率变化的规律，反映输出相对输入的相位滞后。",
         ["相频", "相移", "相位"]),
        ("奈奎斯特图",
         "频率特性在复平面上绘制的极坐标图，用于判断闭环系统的稳定性。",
         ["奈奎斯特", "极坐标图", "极坐标"]),
        ("伯德图",
         "由对数幅频特性和对数相频特性曲线组成的频率特性图。",
         ["伯德", "对数幅频", "对数坐标"]),
        ("相角裕度",
         "幅值穿越频率处相角与负一百八十度之差，衡量系统的相对稳定性。",
         ["相角裕", "相角裕度", "稳定裕", "稳定裕度", "稳定裕量"]),
        ("幅值裕度",
         "相角穿越频率处幅值的倒数取对数，表示系统增益允许增加的倍数。",
         ["幅值裕", "幅值裕度", "稳定裕"]),
        ("奈奎斯特稳定判据",
         "用开环频率特性曲线包围临界点的圈数来判断闭环系统稳定性。",
         ["奈奎斯特", "稳定判据", "临界点"]),
        ("最小相位系统",
         "开环零极点全部位于左半平面且无延迟，幅频与相频特性一一对应。",
         ["最小相位", "左半平面", "开环零点"]),
    ],
    CH6: [
        ("串联校正",
         "校正装置接在系统前向通道中，与前向环节串联连接的校正方式。",
         ["串联校正", "校正装置"]),
        ("超前校正",
         "利用超前网络提供相位超前角，从而提高相角裕度和系统快速性。",
         ["超前校正", "超前网络", "相位超前"]),
        ("滞后校正",
         "利用滞后网络提高低频增益，改善稳态精度而不明显影响稳定性。",
         ["滞后校正", "滞后网络"]),
        ("滞后超前校正",
         "兼有滞后和超前特性的校正网络，可同时改善稳态与动态性能。",
         ["滞后超前", "滞后-超前"]),
        ("PID控制器",
         "由比例、积分、微分环节组合而成，按偏差信号进行调节的控制器。",
         ["PID", "比例积分微分"]),
        ("比例积分控制",
         "引入积分环节消除稳态误差，同时用比例环节提高响应速度。",
         ["比例积分", "积分环节", "稳态误差"]),
        ("反馈校正",
         "在系统局部引入反馈构成内环，用反馈网络改变系统动态特性。",
         ["反馈校正", "局部反馈", "内环"]),
    ],
    CH7: [
        ("采样定理",
         "采样频率必须大于信号最高频率的两倍，才能无失真地恢复连续信号。",
         ["采样定理", "采样频率"]),
        ("Z变换",
         "把离散时间序列变换为复变量 z 的函数的数学工具，用于离散系统分析。",
         ["z变换", "Z变换"]),
        ("脉冲传递函数",
         "零初始条件下离散系统输出与输入 Z 变换之比，描述离散系统特性。",
         ["脉冲传递"]),
        ("零阶保持器",
         "把采样信号在一个采样周期内保持不变的环节，其传递函数为已知形式。",
         ["零阶保持", "保持器"]),
        ("离散系统稳定性",
         "闭环特征根全部位于 z 平面单位圆内时，离散系统才是稳定的。",
         ["离散", "单位圆", "稳定"]),
        ("双线性变换",
         "把 s 平面映射到 z 平面的近似变换方法，用于连续系统的离散化。",
         ["双线性", "离散化"]),
        ("采样周期选择",
         "需兼顾控制精度与计算负担，通常依据系统带宽和动态响应选取。",
         ["采样周期"]),
        ("离散系统稳态误差",
         "离散系统在典型输入下进入稳态后的误差，与系统型别和采样周期有关。",
         ["稳态误差", "零型", "采样控制"]),
    ],
    CH8: [
        ("非线性系统",
         "含有非线性元件或环节，不能直接套用线性理论进行分析的系统。",
         ["非线性"]),
        ("描述函数",
         "非线性环节在正弦输入下输出基波分量与输入正弦信号的复数比。",
         ["描述函数", "基波"]),
        ("相平面法",
         "以输出及其导数为坐标绘制系统运动轨迹，用来分析非线性系统。",
         ["相平面", "相轨迹"]),
        ("极限环",
         "非线性系统产生的等幅持续振荡，对应相平面上的封闭曲线。",
         ["极限环"]),
        ("相平面奇点",
         "相平面上系统速度与加速度同时为零的平衡点，分为多种类型。",
         ["奇点", "平衡点"]),
        ("自激振荡",
         "非线性系统在没有外部周期输入时产生的持续等幅振荡现象。",
         ["自激振荡", "持续振荡"]),
        ("非线性系统稳定性",
         "用描述函数法或相平面法判断平衡点与极限环稳定性的分析方法。",
         ["非线性", "稳定"]),
    ],
    CH9: [
        ("状态空间表达式",
         "由状态方程和输出方程组成，完整描述系统内部状态与外部输出关系。",
         ["状态空间", "状态方程", "输出方程"]),
        ("状态变量",
         "能够完全确定系统运动状态的最小一组变量，构成状态向量。",
         ["状态变量", "状态向量"]),
        ("状态转移矩阵",
         "描述零输入条件下状态随时间演化规律的矩阵指数函数。",
         ["状态转移", "矩阵指数"]),
        ("能控性",
         "存在控制输入使系统在有限时间内从任意初态到达任意终态的性质。",
         ["能控", "可控"]),
        ("能观性",
         "通过有限时间内的输出观测能够唯一确定系统初始状态的性质。",
         ["能观", "可观"]),
        ("能控标准型",
         "把系统状态方程化为便于分析与设计的特定标准结构形式。",
         ["能控标准型", "标准型"]),
        ("李雅普诺夫稳定性",
         "用能量型标量函数判断系统平衡点稳定性的第二方法。",
         ["李雅普诺夫"]),
        ("状态反馈",
         "把状态变量按比例反馈到输入端，用以配置闭环极点的控制方式。",
         ["状态反馈", "极点配置"]),
    ],
    CH10: [
        ("最优控制",
         "在给定约束条件下使性能指标达到极值的控制策略设计方法。",
         ["最优控制", "性能指标"]),
        ("性能指标",
         "衡量控制系统优劣的泛函，常取时间与能量加权的积分形式。",
         ["性能指标", "泛函"]),
        ("变分法",
         "求泛函极值的数学方法，用于求解无约束的最优控制问题。",
         ["变分法", "变分"]),
        ("极大值原理",
         "庞特里亚金提出的最优控制必要条件，由哈密顿函数取极值给出。",
         ["极大值原理", "哈密顿"]),
        ("动态规划",
         "贝尔曼提出的分阶段决策方法，利用最优性原理递推求解最优控制。",
         ["动态规划", "最优性原理"]),
        ("哈密顿函数",
         "最优控制中构造的辅助函数，其极值条件给出了最优控制律。",
         ["哈密顿"]),
        ("线性二次型调节器",
         "性能指标为状态与控制二次型时的最优状态反馈控制方法。",
         ["线性二次型", "二次型", "LQR"]),
        ("黎卡提方程",
         "线性二次型最优控制中用于求解最优反馈增益矩阵的微分方程。",
         ["黎卡提"]),
    ],
}

QUESTION_TYPES = ["选择", "填空", "计算", "分析", "设计", "证明"]


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #
def validate_definitions() -> None:
    """定义自检：章节分布、名称/释义长度。发现不合格直接抛错。"""
    expected = {"ch01": 7, "ch02": 8, "ch03": 8, "ch04": 8, "ch05": 9,
                "ch06": 7, "ch07": 8, "ch08": 7, "ch09": 8, "ch10": 8}
    actual = {code: len(KP_DEFS[title]) for code, title in CHAPTER_DEFS}
    if actual != expected:
        raise ValueError(f"知识点章节分布不符：{actual} != {expected}")
    total = sum(actual.values())
    if total != 78:
        raise ValueError(f"知识点总数应为 78，实际 {total}")
    for title, defs in KP_DEFS.items():
        for name, desc, _kw in defs:
            if len(name) < 3:
                raise ValueError(f"知识点名过短（<3字）：{name}")
            if len(desc) < 20:
                raise ValueError(f"知识点释义过短（<20字）：{name} -> {desc}")
    if len(QUESTION_CHAPTER) != 53:
        raise ValueError(f"逐题映射应覆盖 53 道，实际 {len(QUESTION_CHAPTER)}")
    if set(QUESTION_CHAPTER) != set(range(QUESTION_ID_MIN, QUESTION_ID_MAX + 1)):
        raise ValueError("逐题映射的 id 必须连续覆盖 218–270")


def score_kps(content: str, pool: list[dict], top: int = 3) -> list[dict]:
    """按关键词命中长度打分，取前 top 个。"""
    text = content or ""
    scored: list[tuple[int, int, dict]] = []
    for idx, kp in enumerate(pool):
        score = sum(len(kw) for kw in kp["keywords"] if kw and kw in text)
        if score:
            scored.append((score, -idx, kp))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [kp for _, _, kp in scored[:top]]


def match_kps(chapter: str, content: str, kps: list[dict]) -> list[tuple[dict, str, float]]:
    """在目标章节内匹配知识点；无命中时用本章前两个兜底，保证覆盖率。"""
    pool = [k for k in kps if k["chapter"] == chapter]
    if not pool:
        return []
    picked = score_kps(content, pool)
    if not picked:
        picked = pool[:2]
    return [
        (kp, "primary" if idx == 0 else "secondary", 1.0 if idx == 0 else 0.6)
        for idx, kp in enumerate(picked)
    ]


# --------------------------------------------------------------------------- #
# 数据库操作
# --------------------------------------------------------------------------- #
def ensure_subject(db) -> int:
    from sqlalchemy import text

    row = db.execute(text("SELECT id FROM subjects WHERE name = :n"), {"n": SUBJECT}).fetchone()
    if row:
        sid = int(row[0])
        db.execute(text("""
            UPDATE subjects
               SET short_name=:sn, is_active=true, is_custom=true,
                   description=COALESCE(NULLIF(description, ''), :d), updated_at=now()
             WHERE id=:sid
        """), {"sn": SHORT_NAME, "d": DESCRIPTION, "sid": sid})
        return sid

    category = db.execute(text(
        "SELECT category FROM subjects WHERE name=:n LIMIT 1"
    ), {"n": CATEGORY_REFERENCE_SUBJECT}).scalar()
    if not category:
        category = db.execute(text("SELECT category FROM subjects ORDER BY id LIMIT 1")).scalar()
    if not category:
        raise RuntimeError("subjects 表为空，无法确定 category 口径")

    sort_order = int(db.execute(text(
        "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM subjects"
    )).scalar() or 1)
    sid = db.execute(text("""
        INSERT INTO subjects
            (code, name, short_name, category, exam_overlap, description,
             sort_order, is_active, is_custom, legacy_names)
        VALUES
            (:code, :name, :sn, CAST(:cat AS subject_category), NULL, :d,
             :so, true, true, CAST(:legacy AS jsonb))
        RETURNING id
    """), {
        "code": SUBJECT_CODE, "name": SUBJECT, "sn": SHORT_NAME,
        "cat": str(category), "d": DESCRIPTION, "so": sort_order,
        "legacy": json.dumps(["自控", "自动控制"], ensure_ascii=False),
    }).scalar()
    return int(sid)


def ensure_subject_config(db, subject_id: int, chapters: dict[str, int]) -> None:
    """subject_config 是视图；首次插入会连带建章节，之后只更新题型。

    幂等要点：已存在时**不传 chapters**，否则视图触发器会「全删重插」章节，
    导致 quiz_questions.chapter_id 被 SET NULL。
    """
    from sqlalchemy import text

    exists = db.execute(text(
        "SELECT 1 FROM subject_config WHERE subject=:s"
    ), {"s": SUBJECT}).fetchone()
    types_json = json.dumps(QUESTION_TYPES, ensure_ascii=False)
    if exists:
        db.execute(text("""
            UPDATE subject_config
               SET question_types=CAST(:q AS jsonb), is_custom=true, updated_at=now()
             WHERE subject=:s
        """), {"q": types_json, "s": SUBJECT})
        return

    chapters_json = json.dumps(
        [{"code": code, "title": title} for code, title in CHAPTER_DEFS],
        ensure_ascii=False,
    )
    db.execute(text("""
        INSERT INTO subject_config (subject, chapters, question_types, is_custom)
        VALUES (:s, CAST(:c AS jsonb), CAST(:q AS jsonb), true)
    """), {"s": SUBJECT, "c": chapters_json, "q": types_json})

    # 若同名科目曾被删除，清墓碑，避免播种逻辑再判缺失
    if db.execute(text("SELECT to_regclass('subject_removals')")).scalar():
        db.execute(text("DELETE FROM subject_removals WHERE subject=:s"), {"s": SUBJECT})


def ensure_chapters(db, subject_id: int) -> dict[str, int]:
    from sqlalchemy import text

    out: dict[str, int] = {}
    for idx, (code, title) in enumerate(CHAPTER_DEFS, start=1):
        cid = db.execute(text("""
            INSERT INTO subject_chapters (subject_id, code, title, parent_id, sort_order, is_active)
            VALUES (:sid, :c, :t, NULL, :so, true)
            ON CONFLICT (subject_id, code)
            DO UPDATE SET title=EXCLUDED.title, sort_order=EXCLUDED.sort_order,
                          is_active=true, updated_at=now()
            RETURNING id
        """), {"sid": subject_id, "c": code, "t": title, "so": idx}).scalar()
        out[title] = int(cid)
    return out


def ensure_knowledge_points(db, subject_id: int, chapters: dict[str, int]) -> list[dict]:
    from sqlalchemy import text

    out: list[dict] = []
    for code, chapter_title in CHAPTER_DEFS:
        cid = chapters[chapter_title]
        for name, desc, keywords in KP_DEFS[chapter_title]:
            row = db.execute(text(
                "SELECT id FROM knowledge_points WHERE subject=:s AND name=:n ORDER BY id LIMIT 1"
            ), {"s": SUBJECT, "n": name}).fetchone()
            if row:
                kp_id = int(row[0])
                db.execute(text("""
                    UPDATE knowledge_points
                       SET subject_id=:sid, chapter_id=:cid, chapter=:ch,
                           description=:d, updated_at=now()
                     WHERE id=:i
                """), {"sid": subject_id, "cid": cid, "ch": chapter_title,
                        "d": desc, "i": kp_id})
            else:
                kp_id = int(db.execute(text("""
                    INSERT INTO knowledge_points
                        (name, subject_id, subject, chapter_id, chapter, extract_source,
                         subject_source, question_types, description, created_at, updated_at)
                    VALUES
                        (:n, :sid, :s, :cid, :ch, CAST('manual' AS extract_source),
                         'manual', CAST('[]' AS jsonb), :d, now(), now())
                    RETURNING id
                """), {
                    "n": name, "sid": subject_id, "s": SUBJECT, "cid": cid,
                    "ch": chapter_title, "d": desc,
                }).scalar())
            out.append({"id": kp_id, "name": name, "chapter": chapter_title,
                        "keywords": keywords})
    return out


def _delete_old_links(db, qids: list[int]) -> int:
    """删除指向非本学科知识点的历史关联（必须过物理删除闸门）。"""
    from sqlalchemy import bindparam, text
    from services.delete_guard import require_physical_delete_enabled

    stmt = text("""
        SELECT l.id
          FROM question_knowledge_links l
          JOIN knowledge_points kp ON kp.id = l.knowledge_point_id
         WHERE l.question_id IN :qids
           AND kp.subject IS DISTINCT FROM :s
    """).bindparams(bindparam("qids", expanding=True))
    ids = [int(r[0]) for r in db.execute(stmt, {"qids": qids, "s": SUBJECT}).fetchall()]
    if not ids:
        return 0

    require_physical_delete_enabled("question_knowledge_links")
    del_stmt = text(
        "DELETE FROM question_knowledge_links WHERE id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    db.execute(del_stmt, {"ids": ids})
    return len(ids)


def apply_questions(db, subject_id: int, chapters: dict[str, int],
                    kps: list[dict]) -> dict:
    from sqlalchemy import bindparam, text

    qids = sorted(QUESTION_CHAPTER)
    existing = {
        int(r[0]) for r in db.execute(
            text("SELECT id FROM quiz_questions WHERE id IN :qids")
            .bindparams(bindparam("qids", expanding=True)),
            {"qids": qids},
        ).fetchall()
    }
    missing = sorted(set(qids) - existing)
    if missing:
        raise RuntimeError(f"题库缺少预期题目 id：{missing}")

    old_deleted = _delete_old_links(db, qids)

    rows = db.execute(
        text("SELECT id, content FROM quiz_questions WHERE id IN :qids")
        .bindparams(bindparam("qids", expanding=True)),
        {"qids": qids},
    ).fetchall()
    contents = {int(r[0]): (r[1] or "") for r in rows}

    per_chapter: dict[str, int] = {t: 0 for t in CHAPTER_TITLES}
    link_count = 0
    for qid in qids:
        chapter = QUESTION_CHAPTER[qid]
        cid = chapters[chapter]
        matches = match_kps(chapter, contents[qid], kps)
        primary = matches[0][0]["name"] if matches else None

        db.execute(text("""
            UPDATE quiz_questions
               SET subject=:s, subject_id=:sid, chapter=:ch, chapter_id=:cid,
                   knowledge_point=:kp, updated_at=now()
             WHERE id=:qid
        """), {"s": SUBJECT, "sid": subject_id, "ch": chapter, "cid": cid,
                "kp": primary, "qid": qid})

        for kp, role, weight in matches:
            db.execute(text("""
                INSERT INTO question_knowledge_links
                    (question_id, knowledge_point_id, role, weight, is_verified, created_at)
                VALUES (:q, :k, :r, :w, false, now())
                ON CONFLICT (question_id, knowledge_point_id)
                DO UPDATE SET role=EXCLUDED.role, weight=EXCLUDED.weight
            """), {"q": qid, "k": kp["id"], "r": role, "w": weight})
            link_count += 1

        per_chapter[chapter] += 1

    return {"questions": len(qids), "links": link_count,
            "old_links_deleted": old_deleted, "per_chapter": per_chapter}


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def print_plan(plan_kps: list[dict]) -> None:
    print(f"\n待迁移题目：{len(QUESTION_CHAPTER)} 道（id {QUESTION_ID_MIN}–{QUESTION_ID_MAX}）")
    counts: dict[str, int] = {t: 0 for t in CHAPTER_TITLES}
    for qid in sorted(QUESTION_CHAPTER):
        counts[QUESTION_CHAPTER[qid]] += 1
    for code, title in CHAPTER_DEFS:
        print(f"  {title}: {counts[title]} 道")

    print(f"\n知识点计划：{len(plan_kps)} 个")
    for code, title in CHAPTER_DEFS:
        print(f"  {title}: {sum(1 for k in plan_kps if k['chapter'] == title)} 个")


def print_verify(db, subject_id: int) -> None:
    from sqlalchemy import text

    def one(sql: str, **params):
        return db.execute(text(sql), params).scalar()

    subj = db.execute(text(
        "SELECT id, name, is_active FROM subjects WHERE name=:s"
    ), {"s": SUBJECT}).fetchone()
    print("\n" + "=" * 78)
    print("验收")
    print("=" * 78)
    print(f"1) subjects: {tuple(subj) if subj else None}")
    print(f"2) subject_chapters: {one('SELECT count(*) FROM subject_chapters WHERE subject_id=:i', i=subject_id)}")
    print(f"3) quiz_questions: {one('SELECT count(*) FROM quiz_questions WHERE subject=:s', s=SUBJECT)}")
    print(f"4) knowledge_points: {one('SELECT count(*) FROM knowledge_points WHERE subject=:s', s=SUBJECT)}")
    covered = one("""
        SELECT count(DISTINCT l.question_id)
          FROM question_knowledge_links l
          JOIN knowledge_points kp ON kp.id = l.knowledge_point_id
         WHERE l.question_id BETWEEN :a AND :b AND kp.subject=:s
    """, a=QUESTION_ID_MIN, b=QUESTION_ID_MAX, s=SUBJECT)
    print(f"5) 218–270 重挂覆盖：{covered}/53")
    dist = db.execute(text("""
        SELECT chapter, count(*) FROM quiz_questions
         WHERE subject=:s GROUP BY chapter ORDER BY min(id)
    """), {"s": SUBJECT}).fetchall()
    print("   章节分布：")
    for ch, n in dist:
        print(f"     {ch}: {n} 道")


def main() -> int:
    parser = argparse.ArgumentParser(description="新增自动控制原理科目并归位误标题目")
    parser.add_argument("--apply", action="store_true", help="写库（默认 dry-run）")
    args = parser.parse_args()

    validate_definitions()

    plan_kps: list[dict] = []
    idx = 0
    for code, title in CHAPTER_DEFS:
        for name, desc, keywords in KP_DEFS[title]:
            idx += 1
            plan_kps.append({"id": -idx, "name": name, "chapter": title,
                             "keywords": keywords})

    if not args.apply:
        print("=" * 78)
        print("DRY-RUN（未写库）")
        print("=" * 78)
        print_plan(plan_kps)
        print("\n确认后执行：KAOYAN_ALLOW_PHYSICAL_DELETE=1 python scripts/add_control_subject.py --apply")
        return 0

    from sqlalchemy import text
    from database import SessionLocal
    from services.backup_service import create_backup

    backup_path = create_backup()
    print(f"[backup] {backup_path}")

    db = SessionLocal()
    try:
        sid = ensure_subject(db)
        chapters = ensure_chapters(db, sid)
        ensure_subject_config(db, sid, chapters)
        # 视图插入后章节 id 可能变化（首次建），重取一次
        chapters = ensure_chapters(db, sid)
        kps = ensure_knowledge_points(db, sid, chapters)
        stats = apply_questions(db, sid, chapters, kps)
        db.commit()

        print("\n" + "=" * 78)
        print("APPLY 完成")
        print("=" * 78)
        print(f"科目 id={sid}，章节 {len(chapters)} 章，知识点 {len(kps)} 个")
        print(f"归位题目 {stats['questions']} 道，重挂关联 {stats['links']} 条，"
              f"清除旧关联 {stats['old_links_deleted']} 条")
        for title, n in stats["per_chapter"].items():
            print(f"  {title}: {n} 道")
        print_verify(db, sid)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
