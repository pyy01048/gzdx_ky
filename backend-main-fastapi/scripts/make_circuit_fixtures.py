# -*- coding: utf-8 -*-
"""生成 3 张标准教科书电路图作为 VLM 实测 fixture。

输出到 tests/fixtures/circuits/：
  01_voltage_divider.png   - 电阻分压电路（Vcc-R1-节点-R2-GND）
  02_common_emitter.png    - 共射极放大电路（NPN + Rc/Re/C1/C2/Vin/Vout）
  03_bridge_rectifier.png  - 桥式整流（D1-D4 + 交流源 + C1 + Rload）
"""
from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "tests", "fixtures", "circuits")
OUT = os.path.abspath(OUT)
os.makedirs(OUT, exist_ok=True)

W, H = 900, 600
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def _font(size=18):
    for fp in [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"]:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def new_canvas():
    img = Image.new("RGB", (W, H), WHITE)
    return img, ImageDraw.Draw(img)


def line(d, p1, p2, w=2):
    d.line([p1, p2], fill=BLACK, width=w)


def resistor_h(d, x1, y, x2, label=None, label_dy=-14):
    """水平电阻：x1..x2，中间 zigzag，返回中心 x。"""
    body_w = min(80, (x2 - x1) * 0.5)
    mid = (x1 + x2) / 2
    line(d, (x1, y), (mid - body_w / 2, y))
    # zigzag: 6 peaks
    peaks = 6
    zx0 = mid - body_w / 2
    step = body_w / peaks
    amp = 10
    pts = [(zx0, y)]
    for i in range(peaks):
        px = zx0 + step * (i + 0.5)
        py = y - amp if i % 2 == 0 else y + amp
        pts.append((px, py))
    pts.append((mid + body_w / 2, y))
    d.line(pts, fill=BLACK, width=2)
    line(d, (mid + body_w / 2, y), (x2, y))
    if label:
        d.text((mid - 20, y + label_dy), label, fill=BLACK, font=_font(16))
    return mid


def resistor_v(d, x, y1, y2, label=None, label_dx=12):
    """垂直电阻：y1..y2，中间 zigzag。"""
    body_h = min(80, (y2 - y1) * 0.5)
    mid = (y1 + y2) / 2
    line(d, (x, y1), (x, mid - body_h / 2))
    peaks = 6
    zy0 = mid - body_h / 2
    step = body_h / peaks
    amp = 10
    pts = [(x, zy0)]
    for i in range(peaks):
        py = zy0 + step * (i + 0.5)
        px = x - amp if i % 2 == 0 else x + amp
        pts.append((px, py))
    pts.append((x, mid + body_h / 2))
    d.line(pts, fill=BLACK, width=2)
    line(d, (x, mid + body_h / 2), (x, y2))
    if label:
        d.text((x + label_dx, mid - 8), label, fill=BLACK, font=_font(16))
    return mid


def capacitor_v(d, x, y1, y2, label=None):
    """垂直电容：两条平行横线。"""
    mid = (y1 + y2) / 2
    line(d, (x, y1), (x, mid - 15))
    line(d, (x - 20, mid - 15), (x + 20, mid - 15), w=3)
    line(d, (x - 20, mid + 15), (x + 20, mid + 15), w=3)
    line(d, (x, mid + 15), (x, y2))
    if label:
        d.text((x + 25, mid - 8), label, fill=BLACK, font=_font(16))


def diode_h(d, x1, y, x2, label=None, direction="forward"):
    """水平二极管：x1 -> x2，三角+竖线。direction=forward 表示三角指向 x2。"""
    mid = (x1 + x2) / 2
    line(d, (x1, y), (mid - 15, y))
    # 三角
    if direction == "forward":
        tri = [(mid - 15, y - 12), (mid - 15, y + 12), (mid + 5, y)]
    else:
        tri = [(mid + 15, y - 12), (mid + 15, y + 12), (mid - 5, y)]
    d.polygon(tri, outline=BLACK, fill=WHITE)
    d.line(tri + [tri[0]], fill=BLACK, width=2)
    line(d, (mid + 15, y - 12), (mid + 15, y + 12), w=3)
    line(d, (mid + 15, y), (x2, y))
    if label:
        d.text((mid - 10, y - 30), label, fill=BLACK, font=_font(16))


def gnd(d, x, y):
    """接地符号。"""
    line(d, (x, y), (x, y + 10))
    line(d, (x - 18, y + 10), (x + 18, y + 10), w=3)
    line(d, (x - 12, y + 18), (x + 12, y + 18), w=3)
    line(d, (x - 6, y + 26), (x + 6, y + 26), w=3)


def vcc(d, x, y, label="Vcc (+12V)"):
    line(d, (x, y), (x, y - 20))
    d.text((x - 50, y - 40), label, fill=BLACK, font=_font(16))


# ---------------------------------------------------------------------------
# 01: 电阻分压电路
# ---------------------------------------------------------------------------
def draw_divider():
    img, d = new_canvas()
    cx = 450
    vcc(d, cx, 100)
    # R1 垂直 Vcc -> node
    resistor_v(d, cx, 120, 280, label="R1 = 10kΩ")
    # node dot
    d.ellipse([cx - 5, 340 - 5, cx + 5, 340 + 5], fill=BLACK)
    # 输出节点向右引出
    line(d, (cx, 340), (700, 340))
    d.text((710, 332), "Vout", fill=BLACK, font=_font(18))
    # R2 垂直 node -> GND
    resistor_v(d, cx, 340, 480, label="R2 = 20kΩ")
    gnd(d, cx, 500)
    img.save(os.path.join(OUT, "01_voltage_divider.png"))


# ---------------------------------------------------------------------------
# 02: 共射极放大电路
# ---------------------------------------------------------------------------
def draw_common_emitter():
    img, d = new_canvas()
    # Vcc 顶部总线
    vcc_x = 600
    vcc(d, vcc_x, 80, label="Vcc (+12V)")
    line(d, (vcc_x, 100), (vcc_x, 120))
    line(d, (200, 120), (vcc_x, 120))  # 顶部水平总线

    # Rc: Vcc -> collector
    resistor_v(d, 500, 120, 220, label="Rc=3kΩ")
    # collector node
    line(d, (500, 220), (500, 260))
    # C2: collector -> Vout
    capacitor_v(d, 500, 260, 310, label="C2=10µF")
    line(d, (500, 310), (750, 310))
    d.text((760, 302), "Vout", fill=BLACK, font=_font(18))

    # Q1 NPN: 位置 (350, 350)
    qx, qy = 350, 350
    d.ellipse([qx - 50, qy - 50, qx + 50, qy + 50], outline=BLACK, width=2)
    d.text((qx - 12, qy - 70), "Q1 (NPN)", fill=BLACK, font=_font(16))
    # Base: 从左进
    line(d, (qx - 50, qy), (qx - 10, qy))
    d.line([(qx - 10, qy - 25), (qx - 10, qy + 25)], fill=BLACK, width=3)
    # Collector: 斜向上
    d.line([(qx - 10, qy - 15), (qx + 20, qy - 35)], fill=BLACK, width=3)
    line(d, (qx + 20, qy - 35), (500, qy - 35))
    line(d, (500, qy - 35), (500, 220))  # 接到 Rc 下端
    # Emitter: 斜向下 + 箭头向外（NPN）
    d.line([(qx - 10, qy + 15), (qx + 20, qy + 35)], fill=BLACK, width=3)
    # NPN 箭头向外
    d.polygon([(qx + 18, qy + 30), (qx + 28, qy + 38), (qx + 15, qy + 40)], fill=BLACK)

    # Re: emitter -> GND
    line(d, (qx + 20, qy + 35), (qx + 20, qy + 60))
    resistor_v(d, qx + 20, qy + 60, qy + 130, label="Re=1kΩ")
    gnd(d, qx + 20, qy + 150)

    # C1: Vin -> base
    line(d, (100, qy), (200, qy))
    d.text((70, qy - 25), "Vin", fill=BLACK, font=_font(18))
    capacitor_v(d, 200, qy - 25, qy + 25, label="C1=1µF") if False else None
    # 水平电容
    line(d, (200, qy), (260, qy))
    line(d, (260, qy - 18), (260, qy + 18), w=3)
    line(d, (280, qy - 18), (280, qy + 18), w=3)
    d.text((255, qy - 45), "C1=1µF", fill=BLACK, font=_font(16))
    line(d, (280, qy), (qx - 50, qy))

    img.save(os.path.join(OUT, "02_common_emitter.png"))


# ---------------------------------------------------------------------------
# 03: 桥式整流
# ---------------------------------------------------------------------------
def draw_bridge():
    img, d = new_canvas()
    # 交流源左边
    ax, ay = 150, 300
    d.ellipse([ax - 30, ay - 30, ax + 30, ay + 30], outline=BLACK, width=2)
    d.arc([ax - 18, ay - 18, ax + 18, ay + 18], 0, 180, fill=BLACK, width=2)
    d.arc([ax - 18, ay - 18, ax + 18, ay + 18], 180, 360, fill=BLACK, width=2)
    d.text((ax - 30, ay + 40), "AC 220V", fill=BLACK, font=_font(16))
    # 交流源上端到桥左上
    line(d, (ax, ay - 30), (ax, 150))
    line(d, (ax, 150), (350, 150))
    # 交流源下端到桥左下
    line(d, (ax, ay + 30), (ax, 450))
    line(d, (ax, 450), (350, 450))

    # 桥四个顶点：左上(350,150) 右上(650,150) 左下(350,450) 右下(650,450)
    # D1: 左上 -> 右上（水平）
    diode_h(d, 380, 150, 620, label="D1")
    # D2: 右上 -> 右下（垂直，向下）
    # 用一个旋转的二极管：从 (650,180) 到 (650,420)
    d.line([(650, 180), (650, 240)], fill=BLACK, width=2)
    # 三角向下
    d.polygon([(638, 240), (662, 240), (650, 260)], outline=BLACK, fill=WHITE)
    d.line([(638, 240), (662, 240), (650, 260), (638, 240)], fill=BLACK, width=2)
    d.line([(638, 270), (662, 270)], fill=BLACK, width=3)
    d.line([(650, 270), (650, 420)], fill=BLACK, width=2)
    d.text((665, 245), "D2", fill=BLACK, font=_font(16))

    # D3: 左下 -> 右下（水平）方向从右下指左到左下（反向）
    diode_h(d, 380, 450, 620, label="D3", direction="backward")

    # D4: 左下 -> 左上（垂直，向上）
    d.line([(350, 420), (350, 360)], fill=BLACK, width=2)
    d.polygon([(338, 360), (362, 360), (350, 340)], outline=BLACK, fill=WHITE)
    d.line([(338, 360), (362, 360), (350, 340), (338, 360)], fill=BLACK, width=2)
    d.line([(338, 330), (362, 330)], fill=BLACK, width=3)
    d.line([(350, 330), (350, 180)], fill=BLACK, width=2)
    d.text((315, 345), "D4", fill=BLACK, font=_font(16))

    # 正输出节点：右上(650,150) 向右到 C1+ 和 Rload
    line(d, (650, 150), (800, 150))
    d.text((760, 130), "+Vout", fill=BLACK, font=_font(16))
    # C1: 正输出 -> GND
    line(d, (750, 150), (750, 250))
    line(d, (730, 250), (770, 250), w=3)
    line(d, (730, 275), (770, 275), w=3)
    d.text((775, 255), "C1=470µF", fill=BLACK, font=_font(16))
    line(d, (750, 275), (750, 500))
    gnd(d, 750, 500)
    # Rload: 正输出 -> 负输出（底部线）
    line(d, (800, 150), (800, 350))
    resistor_v(d, 800, 150, 350) if False else None
    # 用水平电阻画 Rload 在底部
    line(d, (650, 450), (800, 450))
    resistor_h(d, 680, 450, 780, label="Rload", label_dy=20)
    line(d, (800, 450), (800, 500))
    gnd(d, 800, 500)

    img.save(os.path.join(OUT, "03_bridge_rectifier.png"))


if __name__ == "__main__":
    draw_divider()
    draw_common_emitter()
    draw_bridge()
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print(f, os.path.getsize(p))
