# -*- coding: utf-8 -*-
"""生成全栈缺陷诊断与修复图示（供 docs 归档）。"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager

OUT = r"D:\平台\docs\figures"
os.makedirs(OUT, exist_ok=True)

for _f in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc"]:
    try:
        font_manager.fontManager.addfont(_f)
    except Exception:
        pass
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

GREEN_BG, GREEN_LN, GREEN_TX = "#EAF3DE", "#639922", "#173404"
RED_BG, RED_LN, RED_TX = "#FCEBEB", "#E24B4A", "#501313"
AMB_BG, AMB_LN, AMB_TX = "#FAEEDA", "#BA7517", "#412402"
BLU_BG, BLU_LN, BLU_TX = "#E6F1FB", "#378ADD", "#042C53"
GRY_BG, GRY_LN, GRY_TX = "#F1EFE8", "#888780", "#2C2C2A"
LINE_H = 0.037          # 行高
TITLE_GAP = 0.052       # 标题到首行的间距


def box(ax, x, y, w, h, title, lines, bg, ln, tx, fs_title=12.5, fs_body=10.5):
    """lines 为None 时只画标题。"""
    ax.add_patch(FancyBboxPatch((x, y), w, h,
                                boxstyle="round,pad=0.010,rounding_size=0.018",
                                fc=bg, ec=ln, lw=1.2, zorder=2))
    ax.text(x + w / 2, y + h - 0.038, title, ha="center", va="center", fontsize=fs_title,
            color=tx, weight="bold", zorder=3)
    if lines:
        top = y + h - TITLE_GAP - 0.014
        for i, s in enumerate(lines):
            if s:
                ax.text(x + w / 2, top - i * LINE_H, s, ha="center", va="center",
                        fontsize=fs_body, color=tx, zorder=3)


def arrow(ax, x1, y1, x2, y2):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=14, color="#888780", lw=1.4,
                                 zorder=1, shrinkA=0, shrinkB=0))


# ================= 图1：根因结构 =================
fig, ax = plt.subplots(figsize=(13.5, 10))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
ax.text(0.5, 0.982, "考研平台「错误率高」根因结构", ha="center", va="top",
        fontsize=18, weight="bold", color="#1F1F1F")

# 对照区
box(ax, 0.045, 0.800, 0.435, 0.115, "测试层：看起来很健康",
    ["后端 149 项通过 · 前端构建通过", "前端仅 3 个测试，覆盖几乎为零"],
    GREEN_BG, GREEN_LN, GREEN_TX)
box(ax, 0.520, 0.800, 0.435, 0.115, "运行时层：实际很脆弱",
    ["226 路由探测：75 成功 / 38 失败", "探测中途后端进程整体崩溃"],
    RED_BG, RED_LN, RED_TX)
arrow(ax, 0.482, 0.8575, 0.518, 0.8575)

ax.text(0.045, 0.762, "四条根因（均已实测复现）", ha="left", va="top",
        fontsize=14, weight="bold", color="#1F1F1F")

causes = [
    ("① storage/scan 阻塞事件循环",
     ["async 函数内同步全盘扫描", "76GB 目录树遍历 18 遍",
      "逐文件全文读取算 MD5", "→ 77.21s，占死整个事件循环"], RED_BG, RED_LN, RED_TX),
    ("② datetime 名称遮蔽",
     ["review.py:119 导入的是类", "datetime.UTC 取到类属性",
      "", "→ 必然 500 AttributeError"], RED_BG, RED_LN, RED_TX),
    ("③ naive / aware 混比",
     ["planner.py 时间列比较", "DB 列为 naive，代码用 aware",
      "", "→ 必然 500 TypeError"], RED_BG, RED_LN, RED_TX),
    ("④ 裸字符串未包 text()",
     ["exam.py:95 等 2 处", "SQLAlchemy 2.x 硬性要求",
      "", "→ 必然 500 ArgumentError"], AMB_BG, AMB_LN, AMB_TX),
]
CW, GAP, CTOP, CH = 0.218, 0.024, 0.520, 0.205
for i, (t, ls, bg, ln, tx) in enumerate(causes):
    x = 0.045 + i * (CW + GAP)
    box(ax, x, CTOP, CW, CH, t, ls, bg, ln, tx, fs_title=11.8, fs_body=10)
    arrow(ax, x + CW / 2, CTOP, x + CW / 2, CTOP - 0.032)

box(ax, 0.045, 0.352, 0.910, 0.104, "叠加效应：事件循环被长时间占死 + SQLite 写锁被抢",
    ["APScheduler 3 个后台 job + 后台队列 3 工作线程同时写库，进一步放大锁竞争"],
    GRY_BG, GRY_LN, GRY_TX)
arrow(ax, 0.5, 0.352, 0.5, 0.329)

box(ax, 0.045, 0.190, 0.910, 0.135, "用户看到的现象：接口超时 · 页面空白 · 整个服务突然消失",
    ["单元测试完全测不到这一层，所以 149 项全绿也无法预警任何运行时缺陷",
     "这是「错误率高」的真实根源，而不是某几个孤立的 bug"],
    RED_BG, "#A32D2D", RED_TX)

ax.text(0.045, 0.152, "三条被实测推翻的初始假设", ha="left", va="top",
        fontsize=13, weight="bold", color="#1F1F1F")
box(ax, 0.045, 0.022, 0.910, 0.115, None,
    ["① 连接池饥饿 → 实测 30 线程并发全部成功（最慢 94ms），池配置是健康的，真凶是堵源占死事件循环",
     "② datetime.UTC 是 Python 版本问题 → 实为 import 遮蔽，类属性取不到",
     "③ 裸字符串 execute 有 6 处 → 实为 DBAPI 代理，包裹text() 反而报错"],
    BLU_BG, BLU_LN, BLU_TX, fs_body=10.5)

fig.savefig(os.path.join(OUT, "01-根因结构.png"), dpi=150, bbox_inches="tight",
            facecolor="white")
plt.close(fig)
print("OK 01-根因结构.png")


# ================= 图2：修复前后对比 =================
fig, ax = plt.subplots(figsize=(13.5, 8.2))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
ax.text(0.5, 0.975, "修复前后对比：核心指标", ha="center", va="top",
        fontsize=18, weight="bold", color="#1F1F1F")

rows = [
    ("storage/scan 耗时", "77.21 s", "0.28 s", "271 倍"),
    ("扫描期间 /api/health", "60 000 ms 超时假死", "223 ms 正常", "根除"),
    ("目录树遍历次数", "18 遍 rglob", "1 遍 os.walk", "18 倍"),
    ("扫描文件内容读取", "全文 MD5（读 76 GB）", "仅 stat 取指纹", "根除"),
    ("GET 接口 5xx", "38 个失败", "0 个", "归零"),
    ("后端进程", "探测中途崩溃", "未复现", "修复"),
    ("前端测试数量", "3 个", "61 个", "+58"),
    ("后端测试数量", "149 个", "202 个", "+53"),
]

XR = [0.045, 0.300, 0.520, 0.745, 0.955]
ax.add_patch(FancyBboxPatch((0.045, 0.800), 0.910, 0.052,
                            boxstyle="round,pad=0.008,rounding_size=0.014",
                            fc=BLU_BG, ec=BLU_LN, lw=1.2, zorder=2))
for cx, t in zip(XR, ["指标", "修复前", "修复后", "改善"]):
    ax.text(cx, 0.826, t, ha="center", va="center", fontsize=12.5,
            weight="bold", color=BLU_TX, zorder=3)

y = 0.772
for i, (a, b, c, d) in enumerate(rows):
    ax.add_patch(FancyBboxPatch((0.045, y - 0.030), 0.910, 0.060,
                                boxstyle="square,pad=0",
                                fc="#FAFAF8" if i % 2 == 0 else "#FFFFFF",
                                ec="#D3D1C7", lw=0.6, zorder=1))
    ax.text(XR[0] + 0.008, y, a, ha="left", va="center", fontsize=11.5, color="#2C2C2A", zorder=3)
    ax.text(XR[1], y, b, ha="center", va="center", fontsize=11.5, color="#A32D2D", zorder=3)
    ax.text(XR[2], y, c, ha="center", va="center", fontsize=11.5, color="#0F6E56",
            weight="bold", zorder=3)
    ax.text(XR[3], y, d, ha="center", va="center", fontsize=11.5, color="#0F6E56",
            weight="bold", zorder=3)
    y -= 0.066

box(ax, 0.045, 0.052, 0.910, 0.145, "结论：不是代码质量差，而是一个 76GB 全盘扫描阻塞了事件循环",
    ["叠加测试基础设施损坏（starlette 0.27 + httpx 0.28 冲突，TestClient 无法使用）→ 缺陷长期无法被发现",
     "现已用 121 条 GET 路由契约巡检 + 硬断言「绝无5xx」钉住，回归会自动失败"],
    GREEN_BG, GREEN_LN, GREEN_TX)

fig.savefig(os.path.join(OUT, "02-修复前后对比.png"), dpi=150, bbox_inches="tight",
            facecolor="white")
plt.close(fig)
print("OK 02-修复前后对比.png")


# ================= 图3：检测能力对比 =================
fig, ax = plt.subplots(figsize=(13.5, 7.6))
ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
ax.text(0.5, 0.972, "检测能力对比：项目质量的真实变化", ha="center", va="top",
        fontsize=18, weight="bold", color="#1F1F1F")

box(ax, 0.045, 0.625, 0.435, 0.280, "修复前",
    ["后端：149 个纯函数单测", "前端：3 个 smoke 测试", "HTTP 层覆盖：0",
     "5xx：38 个失败", "超时：12 个", "崩溃：探测中途整体崩溃",
     "→ 149 全绿也测不出运行时缺陷"],
    RED_BG, RED_LN, RED_TX, fs_body=10.5)

box(ax, 0.520, 0.625, 0.435, 0.280, "修复后",
    ["后端：202 个（含 121 路由契约）", "前端：61 个（含 5 种异常场景）",
     "HTTP 层覆盖：121 条 GET 全量", "5xx：0 个（硬断言守住）", "超时：0",
     "崩溃：未复现", "→ 缺陷一出现就让 CI 失败"],
    GREEN_BG, GREEN_LN, GREEN_TX, fs_body=10.5)

arrow(ax, 0.482, 0.765, 0.518, 0.765)

box(ax, 0.045, 0.372, 0.910, 0.190, "新增的三道防线",
    ["1. conftest.py 强制测试库隔离 —— 从 import 起重定向到临时库，杜绝污染 283MB 真实数据",
     "2. api_health_check.py 一键体检 —— 有 5xx/超时则退出码非 0，可直接做门禁",
     "3. pages.smoke.test.jsx 把 React 渲染崩溃转成显式断言 —— 否则崩了测试也会假绿"],
    BLU_BG, BLU_LN, BLU_TX)

box(ax, 0.045, 0.055, 0.910, 0.272, "你现在可以自己体检",
    ["python backend-main-fastapi/scripts/diagnostics/api_health_check.py --base-url http://127.0.0.1:8000",
     "",
     "输出：总数 / 200 / 4xx / 5xx / 超时 / 平均耗时 / P95 / 最慢 10 个，支持 JSON 导出",
     "以后改完代码跑一次，就能确认有没有引入新的 5xx —— 不再依赖人肉记忆"],
    GRY_BG, GRY_LN, GRY_TX)

fig.savefig(os.path.join(OUT, "03-检测能力对比.png"), dpi=150, bbox_inches="tight",
            facecolor="white")
plt.close(fig)
print("OK 03-检测能力对比.png")