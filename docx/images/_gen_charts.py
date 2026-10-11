# -*- coding: utf-8 -*-
"""
V7.0 优化路线图 · 配图生成脚本
作者：许清楚（PM） · 2026-10-09
所有数字均来自 V6.0 审计实测（数据库只读查询 / 源码 grep / 手工清单解析），不在本脚本内创造新数字。
样式：暖纸底 #f4f1e9 · 墨蓝 #2f4b6e · 朱红 #b0442e · 暖灰 #83878f
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np
import os

# ---------- 样式常量（与平台设计令牌一致）----------
PAPER = '#f4f1e9'
INK   = '#2f4b6e'
RED   = '#b0442e'
GREY  = '#83878f'
GREEN = '#4a7a5c'   # 正向/可信
AMBER = '#c08a3e'   # 存疑
LGREY = '#d9d5c8'

plt.rcParams.update({
    'font.sans-serif': ['Microsoft YaHei', 'SimHei'],
    'axes.unicode_minus': False,
    'figure.facecolor': PAPER,
    'axes.facecolor': PAPER,
    'savefig.facecolor': PAPER,
    'text.color': INK,
    'axes.labelcolor': INK,
    'xtick.color': GREY,
    'ytick.color': GREY,
    'axes.edgecolor': LGREY,
    'font.size': 11,
})

OUT = os.path.dirname(os.path.abspath(__file__))


def finish(fig, ax, title, subtitle, source, fname, left=0.10):
    """统一收尾：标题 + 副标题 + 数据来源脚注。
    固定边距（不用 bbox_inches='tight'，否则 figure 坐标会漂移导致文字重叠）。
    left 需按 y 轴标签长度调整，避免长标签被裁切。"""
    fig.subplots_adjust(top=0.84, bottom=0.135, left=left, right=0.965)
    fig.text(0.012, 0.965, title, fontsize=17, fontweight='bold',
             color=INK, ha='left', va='top')
    fig.text(0.012, 0.893, subtitle, fontsize=11.5, color=RED, ha='left', va='top')
    fig.text(0.012, 0.020, source, fontsize=8.6, color=GREY, ha='left', va='bottom')
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    fig.savefig(os.path.join(OUT, fname), dpi=155)
    plt.close(fig)
    print('OK', fname)


# =====================================================================
# 01 问题严重度分布
# =====================================================================
def chart01():
    fig, ax = plt.subplots(figsize=(10.6, 5.5))
    labels = ['P0 阻断级', 'P1 结构性', 'P2 质量债', 'P3 整洁度']
    arch = [9, 14, 13, 8]
    tech = [3, 14, 21, 15]
    y = np.arange(len(labels))
    h = 0.34
    ax.barh(y + h/2, arch, h, label='架构审计报告', color=INK)
    ax.barh(y - h/2, tech, h, label='技术债检测报告', color=RED)
    for i, (a, t) in enumerate(zip(arch, tech)):
        ax.text(a + 0.35, i + h/2, str(a), va='center', fontsize=11, color=INK, fontweight='bold')
        ax.text(t + 0.35, i - h/2, str(t), va='center', fontsize=11, color=RED, fontweight='bold')
        ax.text(a + t + 1.5, i, f'合计 {a+t}', va='center', fontsize=10.5, color=GREY)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=12)
    ax.invert_yaxis()
    ax.set_xlabel('问题条数')
    ax.set_xlim(0, 42)
    ax.legend(loc='lower right', frameon=False, fontsize=11)
    ax.grid(axis='x', color=LGREY, lw=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    finish(fig, ax, '问题严重度分布：去重前 107 条，去重后约 60 条',
           'P0/P1 合计 40 条，占 37%—— 资源有限，必须先做 P0',
           '数据来源：V6.0 架构审计报告（9/14/13/8）+ 技术债检测报告（3/14/21/15）；README-V6.0审计总览「问题总量」表',
           '01-问题严重度分布.png', left=0.10)


# =====================================================================
# 02 择校数据可信度分级
# =====================================================================
def chart02():
    fig, ax = plt.subplots(figsize=(10.6, 5.8))
    cats = [
        ('可直接展示（值对，名需改）', 6, GREEN, '进面最低分 / 进面均分 / 进面人数\n录取人数 / 复录比 / 专业课均分'),
        ('需隐藏或整列作废', 7, RED, '复试线(假字段) · 国家线 · 政治线\n英语线 · 数学线 · 拟录取人数(伪造)'),
    ]
    left = 0
    for name, n, color, detail in cats:
        ax.barh([0], [n], left=left, height=0.42, color=color)
        ax.text(left + n/2, 0, f'{n} 个字段', ha='center', va='center',
                color='white', fontsize=15, fontweight='bold')
        ax.text(left + n/2, -0.34, detail, ha='center', va='top', fontsize=9.8, color=GREY)
        left += n
    ax.set_xlim(0, 13)
    ax.set_ylim(-0.95, 1.05)
    ax.set_yticks([])
    ax.set_xlabel('择校字段数（13 个错位字段分类）')
    ax.set_xticks(range(0, 14))
    ax.grid(axis='x', color=LGREY, lw=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    ax.annotate('', xy=(3, 0.36), xytext=(3, 0.86),
                arrowprops=dict(arrowstyle='-|>', color=INK, lw=1.6))
    ax.text(3, 0.90, '6 / 13 可直接用', ha='center', fontsize=13, color=GREEN,
            fontweight='bold')
    ax.text(9.5, 0.90, '7 / 13 必须隐藏', ha='center', va='center', fontsize=13,
            color=RED, fontweight='bold')
    finish(fig, ax, '择校数据可信度分级：13 个字段里只有 6 个能直接用',
           '「值对名错」6 个 —— 改前端标签即可 · 「不可用」7 个 —— 必须隐藏',
           '数据来源：开源对比与文档治理报告 §6.4.3 前端字段级降级建议（P0，可当天上线）；825 行全量回归',
           '02-择校数据可信度分级.png', left=0.10)


# =====================================================================
# 03 字段值对名错对照（命中率条形图）
# =====================================================================
def chart03():
    fig, ax = plt.subplots(figsize=(11.4, 7.4))
    rows = [
        ('enroll_count',   '进线人数 → 进面人数',      95.4, 'en: 进线人数'),
        ('retest_count',   '进复试人数 → 录取人数',    96.7, 'admitNum 录取人数'),
        ('retest_ratio',   '复录比（值正确）',          93.8, 'ratio 复录比'),
        ('total_line',     '总分线 → 进面最低分',93.8, 'enterMin 进面最低分'),
        ('retest_line',    '校复试线（假字段）',        93.8, 'enterMin 同一值'),
        ('admit_avg_score','录取均分 → 进面均分',      94.2, 'enterAvg 进面均分'),
        ('major_line',     '专业课线 → 专业课均分',     99.4, 'courseAvg 值正确'),
        ('math_line',      '数学线',3.3,  '实装 courseMid'),
        ('major_avg_score','专业课均分 → 数学均分',      1.0,  'mathAvg 数学均分'),
        ('politics_line',  '政治线',                   0.0,  '实装 enterMin'),
        ('national_line',  '国家线',                   0.0,  '空列0/811'),
        ('admit_count',    '拟录取人数（伪造列）',      33.2, '无对应数据源'),
    ]
    rows = sorted(rows, key=lambda r: r[2])
    names = [r[0] for r in rows]
    hits = [r[2] for r in rows]
    disp = [r[1] for r in rows]
    truth = [r[3] for r in rows]
    colors = [RED if h < 50 else (AMBER if h < 90 else GREEN) for h in hits]
    y = np.arange(len(rows))
    ax.barh(y, hits, 0.6, color=colors)
    for i, (h, d, t) in enumerate(zip(hits, disp, truth)):
        ax.text(h + 1.2, i, f'{h:.1f}%', va='center', fontsize=10.5,
                color=RED if h < 50 else INK, fontweight='bold')
        ax.text(-1.5, i + 0.19, d, ha='right', va='center', fontsize=10.2, color=INK)
        ax.text(-1.5, i - 0.21, f'真实装的是：{t}', ha='right', va='center', fontsize=8.4, color=GREY)
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=10.2, fontweight='bold')
    ax.set_ylim(-1.9, 11.9)
    ax.set_xlim(-58, 118)
    ax.set_xlabel('825 行全量回归命中率（%）')
    ax.axvline(50, color=RED, ls='--', lw=1.2, alpha=0.75)
    ax.text(51, -1.32, '50% 分界线：以下字段不可信', fontsize=9.8, color=RED)
    ax.axvline(90, color=GREEN, ls='--', lw=1.1, alpha=0.6)
    ax.text(91, -0.85, '90%：可直接使用', fontsize=9.8, color=GREEN)
    ax.grid(axis='x', color=LGREY, lw=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    lg = [Patch(facecolor=GREEN, label='≥90% 可直接用'),
          Patch(facecolor=AMBER, label='50–90% 需加警示'),
          Patch(facecolor=RED, label='<50% 不可用')]
    ax.legend(handles=lg, loc='upper left', bbox_to_anchor=(0.62, 0.40),
              frameon=True, facecolor=PAPER, edgecolor=LGREY, fontsize=9.6)
    finish(fig, ax, '字段「值对名错」对照：命中率决定处置方式',
           '红线以下 6 个字段必须隐藏或改名 —— 多数字段值是对的，只是名字错了',
           '数据来源：开源对比与文档治理报告 §6.3 逐字段全量回归（825/825 行全匹配，非抽样）',
           '03-字段值对名错对照.png', left=0.30)


# =====================================================================
# 04 三个失真指标
# =====================================================================
def chart04():
    fig, ax = plt.subplots(figsize=(10.8, 5.6))
    metrics = [
        ('分数线来源未核验\nunverified', 789, 811, RED),
        ('「校复试线」实为总分数线复制\ntotal_line = retest_line', 788, 811, RED),
        ('拟录取人数逻辑矛盾\nadmit_count < retest_count', 505, 786, AMBER),
    ]
    y = np.arange(len(metrics))
    for i, (name, num, den, color) in enumerate(metrics):
        pct = num / den * 100
        ax.barh(i, 100, 0.46, color=LGREY)
        ax.barh(i, pct, 0.46, color=color)
        ax.text(pct + 1.5, i, f'{num} / {den} = {pct:.1f}%', va='center',
                fontsize=12.5, color=color, fontweight='bold')
        ax.text(-1.5, i, name, ha='right', va='center', fontsize=11, color=INK)
    ax.set_yticks(y); ax.set_yticklabels([''] * 3)
    ax.invert_yaxis()
    ax.set_xlim(0, 118)
    ax.set_xlabel('占比（%）')
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.grid(axis='x', color=LGREY, lw=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    finish(fig, ax, '三个失真指标：择校数据的三处硬伤',
           '两个指标都超过 97% —— 择校页当前展示的多数数字不具备可信度',
           '数据来源：开源对比与文档治理报告 §6.4.1 六个实测数字（sqlite3只读查询，D:/平台/database/kaoyan.db）',
           '04-三处失真指标.png', left=0.235)


# =====================================================================
# 05 年份分布
# =====================================================================
def chart05():
    fig, ax = plt.subplots(figsize=(10.8, 5.8))
    years = ['2022', '2023', '2024', '2025', '2026', '2099']
    scor = [5, 5, 5, 7, 788, 1]
    admi = [0, 0, 0, 6, 825, 1]
    x = np.arange(len(years))
    w = 0.36
    b1 = ax.bar(x - w/2, scor, w, label='kaoyan_scorelines（分数线）', color=INK)
    b2 = ax.bar(x + w/2, admi, w, label='kaoyan_admissions（录取）', color=RED)
    for bars in (b1, b2):
        for r in bars:
            ax.text(r.get_x() + r.get_width()/2, r.get_height() + 14,
                    str(int(r.get_height())), ha='center', fontsize=10.5,
                    color=INK if r in list(b1) else RED, fontweight='bold')
    ax.set_xticks(x); ax.set_xticklabels(years, fontsize=12)
    ax.set_xlim(-0.6, 5.6)
    ax.set_ylabel('数据行数')
    ax.set_ylim(0, 980)
    ax.set_xlim(-0.65, 5.85)
    ax.legend(frameon=False, fontsize=11, loc='upper left')
    ax.grid(axis='y', color=LGREY, lw=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    ax.axvspan(0.5, 3.5, color=RED, alpha=0.07)
    ax.text(2, 860, '2022–2025：每年仅 5–7 行\n→ 无法做任何趋势对比', ha='center',
            fontsize=12, color=RED, fontweight='bold')
    ax.annotate('2099 年 1 行\n脏数据', xy=(5.0, 12), xytext=(5.28, 300),
                fontsize=10, color=RED,
                arrowprops=dict(arrowstyle='-|>', color=RED, lw=1.3))
    ax.text(0.0, 560, '趋势功能前置条件 4 项\n全部不满足', ha='center',
            fontsize=11.5, color=INK, style='italic')
    finish(fig, ax, '年份分布：只有一年数据，趋势功能不能做',
           '2026 年 788/825 行 vs 2022–2025 年各 5–7 行 —— 趋势图会是 1 个真点 + 4 个噪声点',
           '数据来源：开源对比与文档治理报告 §6.4.5（GROUP BY year 实测）；KaoyanAnalysis.jsx 依赖此维度',
           '05-年份分布与趋势可行性.png', left=0.10)


# =====================================================================
# 06 三阶段路线图甘特图
# =====================================================================
def chart06():
    fig, ax = plt.subplots(figsize=(11.6, 6.4))
    fig.subplots_adjust(top=0.80)
    tasks = [
        # (名称, 起始天, 长度, 并行度, 人时, 颜色)
        ('1.1 字段标签纠偏（13 字段）', 1, 1, 1, 5, INK),
        ('1.2 主题4 路→1 路收口',1, 1, 1, 2.5, INK),
        ('1.3 僵尸院校去重归档',   2, 1, 1, 3.5, INK),
        ('1.4 密钥/models/temp 清理', 1, 1, 1, 1, INK),
        ('1.5 虚拟环境 + 依赖锁定', 2, 1, 1, 3.5, INK),
        ('1.6 最小 CI（2 job）',    3, 1, 1, 2.5, INK),
        ('1.7 闪卡 {grade} 修复',  1, 1, 1, 0.5, INK),
        ('2.1 找回 txkyer 导入器', 4, 2, 1, 7, RED),
        ('2.2 择校 10 页 → 3 页',   4, 5, 2, 18, RED),
        ('2.3 224 处内联样式收口',  8, 3, 1, 11, RED),
        ('2.4 AI 网关收口',        6, 4, 1, 8, RED),
        ('2.5 死代码 + 吞异常清理', 9, 2, 1, 5, RED),
        ('2.6 修 9 个接口断链',     8, 3, 1, 7, RED),
        ('2.7 可信度看板 + 来源角标', 10, 2, 1, 5, RED),
        ('2.8 接入官网白名单校验',  11, 3, 1, 7, RED),
        ('2.9 BOM 剥离 + 协作规范', 12, 1, 1, 4, RED),
        ('3.1 官网白名单持续治理',  15, 8, 1, 10, AMBER),
        ('3.2 补参考书 (0/832)',   15, 3, 1, 9, AMBER),
        ('3.3 省份归一化 + 补 city', 15, 2, 1, 5, AMBER),
        ('3.4 加 UNIQUE(name) 约束', 17, 1, 1, 2, AMBER),
        ('3.5 预聚合视图',          18, 3, 1, 9, AMBER),
        ('3.6 补2022–2025 历史数据', 20, 8, 1, 50, LGREY),
        ('3.7 历年趋势（3.6 后才做）', 28, 3, 1, 11, LGREY),
    ]
    labels = [t[0] for t in tasks]
    for i, (name, s, ln, par, hrs, color) in enumerate(tasks):
        y = len(tasks) - i - 1
        ax.barh(y, ln, left=s, height=0.58, color=color, alpha=0.88)
        ax.text(s + ln + 0.22, y, f'{hrs:g}h', va='center', fontsize=9.2,
                color=GREY, fontweight='bold')
        if par > 1:
            ax.text(s + 0.15, y, f'并行{par}', va='center', ha='left',
                    fontsize=8.6, color='white', fontweight='bold')
    ax.set_yticks(range(len(tasks)))
    ax.set_yticklabels(labels[::-1], fontsize=9.6)
    ax.set_xlim(0, 33)
    ax.set_xlabel('工作日（并行 2 人）')
    for d, name, color in [(1.5, '阶段一 · 立即止损 25h', INK),
                           (8.0, '阶段二 · 结构性重构 60h', RED),
                           (19.0, '阶段三 · 能力建设 80h+', AMBER)]:
        ax.axvline(d, color=color, ls='--', lw=1.5, alpha=0.85)
        ax.text(d + 0.15, len(tasks) - 0.1, name, fontsize=10.5,
                color=color, fontweight='bold', va='top')
    ax.axvline(14.5, color=GREY, ls=':', lw=1.8)
    ax.text(14.6, -1.15, '▲ 阶段一不完成，不许开阶段二', fontsize=10.5,
            color=RED, fontweight='bold')
    ax.grid(axis='x', color=LGREY, lw=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    finish(fig, ax, '三阶段实施路线图：165 人时 · 并行 2 人约 11 个工作日',
           '灰色列为「3.6 补历史数据」50h—— 建议先做 50 所成本探针再决定是否启动',
           '数据来源：【优化路线图】V7.0 §2 三阶段路线图；阶段一 25h / 阶段二 60h / 阶段三 80h（不含补数 50h）',
           '06-三阶段路线图甘特图.png', left=0.235)


# =====================================================================
# 07 七方向投入产出四象限
# =====================================================================
def chart07():
    fig, ax = plt.subplots(figsize=(11.2, 8))
    dirs = [
        ('\u2460', 5,9.4, 1, '字段语义纠偏', GREEN),
        ('\u2461', 2.5, 7.2, 1, '主题收口',GREEN),
        ('\u2462', 3.5, 7.0, 3, '僵尸院校清理', INK),
        ('\u2463', 7, 8.6, 2, '找回导入器', INK),
        ('\u2464', 14, 7.8, 5, 'AI 网关收口', RED),
        ('\u2465', 5, 6.4, 1, '可信度可见化', INK),
        ('\u2466', 7.5, 8.0, 3, '官网白名单接入', INK),
    ]
    for code, cost, gain, risk, name, color in dirs:
        ax.scatter(cost, gain, s=230 + risk*105, color=color, alpha=0.80,
                   edgecolors=PAPER, linewidths=2.2, zorder=3)
        ax.text(cost, gain, code, ha='center', va='center', fontsize=13,
                color='white', fontweight='bold', zorder=4)
        ax.text(cost, gain - 0.62 - risk*0.045, name, ha='center', va='top',
                fontsize=10, color=INK, zorder=4)
    ax.axvline(6, color=LGREY, lw=1.5, zorder=1)
    ax.axhline(7.5, color=LGREY, lw=1.5, zorder=1)
    ax.set_xlim(0, 17); ax.set_ylim(4.85, 11)
    ax.set_xlabel('预估工作量（人时）→  越左越省力', fontsize=12)
    ax.set_ylabel('收益评分（1–10）→  越上越值得', fontsize=12)
    ax.text(0.35, 10.75, '★ 立即做：省力又高收益', fontsize=12.5,
            color=GREEN, fontweight='bold')
    ax.text(16.6, 10.75, '高投入高收益：排期做', fontsize=12, color='#9a6f2e',
            fontweight='bold', ha='right')
    ax.text(16.6, 5.2, '投入大收益低：不做', fontsize=12, color=GREY,
            fontweight='bold', ha='right')
    ax.text(0.35, 5.2, '低投入低收益：可缓', fontsize=12, color=GREY,
            fontweight='bold')
    ax.grid(color=LGREY, lw=0.7, alpha=0.7)
    ax.set_axisbelow(True)
    ax.text(0.30, 0.022, '气泡大小 = 风险等级（1 最低 · 5 最高）· 绿色 = P0 立即做',
            transform=ax.transAxes, fontsize=10, color=GREY)
    finish(fig, ax, '七个优化方向 · 投入产出四象限',
           '方向 ①②③ 落在左上「立即做」区 —— 三项合计仅 11 人时',
           '数据来源：【优化路线图】V7.0 §1（成本为各方向人时估算；收益与风险评分为 PM 基于审计实测数字的判断值）',
           '07-七方向投入产出四象限.png', left=0.095)


# =====================================================================
# 08 院校数据冗余
# =====================================================================
def chart08():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13.2, 5.7),
                                   gridspec_kw={'width_ratios': [1, 1.18]})
    # ---- 左：总行数 vs 唯一校名 ----
    axL.bar([0, 1], [493, 356], 0.44, color=[INK, GREEN])
    for i, v in enumerate([493, 356]):
        axL.text(i, v + 14, str(v), ha='center', fontsize=15, fontweight='bold',
                 color=INK)
    axL.set_xticks([0, 1])
    axL.set_xticklabels(['数据库总行数\nkaoyan_schools', '唯一校名\nCOUNT(DISTINCT name)'],
                        fontsize=11.5)
    axL.set_ylabel('行数', fontsize=11.5, color=INK)
    axL.set_ylim(0, 600)
    axL.set_xlim(-0.6, 1.6)
    axL.annotate('', xy=(0.26, 493), xytext=(0.74, 493),
                 arrowprops=dict(arrowstyle='<|-|>', color=RED, lw=1.7))
    axL.text(0.5, 512, '137 行冗余\n82 组重名', ha='center', fontsize=12,
             color=RED, fontweight='bold')
    axL.grid(axis='y', color=LGREY, lw=0.7, alpha=0.8)
    axL.set_axisbelow(True)
    axL.set_title('总量：493 行 → 356 所', fontsize=12.5, color=INK, pad=8)

    # ---- 右：按 data_source 拆分（同一坐标轴，可直接比高低）----
    names = ['school_official', 'seed_txkyer']
    vals = [268, 225]
    uniq = [131, 225]
    cols = [RED, GREEN]
    x = np.arange(2)
    axR.bar(x - 0.19, vals, 0.36, color=cols, label='总行数')
    axR.bar(x + 0.19, uniq, 0.36, color=cols, alpha=0.42,
            edgecolor=PAPER, linewidth=1.4, label='唯一校名')
    for i, (v, u) in enumerate(zip(vals, uniq)):
        axR.text(i - 0.19, v + 8, str(v), ha='center', fontsize=13,
                 fontweight='bold', color=cols[i])
        axR.text(i + 0.19, u + 8, str(u), ha='center', fontsize=13,
                 fontweight='bold', color=cols[i])
    axR.set_xticks(x)
    axR.set_xticklabels(['data_source=school_official\n（空壳院校）',
                         'data_source=seed_txkyer\n（数据完整）'], fontsize=11)
    axR.set_ylabel('院校行数', fontsize=11.5)
    axR.set_ylim(0, 330)
    axR.set_xlim(-0.55, 1.55)
    axR.grid(axis='y', color=LGREY, lw=0.7, alpha=0.8)
    axR.set_axisbelow(True)
    axR.text(0.5, 292, '268 行挂 0 专业 / 0 分数线 → 点进去是空白页',
             ha='center', fontsize=11, color=RED, fontweight='bold')
    axR.legend(frameon=False, fontsize=10.5, loc='upper right')
    axR.set_title('按来源拆分：54% 是空壳', fontsize=12.5, color=INK, pad=8)
    for sp in ('top', 'right'):
        axR.spines[sp].set_visible(False)
    finish(fig, axL, '院校数据冗余：493 行里只有 356 所真实院校',
           '重名 Top5：西安建筑科技大学 6 个 id（444/446/448/450/452/454）· 陕西科技大学 6 个 · 山东建筑大学 5 个',
           '数据来源：开源对比与文档治理报告 §6.4.4（GROUP BY name HAVING COUNT(*)>1 实测，共 82 组重名）',
           '08-院校数据冗余.png')


# =====================================================================
# 09 AI 四路径引用数
# =====================================================================
def chart09():
    fig, ax = plt.subplots(figsize=(10.6, 5.8))
    mods = [
        ('model_gateway.py\n15,361 B · 模型网关\n引用最多 → 网关雏形已存在', 10, GREEN, ''),
        ('ai_service.py\n43,368 B / 1001 行 · AI 服务\n承载全部 AI 能力，动它风险最高', 5, INK, ''),
        ('ai_router.py\n22,424 B · AI 路由\n与网关存在反向依赖', 3, INK, ''),
        ('ai_optimizer.py\n12,530 B · 性能优化\n仅被 1 个诊断端点引用', 1, AMBER, ''),
        ('ollama_service.py\n11,048 B · 死代码\n零引用 → 立即删除，零风险', 0, RED, ''),
    ]
    names = [m[0] for m in mods]
    vals = [m[1] for m in mods]
    colors = [m[2] for m in mods]
    y = np.arange(len(mods))
    ax.barh(y, vals, 0.55, color=colors)
    for i, (v, m) in enumerate(zip(vals, mods)):
        ax.text(v + 0.18, i, f'{v} 处', va='center', fontsize=13,
                fontweight='bold', color=m[2])
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=10.2)
    ax.set_xlabel('跨文件引用处数（grep -rl 实测）')
    ax.set_xlim(0, 12)
    ax.axvline(5, color=GREY, ls='--', lw=1.2, alpha=0.7)
    ax.text(5.08, 4.60, '← model_gateway 引用数已超过 ai_service →', fontsize=10.2,
            color=INK, fontweight='bold')
    ax.axvline(11.5, color=GREEN, ls=':', lw=1.3)
    ax.text(11.32, -0.62, '目标：全部收口到此一列', ha='right', fontsize=10.2,
            color=GREEN, fontweight='bold')
    ax.set_ylim(-1.05, 4.9)
    ax.grid(axis='x', color=LGREY, lw=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    finish(fig, ax, 'AI 能力 4 路并存：网关事实上已经存在',
           'model_gateway 被引用 10 处> ai_service 5 处 —— 所以是「扶正收口」，不是「推倒重建」',
           '数据来源：grep -rl 实测 backend-main-fastapi（2026-10-09）；择校推荐 kaoyan.py:214 为第 5 套独立决策逻辑，本次下线不做迁移',
           '09-AI四路径引用数.png', left=0.235)


# =====================================================================
# 10 优秀项目.txt 输入源问题
# =====================================================================
def chart10():
    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13.4, 5.9),
                                   gridspec_kw={'width_ratios': [1.15, 1]})
    # ---- 左：同一仓库被重复的次数分布 ----
    cats = ['仅出现 1 次', '出现 4 次', '出现 8 次']
    vals = [3, 82, 3]
    colors = [GREEN, RED, RED]
    x = np.arange(3)
    axL.bar(x, vals, 0.46, color=colors)
    for i, v in enumerate(vals):
        axL.text(i, v + 2.4, f'{v} 个', ha='center', fontsize=13,
                 fontweight='bold', color=colors[i])
    axL.set_xticks(x)
    axL.set_xticklabels(cats, fontsize=11.5)
    axL.set_ylabel('仓库数量（个）', fontsize=11.5)
    axL.set_xlabel('同一仓库 URL 在文件中被重复的次数', fontsize=11.5)
    axL.set_ylim(0, 100)
    axL.grid(axis='y', color=LGREY, lw=0.7, alpha=0.8)
    axL.set_axisbelow(True)
    axL.text(1, 92, '85 个仓库被重复粘贴\n（占 88 个的唯一 96.6%）',
             ha='center', fontsize=11.5, color=RED, fontweight='bold')
    axL.set_title('重复次数分布', fontsize=12.5, color=INK, pad=8)

    # ---- 右：A/B/C 三档处置 ----
    tiers = ['A 档 · 立即借鉴', 'B 档 · 单独立项', 'C 档 · 灵感池']
    tv = [4, 9, 75]
    tcol = [GREEN, AMBER, LGREY]
    y = np.arange(3)
    axR.barh(y, tv, 0.46, color=tcol)
    for i, v in enumerate(tv):
        axR.text(v + 1.8, i, f'{v} 个', va='center', fontsize=13,
                 fontweight='bold', color=[GREEN, '#9a6f2e', GREY][i])
    axR.set_yticks(y); axR.set_yticklabels(tiers, fontsize=11.5)
    axR.invert_yaxis()
    axR.set_xlabel('仓库数量（个）', fontsize=11.5)
    axR.set_xlim(0, 100)
    axR.grid(axis='x', color=LGREY, lw=0.7, alpha=0.8)
    axR.set_axisbelow(True)
    names = ['txkyer.cn / kaoyan-notifier\nD:////咨询 / pictureVerification',
             'OCR 链路 · 组卷 · 成长体系\n（约 6–8 个）',
             '其余约 75 个 · 归档不再作为任务来源\n只有具体需求出现时才回查']
    for i, n in enumerate(names):
        axR.text(1.5, i - 0.40, n, va='top', fontsize=9.0, color=GREY)
    axR.set_title('按处置分档', fontsize=12.5, color=INK, pad=8)
    finish(fig, axL, '输入源问题：优秀项目.txt 整段内容被重复粘贴',
           '88 个唯一仓库在正文被提及 355 次；其中 5 条数字陈述已被证伪（C6 答案覆盖率 15% → 实测 100%）',
           '数据来源：D:/桌面/优秀项目.txt 正则解析（2026-10-09，355 次提及 / 88 个唯一）；证伪项见开源对比与文档治理报告 §4.4',
           '10-输入源可靠性问题.png')
    # 右轴也去掉 top/right 边框
    for sp in ('top', 'right'):
        axR.spines[sp].set_visible(False)
    fig.savefig(os.path.join(OUT, '10-输入源可靠性问题.png'), dpi=155)
    plt.close(fig)
    print('OK 10-输入源可靠性问题.png')


if __name__ == '__main__':
    for fn in [chart01, chart02, chart03, chart04, chart05,
               chart06, chart07, chart08, chart09, chart10]:
        fn()
    print('\n全部 10 张图生成完毕 →', OUT)