# -*- coding: utf-8 -*-
"""扩充「模拟电子技术」知识点池 + 清理 q247-q254 的历史垃圾关联。

### 背景
``knowledge_points`` 里模拟电子技术只有 14 条，而 ``quiz_questions`` 有 95 道空
知识点模电题。``scripts/backfill_quiz_kp_semantic.py`` 的 ``--min-pool`` 默认 30，
模电整科被跳过（2026-10-20 基线：模电命中 0/95）。本脚本按 834 电子技术基础的
模电考纲补 90+ 条术语级知识点，使语义匹配有足够细的候选池。

### 设计
- 知识点清单硬编码在 ``KPS`` 里，按 (subject, name) 幂等去重，可重复执行。
- ``chapter`` 取 ``subject_chapters`` 里**真实存在**的章节（第1章…第10章），
  通过 ``第N章`` 前缀定位，写入 chapter_id + chapter 文本。
- 写库前 ``services.backup_service.create_backup()``；删除关联前
  ``services.delete_guard.require_physical_delete_enabled()``。
- 只动 ``knowledge_points`` 与 ``question_knowledge_links``（仅 q247-q254）。

用法：
    python scripts/expand_analog_kp.py                 # 预览（默认，不写库）
    python scripts/expand_analog_kp.py --apply         # 备份后写入知识点
    python scripts/expand_analog_kp.py --clean-links   # 预览垃圾关联
    python scripts/expand_analog_kp.py --clean-links --apply
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import psycopg  # noqa: E402

from pipeline.config import pg_database_url  # noqa: E402

SUBJECT_NAME = "模拟电子技术"
#: 垃圾关联排查范围（题干为自控/数学题，却被挂上「线性变换 / 反对称矩阵」等）
GARBAGE_QID_RANGE = (247, 254)
#: 判定为垃圾的知识点名（与题干中的控制系统内容毫无语义交集）
GARBAGE_KP_NAMES = ("积分上限函数", "微积分基本定理", "线性变换", "反对称矩阵")

#: (知识点名, 章节号, 一句话定义, 考频 0-5, 难度 1-5)
KPS: list[tuple[str, int, str, int, int]] = [
    # ---------------- 第1章 常用半导体器件 ----------------
    ("PN结单向导电性", 1,
     "PN结加正向电压时导通、加反向电压时截止的特性，是二极管整流与检波作用的物理基础。", 5, 2),
    ("杂质半导体", 1,
     "在本征半导体中掺入三价或五价杂质元素形成的P型或N型半导体，导电能力显著提高。", 4, 2),
    ("PN结势垒电容", 1,
     "PN结空间电荷区宽度随外加电压变化所表现出的电容效应，在高频分析中不可忽略。", 3, 4),
    ("二极管伏安特性", 1,
     "二极管端电压与电流之间的非线性关系，正向陡峭、反向平缓并存在反向击穿区。", 5, 2),
    ("二极管最大整流电流", 1,
     "二极管长期工作时允许通过的最大正向平均电流，超过该值会因结温过高而损坏。", 3, 2),
    ("稳压管稳压原理", 1,
     "稳压管工作在反向击穿区，电流在大范围内变化时端电压几乎不变，从而实现稳压。", 5, 2),
    ("稳压管动态电阻", 1,
     "稳压管在击穿区端电压变化量与电流变化量之比，数值越小稳压性能越好。", 4, 3),
    ("三极管电流放大系数", 1,
     "集电极电流与基极电流之比（共射组态记作β），表征三极管的电流控制能力。", 5, 2),
    ("三极管输出特性曲线", 1,
     "以基极电流为参量，集电极电流与管压降之间的关系曲线，可划分放大、饱和与截止区。", 5, 3),
    ("三极管饱和区", 1,
     "发射结正偏、集电结也正偏的工作区域，此时集电极电流不再随基极电流成比例增大。", 4, 3),
    ("三极管类型判别", 1,
     "根据三个电极电位的高低与极性判断晶体管是NPN型还是PNP型、是硅管还是锗管的方法。", 5, 3),
    ("三极管放大区", 1,
     "发射结正偏、集电结反偏的工作区域，此时集电极电流与基极电流近似成正比。", 5, 3),
    ("三极管截止区", 1,
     "发射结反偏或零偏、集电极电流近似为零的工作区域，三极管相当于断开的开关。", 4, 3),
    # ---------------- 第2章 基本放大电路 ----------------
    ("共射放大电路", 2,
     "输入接基极、输出取自集电极的放大电路，电压放大倍数较大且输出与输入反相。", 5, 2),
    ("共集放大电路", 2,
     "输出取自发射极的电压跟随器电路，电压增益略小于1、输入电阻高、输出电阻低。", 5, 3),
    ("共基放大电路", 2,
     "输入接发射极、输出取自集电极的放大电路，频带宽、输入电阻低、无电流放大作用。", 4, 3),
    ("静态工作点", 2,
     "输入信号为零时晶体管的基极电流、集电极电流和管压降所对应的一组直流量。", 5, 3),
    ("直流通路", 2,
     "直流电源作用下将耦合电容视为开路所得的电流通路，用于计算静态工作点。", 4, 2),
    ("交流通路", 2,
     "交流信号作用下将耦合电容与直流电源视为短路所得的等效通路，用于动态分析。", 4, 3),
    ("微变等效电路", 2,
     "把晶体管在小信号范围内线性化为受控源模型所得的等效电路，用于计算动态参数。", 5, 4),
    ("晶体管输入电阻rbe", 2,
     "微变等效模型中基极与发射极之间的等效电阻，随静态工作电流增大而减小。", 4, 3),
    ("放大电路输入电阻", 2,
     "从放大电路输入端看进去的等效电阻，决定电路对信号源电压的衰减程度。", 5, 3),
    ("放大电路输出电阻", 2,
     "从负载端向放大电路看进去的戴维南等效内阻，决定电路的带负载能力。", 5, 3),
    ("饱和失真", 2,
     "静态工作点偏高使输出电压正半周进入饱和区而被削顶所产生的非线性失真。", 5, 3),
    ("截止失真", 2,
     "静态工作点偏低使输出电压负半周进入截止区而被削顶所产生的非线性失真。", 5, 3),
    ("分压式偏置稳定原理", 2,
     "用基极分压电阻固定基极电位，并以发射极电阻引入直流负反馈来稳定静态工作点。", 5, 3),
    ("射极旁路电容", 2,
     "与发射极电阻并联的电容，交流时将其短路以避免交流负反馈、提高电压放大倍数。", 4, 3),
    ("复合管", 2,
     "两只晶体管按达林顿方式连接而成的等效管，电流放大系数近似为两管之积。", 4, 3),
    # ---------------- 第2章 场效应管放大 ----------------
    ("结型场效应管", 2,
     "利用PN结耗尽层宽度控制导电沟道截面积的场效应管，输入电阻高、属耗尽型器件。", 4, 3),
    ("绝缘栅场效应管", 2,
     "以栅极电场经氧化层控制沟道导电能力的场效应管，即金属氧化物半导体场效应管。", 5, 3),
    ("增强型MOS管", 2,
     "栅源电压为零时不存在导电沟道、必须加足够正的栅压才能导通的MOS场效应管。", 4, 3),
    ("耗尽型MOS管", 2,
     "栅源电压为零时已存在导电沟道、栅压可正可负的MOS场效应管。", 3, 3),
    ("跨导gm", 2,
     "漏极电流变化量与栅源电压变化量之比，表征场效应管的栅压控制漏流能力。", 5, 4),
    ("场效应管转移特性", 2,
     "漏源电压恒定时漏极电流随栅源电压变化的曲线，反映栅极对沟道的控制作用。", 4, 3),
    ("场效应管自偏置电路", 2,
     "利用源极电阻上的直流压降为栅极提供反向偏置电压的场效应管偏置方式。", 4, 3),
    ("场效应管分压式偏置", 2,
     "用栅极分压电阻设定栅极电位、配合源极电阻确定静态工作点的偏置方式。", 4, 3),
    # ---------------- 第3章 多级放大电路 ----------------
    ("多级放大电路耦合方式", 3,
     "各级之间采用阻容、直接或变压器连接的方式，决定电路的低频响应与直流传输能力。", 5, 3),
    ("阻容耦合", 3,
     "用耦合电容把前级输出接到后级输入的方式，各级静态工作点独立但低频响应较差。", 4, 2),
    ("直接耦合", 3,
     "各级直接相连的耦合方式，能放大直流和缓慢变化信号，但存在零点漂移问题。", 5, 3),
    ("多级放大倍数", 3,
     "各级电压放大倍数的乘积，计算时必须计入后级输入电阻对前级的负载效应。", 5, 3),
    ("零点漂移", 3,
     "直接耦合放大电路在输入为零时输出随时间缓慢变化的现象，主要由温度变化引起。", 5, 3),
    # ---------------- 第5章 放大电路的频率响应 ----------------
    ("幅频特性", 5,
     "电压放大倍数的模随频率变化的规律，描述电路对不同频率信号的放大能力。", 5, 3),
    ("相频特性", 5,
     "输出电压与输入电压之间的相位差随频率变化的规律，与幅频特性共同描述频率响应。", 4, 3),
    ("下限截止频率", 5,
     "放大倍数下降到中频值的0.707倍时所对应的较低频率，主要受耦合电容与旁路电容影响。", 5, 4),
    ("上限截止频率", 5,
     "放大倍数下降到中频值的0.707倍时所对应的较高频率，主要受晶体管结电容影响。", 5, 4),
    ("通频带", 5,
     "上限截止频率与下限截止频率之间的频率范围，表征电路能够有效放大的频段宽度。", 5, 3),
    ("波特图", 5,
     "以对数频率为横坐标分别绘制幅频与相频渐近线的图形，用于分析电路的频率响应。", 4, 4),
    ("增益带宽积", 5,
     "电压放大倍数与通频带的乘积，在深度负反馈下近似为常数，是运放的重要指标。", 5, 4),
    ("密勒效应", 5,
     "跨接在输入与输出之间的电容等效到输入端后容量被放大的现象，限制电路高频响应。", 4, 5),
    ("晶体管特征频率", 5,
     "共射电流放大系数下降到1时所对应的频率，表征晶体管的高频放大能力。", 4, 4),
    # ---------------- 第6章 放大电路中的反馈 ----------------
    ("反馈网络", 6,
     "把输出量的一部分或全部送回输入端的电路环节，其结构与接法决定反馈组态。", 5, 3),
    ("负反馈判别方法", 6,
     "用瞬时极性法判断反馈极性的方法：反馈信号使净输入量减小即为负反馈。", 5, 2),
    ("串联负反馈", 6,
     "反馈信号以电压形式与输入电压串联叠加的反馈组态，能够提高电路的输入电阻。", 5, 3),
    ("并联负反馈", 6,
     "反馈信号以电流形式在输入端并联叠加的反馈组态，能够降低电路的输入电阻。", 5, 3),
    ("电压负反馈", 6,
     "反馈信号取自输出电压的组态，能够稳定输出电压并降低电路的输出电阻。", 5, 3),
    ("电流负反馈", 6,
     "反馈信号取自输出电流的组态，能够稳定输出电流并提高电路的输出电阻。", 5, 3),
    ("深度负反馈", 6,
     "环路增益远大于1时闭环增益近似等于反馈系数的倒数，与晶体管参数几乎无关。", 5, 4),
    ("反馈深度", 6,
     "一加环路增益所得的量，表征负反馈对放大倍数的削弱程度，也影响频带与失真。", 4, 4),
    ("负反馈自激振荡", 6,
     "负反馈环路附加相移达到180度且环路增益不小于1时产生的持续高频振荡。", 5, 4),
    ("相位裕度", 6,
     "环路增益幅值降到1时附加相移距180度的差值，用于判断闭环系统是否稳定。", 5, 4),
    ("增益裕度", 6,
     "附加相移达到180度时环路增益幅值距1的差距，衡量闭环系统的相对稳定程度。", 4, 4),
    ("反馈系数", 6,
     "反馈信号与输出信号的比值，在深度负反馈条件下其倒数即为闭环放大倍数。", 5, 3),
    # ---------------- 第9章 功率放大电路 ----------------
    ("甲类功率放大", 9,
     "晶体管在整个信号周期内均导通的功放工作状态，失真小但静态功耗大、效率低。", 4, 3),
    ("乙类功率放大", 9,
     "晶体管仅在半个信号周期内导通的功放工作状态，效率高但存在交越失真。", 5, 3),
    ("甲乙类功率放大", 9,
     "晶体管导通时间大于半个信号周期的功放工作状态，兼顾效率并消除交越失真。", 5, 3),
    ("互补对称功率放大", 9,
     "用NPN与PNP两只晶体管互补工作、分别放大正负半周的功率放大电路结构。", 5, 3),
    ("OCL功率放大电路", 9,
     "采用双电源供电、输出端不接耦合电容的互补对称功率放大电路。", 5, 3),
    ("OTL功率放大电路", 9,
     "采用单电源供电、输出端经大容量电容耦合到负载的互补对称功率放大电路。", 5, 3),
    ("功率放大电路效率", 9,
     "输出交流功率与电源提供的直流功率之比，乙类互补对称电路理论最大值约78.5%。", 5, 4),
    ("功率管最大管耗", 9,
     "功率放大电路中晶体管允许消耗的最大功率，是选择功放管型号的主要依据。", 4, 4),
    # ---------------- 第4章 集成运算放大电路 ----------------
    ("差分放大电路", 4,
     "由两只对称晶体管构成、只放大两个输入端电压之差的直接耦合放大电路。", 5, 3),
    ("共模信号", 4,
     "两个输入端大小相等、极性相同的输入信号，差分放大电路应予以充分抑制。", 5, 3),
    ("差模信号", 4,
     "两个输入端大小相等、极性相反的输入信号，是差分放大电路要放大的对象。", 5, 3),
    ("共模抑制比", 4,
     "差模放大倍数与共模放大倍数之比的绝对值，衡量差分电路抑制共模干扰的能力。", 5, 4),
    ("差模输入电阻", 4,
     "差分放大电路两输入端之间对差模信号呈现的等效电阻，反映对信号源的负载效应。", 4, 4),
    ("恒流源偏置", 4,
     "用恒流源代替发射极电阻为差分对管提供偏置，可显著提高共模抑制能力。", 5, 4),
    ("长尾式差分电路", 4,
     "两管发射极共接大阻值电阻并接负电源的差分放大电路，依靠电阻抑制共模信号。", 4, 3),
    ("输入失调电压", 4,
     "使差分放大电路输出电压为零时需要在输入端施加的补偿电压，反映电路的不对称程度。", 4, 4),
    # ---------------- 第7章 信号的运算和处理 ----------------
    ("集成运算放大器", 7,
     "由差分输入级、中间放大级和互补输出级集成而成的高增益直接耦合放大电路。", 5, 2),
    ("虚短与虚断", 7,
     "运放线性工作时两输入端电位近似相等、输入电流近似为零的两条分析依据。", 5, 3),
    ("反相比例运算电路", 7,
     "输入信号经电阻接到反相端、同相端接地的闭环电路，输出反相且增益由电阻比决定。", 5, 3),
    ("同相比例运算电路", 7,
     "输入信号接同相端的闭环运算电路，输出与输入同相且输入电阻很高。", 5, 3),
    ("电压跟随器", 7,
     "输出直接反馈到反相端的同相比例电路，电压增益为1、输入电阻极高。", 4, 2),
    ("加法运算电路", 7,
     "多个输入信号分别经各自电阻接到反相端以实现代数求和的运算电路。", 4, 3),
    ("减法运算电路", 7,
     "利用差分输入结构使输出与两个输入电压之差成正比的运算电路。", 4, 3),
    ("积分运算电路", 7,
     "反馈支路用电容构成的运放电路，输出电压与输入电压对时间的积分成正比。", 5, 3),
    ("微分运算电路", 7,
     "输入支路用电容构成的运放电路，输出电压与输入电压对时间的变化率成正比。", 5, 3),
    ("对数运算电路", 7,
     "反馈支路用二极管构成的运放电路，输出电压与输入电压的对数成正比。", 4, 4),
    ("指数运算电路", 7,
     "输入支路用二极管构成的运放电路，输出电压与输入电压的指数成正比。", 4, 4),
    ("仪表放大电路", 7,
     "由三个运放构成、输入电阻高、共模抑制比大且增益可调的测量用放大电路。", 4, 4),
    ("有源滤波器", 7,
     "由集成运放与RC网络共同构成、兼有信号放大作用的滤波电路。", 4, 4),
    # ---------------- 第8章 波形的产生和信号的转换 ----------------
    ("电压比较器", 8,
     "比较两个输入电压大小并以输出高、低电平表示比较结果的电路，运放多处于非线性区。", 5, 3),
    ("滞回比较器", 8,
     "带有正反馈的比较器，其翻转阈值随输出状态改变，因而具有较强的抗干扰能力。", 5, 4),
    ("方波发生器", 8,
     "由滞回比较器与RC充放电回路构成、输出矩形方波的波形产生电路。", 4, 3),
    ("三角波发生器", 8,
     "由滞回比较器与积分器级联构成、输出三角波的波形产生电路。", 4, 4),
    ("RC桥式振荡电路", 8,
     "以RC串并联网络作为选频与反馈环节、产生正弦波信号的振荡电路。", 5, 4),
    ("振荡条件", 8,
     "振荡器维持稳定振荡所需的幅值条件与相位条件，即环路增益不小于1且总相移为360度整数倍。", 5, 4),
    ("波形变换电路", 8,
     "把一种波形变换为另一种波形的电路，例如比较器把正弦波变为方波、积分器把方波变为三角波。", 4, 4),
    ("石英晶体振荡器", 8,
     "利用石英晶体的压电效应及其高Q值谐振特性获得极高频率稳定度的振荡电路。", 3, 3),
    # ---------------- 第10章 直流电源 ----------------
    ("单相桥式整流电路", 10,
     "由四只二极管接成桥式结构、在正负半周均有电流输出的整流电路。", 5, 3),
    ("电容滤波电路", 10,
     "在负载两端并联滤波电容、利用其充放电过程减小输出脉动电压的滤波电路。", 5, 3),
    ("三端集成稳压器", 10,
     "只有输入端、输出端和公共端三个引脚的集成稳压器件，如78xx与79xx系列。", 5, 2),
    ("调整管", 10,
     "串联型稳压电路中受比较放大环节控制、通过改变自身压降来稳定输出的功率管。", 4, 3),
    ("整流输出电压", 10,
     "整流后负载上得到的直流平均电压，桥式整流约为变压器副边电压有效值的0.9倍。", 4, 3),
]


#: 描述精修：首轮 dry-run 发现这几条的释义与题目里的高频词错位，导致 top1
#: 被语义相近的邻居吸走（例：问「输入电阻」被「输出电阻」抢走、问「RE 的作用」
#: 被「共模信号」抢走）。这里只改 description，不动条目本身，可重复执行。
RENAME: dict[str, str] = {
    "仪用放大电路": "仪表放大电路",
}

REFINE: dict[str, str] = {
    "共模信号":
        "两个输入端大小相等、极性相同的输入信号，放大电路应对其充分抑制。",
    "长尾式差分电路":
        "两管发射极共接大阻值电阻RE并接负电源的差分放大电路，RE对共模信号引入强负反馈。",
    "通频带":
        "上限截止频率与下限截止频率之间的频率范围；多级放大电路级数越多，通频带越窄。",
    "放大电路输出电阻":
        "从负载端向放大电路看进去的戴维南等效内阻，决定带负载能力，可由负载开路与带载时的输出电压之比求得。",
    "二极管伏安特性":
        "二极管端电压与电流之间的非线性关系，正向电压稍有增加正向电流便急剧增大，反向时电流很小并存在击穿区。",
    "二极管最大整流电流":
        "二极管允许长期通过的最大正向平均电流值，是选型时按负载电流校核的极限参数。",
    "功率放大电路效率":
        "输出交流功率与电源提供的直流功率之比；负载上可获得的不失真最大交流功率称为最大输出功率。",
}


def connect(retries: int = 6):
    """连接 PG；后台 postgres 偶发未就绪时重试，绝不自行启停数据库。"""
    last = None
    for i in range(retries):
        try:
            return psycopg.connect(pg_database_url())
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"[retry {i + 1}/{retries}] 连接失败：{exc}")
            time.sleep(3)
    raise RuntimeError(f"无法连接 PostgreSQL：{last}")


def check_names(kps) -> None:
    """落库前的名称质检：≥3 字、非泛词、不与已有条目重复。"""
    banned = {"放大", "放大电路", "反馈", "负反馈", "电路", "信号", "系统", "运放"}
    seen = set()
    for name, *_ in kps:
        assert len(name) >= 3, f"知识点名过短：{name}"
        assert name not in banned, f"泛词不允许作为知识点名：{name}"
        assert name not in seen, f"清单内重名：{name}"
        seen.add(name)


def cmd_apply_kps(apply: bool) -> int:
    check_names(KPS)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM subjects WHERE name = %s", (SUBJECT_NAME,))
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"找不到学科「{SUBJECT_NAME}」")
            subject_id = row[0]

            cur.execute(
                "SELECT id, title FROM subject_chapters WHERE subject_id = %s ORDER BY id",
                (subject_id,),
            )
            chapters = cur.fetchall()
            chapter_by_no = {}
            for cid, title in chapters:
                head = title.split()[0] if title else ""
                if head.startswith("第") and head.endswith("章"):
                    try:
                        chapter_by_no[int(head[1:-1])] = (cid, title)
                    except ValueError:
                        pass

            cur.execute(
                "SELECT name FROM knowledge_points WHERE subject = %s", (SUBJECT_NAME,)
            )
            existing = {r[0].strip() for r in cur.fetchall()}

            todo = []
            for name, ch_no, desc, freq, diff in KPS:
                if name in existing:
                    continue
                if ch_no not in chapter_by_no:
                    raise SystemExit(f"章节 第{ch_no}章 在 subject_chapters 中不存在")
                todo.append((name, ch_no, desc, freq, diff))

            print(f"[kp] 学科 {SUBJECT_NAME}(id={subject_id})，现有 {len(existing)} 条，"
                  f"本次待插入 {len(todo)} 条（清单 {len(KPS)} 条）")
            by_ch = {}
            for name, ch_no, *_ in todo:
                by_ch[chapter_by_no[ch_no][1]] = by_ch.get(chapter_by_no[ch_no][1], 0) + 1
            for title, n in by_ch.items():
                print(f"    {title}: +{n}")

            renames = [(old, new) for old, new in RENAME.items()
                       if old in existing and new not in existing]
            refine = [n for n in REFINE if n in existing | {t[0] for t in todo}]
            print(f"[refine] 描述精修 {len(refine)} 条：{'、'.join(refine) if refine else '无'}")
            if renames:
                print("[rename] 名称订正：" + "、".join(f"{o}→{n}" for o, n in renames))

            if not apply:
                print("\n[DRY-RUN] 未写库；加 --apply 执行。")
                return 0
            if not todo and not refine and not renames:
                print("[OK] 无新增、无需精修，幂等退出。")
                return 0

            from services.backup_service import create_backup

            print(f"[backup] {create_backup()}")

            for old, new in renames:
                cur.execute(
                    "UPDATE knowledge_points SET name = %s WHERE subject = %s AND name = %s",
                    (new, SUBJECT_NAME, old),
                )

            inserted = 0
            for name, ch_no, desc, freq, diff in todo:
                cid, title = chapter_by_no[ch_no]
                cur.execute(
                    """
                    INSERT INTO knowledge_points
                        (name, subject_id, subject, chapter_id, chapter, description,
                         exam_frequency, difficulty, question_types, extract_source, subject_source)
                    SELECT %s, %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, NULL, 'manual'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM knowledge_points WHERE subject = %s AND name = %s
                    )
                    """,
                    (name, subject_id, SUBJECT_NAME, cid, title, desc, freq, diff,
                     SUBJECT_NAME, name),
                )
                inserted += cur.rowcount

            refined = 0
            for name, desc in REFINE.items():
                cur.execute(
                    "UPDATE knowledge_points SET description = %s"
                    " WHERE subject = %s AND name = %s AND description IS DISTINCT FROM %s",
                    (desc, SUBJECT_NAME, name, desc),
                )
                refined += cur.rowcount
        conn.commit()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM knowledge_points WHERE subject = %s", (SUBJECT_NAME,)
            )
            print(f"[OK] 新增 {inserted} 条、精修 {refined} 条；"
                  f"模拟电子技术知识点现有 {cur.fetchone()[0]} 条")
    return 0


def cmd_clean_links(apply: bool) -> int:
    lo, hi = GARBAGE_QID_RANGE
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT q.id, left(replace(q.content, E'\n', ' '), 50), lk.id,
                       kp.name, lk.weight
                FROM quiz_questions q
                JOIN question_knowledge_links lk ON lk.question_id = q.id
                JOIN knowledge_points kp ON kp.id = lk.knowledge_point_id
                WHERE q.id BETWEEN %s AND %s AND kp.name = ANY(%s)
                ORDER BY q.id, kp.name
                """,
                (lo, hi, list(GARBAGE_KP_NAMES)),
            )
            rows = cur.fetchall()
            print(f"[links] q{lo}-q{hi} 命中垃圾知识点关联 {len(rows)} 条")
            for qid, snippet, _lid, name, w in rows:
                print(f"  q{qid} 「{name}」w={w}  题干：{snippet}")
            if not rows:
                print("[OK] 无垃圾关联，幂等退出。")
                return 0
            if not apply:
                print("\n[DRY-RUN] 未删除；加 --apply 执行。")
                return 0

            # 项目铁律：删除前必须过物理删除闸门 + 备份
            from services.delete_guard import require_physical_delete_enabled

            require_physical_delete_enabled("question_knowledge_links")
            from services.backup_service import create_backup

            print(f"[backup] {create_backup()}")

            ids = [r[2] for r in rows]
            cur.execute(
                "DELETE FROM question_knowledge_links WHERE id = ANY(%s)", (ids,)
            )
            deleted = cur.rowcount
        conn.commit()
        print(f"[OK] 已删除垃圾关联 {deleted} 条")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="扩充模电知识点 / 清理垃圾关联")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认只预览）")
    ap.add_argument("--clean-links", action="store_true", help="处理 q247-q254 垃圾关联")
    args = ap.parse_args()
    if args.clean_links:
        return cmd_clean_links(args.apply)
    return cmd_apply_kps(args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
