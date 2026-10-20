"""``services/formula_latex.py`` 的测试。

分三层：

1. **纯函数层**（必跑）：LaTeX 可信度校验、alpha 合成、裁边、张量形状。
2. **真实模型层**（有模型才跑）：对本机真实 Word 公式图做识别，断言质量门禁与
   至少一条「明显正确」的识别结果。
3. **失败路径**：文件不存在、引擎不可用、坏图，都必须是**显式失败**，不能静默返回空串。

第 2 层依赖 ``~/.mineru/models/.../PP-FormulaNet_plus-M.onnx``，
没有模型时自动 skip —— 不让没装模型的机器红。
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from services.formula_latex import (
    INPUT_SIZE,
    FormulaRecognizer,
    FormulaResult,
    FormulaResult as _FR,
    _crop_margin,
    _default_model_dir,
    _flatten_alpha,
    _img_decode,
    _normalize,
    latex_is_plausible,
)


# --------------------------------------------------------------------------- #
# 1. 纯函数层
# --------------------------------------------------------------------------- #
class TestLatexPlausible:
    @pytest.mark.parametrize(
        "latex",
        [
            r"f(x) = \lim_{t \to 0} \left( 1 + \frac{\sin t}{x} \right)^{\frac{x^2}{t}}",
            r"(-\infty, +\infty)",
            r"y = x^{2} + \sin \frac{1}{x}",
            r"\frac{a}{b}",
            r"x",
            r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
            r"\int_{0}^{1} x^{2} \mathrm{d}x",
            r"\sqrt[3]{x+1}",
        ],
    )
    def test_accepts_normal_latex(self, latex):
        ok, why = latex_is_plausible(latex)
        assert ok is True, f"正常公式被误判：{latex!r} -> {why}"

    @pytest.mark.parametrize(
        "latex,reason",
        [
            ("", "too_short"),
            ("   ", "too_short"),
            # 模型把汉字当符号吐出来
            (r"A. \quad 则 \lim x", "contains_cjk"),
            (r"若 \lim_{n} x_n = a", "contains_cjk"),
            # 括号不配对
            (r"\frac{1}{2", "unbalanced_brace"),
            (r"f(x", "unbalanced_paren"),
            # 不存在的命令
            (r"\notacommand{x}", "unknown_command"),
        ],
    )
    def test_rejects_bad_latex(self, latex, reason):
        ok, why = latex_is_plausible(latex)
        assert ok is False
        assert why.startswith(reason.split(":")[0]), f"期望 {reason}，实际 {why}"

    def test_unknown_command_reports_names(self):
        ok, why = latex_is_plausible(r"\foo \bar{x}")
        assert ok is False
        assert "unknown_command" in why
        # 报出具体命令名，方便排查
        assert "foo" in why

    def test_does_not_check_square_brackets(self):
        """方括号在 LaTeX 里是可选参数，不该参与配对检查（否则误报太多）。"""
        ok, _ = latex_is_plausible(r"\sqrt[3]{x}")
        assert ok is True


class TestFlattenAlpha:
    def test_transparent_gif_becomes_white_not_black(self):
        """回归：透明底 GIF 直接 convert("RGB") 会变黑底黑字。

        这是实测踩到的坑——144×47 的完整公式被识别成 ``\\cdot``。
        """
        img = Image.new("RGBA", (50, 20), (0, 0, 0, 0))  # 全透明
        draw = ImageDraw.Draw(img)
        draw.ellipse((5, 5, 15, 15), fill=(0, 0, 0, 255))  # 一块黑墨迹

        out = _flatten_alpha(img)
        assert out.mode == "RGB"
        arr = np.asarray(out)
        # 背景（透明处）必须是白，不是黑
        assert arr[0, 0].min() > 200, f"透明区域没变白: {arr[0, 0]}"
        # 墨迹必须仍是黑
        assert arr[10, 10].max() < 60, f"墨迹颜色异常: {arr[10, 10]}"

    def test_palette_gif_with_transparency(self):
        img = Image.new("P", (30, 30), 0)
        img.putpalette([0, 0, 0] + [255, 255, 255] * 255)
        img.info["transparency"] = 0
        out = _flatten_alpha(img)
        assert out.mode == "RGB"
        assert np.asarray(out)[0, 0].min() > 200

    def test_plain_rgb_passthrough(self):
        img = Image.new("RGB", (10, 10), (128, 128, 128))
        out = _flatten_alpha(img)
        assert out.mode == "RGB"
        assert tuple(np.asarray(out)[0, 0]) == (128, 128, 128)


class TestCropMargin:
    def test_crops_white_border(self):
        img = Image.new("RGB", (200, 100), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle((60, 30, 140, 70), fill=(0, 0, 0))
        out = _crop_margin(img)
        # 裁完应贴近墨迹外框（含 1px 余量），远小于原图
        assert out.width < 100
        assert out.height < 60
        assert out.width > 70  # 但不能把内容裁掉

    def test_solid_image_returned_unchanged(self):
        """纯色图没有墨迹，原样返回（不能因为找不到点集就崩）。"""
        img = Image.new("RGB", (40, 40), (255, 255, 255))
        out = _crop_margin(img)
        assert out.size == (40, 40)


class TestImgDecodeAndNormalize:
    def test_decode_shape_is_384(self):
        img = Image.new("RGB", (144, 47), (255, 255, 255))
        ImageDraw.Draw(img).rectangle((20, 15, 120, 35), fill=(0, 0, 0))
        arr = _img_decode(img)
        assert arr is not None
        assert arr.shape == (INPUT_SIZE, INPUT_SIZE, 3)
        assert arr.dtype == np.uint8

    def test_decode_tall_and_wide_both_fit(self):
        for size in [(40, 300), (300, 40), (384, 384), (10, 10)]:
            img = Image.new("RGB", size, (255, 255, 255))
            ImageDraw.Draw(img).rectangle(
                (size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4),
                fill=(0, 0, 0),
            )
            arr = _img_decode(img)
            assert arr is not None, f"{size} 解码失败"
            assert arr.shape == (INPUT_SIZE, INPUT_SIZE, 3), f"{size} 形状不对"

    def test_normalize_shape_and_range(self):
        arr = np.full((INPUT_SIZE, INPUT_SIZE, 3), 255, dtype=np.uint8)
        out = _normalize(arr)
        assert out.shape == (1, 1, INPUT_SIZE, INPUT_SIZE)
        assert out.dtype == np.float32
        # 白底归一化后应为正且有限
        assert np.isfinite(out).all()
        assert out.max() > 0

    def test_normalize_black_is_negative(self):
        """墨迹（黑）归一化后必须是负值——这是模型区分前景/背景的依据。"""
        arr = np.zeros((INPUT_SIZE, INPUT_SIZE, 3), dtype=np.uint8)
        out = _normalize(arr)
        assert out.min() < 0


# --------------------------------------------------------------------------- #
# 2. 失败路径
# --------------------------------------------------------------------------- #
class TestFailurePaths:
    def test_missing_file(self):
        rec = FormulaRecognizer()
        r = rec.recognize("D:/definitely/not/here.png")
        assert r.ok is False
        assert r.reason == "file_not_found"

    def test_engine_unavailable_reports_reason(self, tmp_path):
        """模型目录不存在时必须显式报错，不能静默返回空 LaTeX。"""
        rec = FormulaRecognizer(model_dir=str(tmp_path / "no_model"))
        # 造一张图，确保能走到引擎加载
        p = tmp_path / "x.png"
        Image.new("RGB", (50, 20), (255, 255, 255)).save(p)
        r = rec.recognize(str(p))
        assert r.ok is False
        assert r.reason.startswith("engine_unavailable")
        assert rec.load_error  # 错误原因要留档

    def test_result_to_dict(self):
        r = FormulaResult(ok=True, latex="x", image_path="/a.png", engine="e")
        d = r.to_dict()
        assert d["ok"] is True
        assert d["latex"] == "x"
        assert isinstance(d["elapsed"], float)


# --------------------------------------------------------------------------- #
# 3. 真实模型层（无模型自动 skip）
# --------------------------------------------------------------------------- #
_MODEL_DIR = _default_model_dir()
_HAS_MODEL = os.path.exists(os.path.join(_MODEL_DIR, "PP-FormulaNet_plus-M.onnx"))
requires_model = pytest.mark.skipif(not _HAS_MODEL, reason=f"未找到公式模型: {_MODEL_DIR}")


def _make_formula_png(path, text="y = x + 1"):
    """用 PIL 画一张干净的黑字白底公式图（不依赖真实 docx）。"""
    img = Image.new("RGB", (160, 48), (255, 255, 255))
    ImageDraw.Draw(img).text((6, 14), text, fill=(0, 0, 0))
    img.save(path)
    return str(path)


@requires_model
class TestRealModel:
    @pytest.fixture(scope="class")
    def rec(self):
        r = FormulaRecognizer()
        if not r.available:
            pytest.skip(f"模型加载失败: {r.load_error}")
        return r

    def test_engine_info_ready(self, rec):
        info = rec.engine_info()
        assert info["ready"] is True
        assert info["engine"] == "pp-formulanet-onnx"
        assert info["providers"]

    def test_recognizes_simple_formula(self, rec, tmp_path):
        p = _make_formula_png(tmp_path / "f.png", "y=x+1")
        r = rec.recognize(p)
        # 不强制完全匹配（字形渲染与训练分布不同），但必须 ok 且非平凡
        assert r.ok is True, f"识别失败: {r.reason}"
        assert len(r.latex) >= 2
        assert "x" in r.latex

    def test_transparent_gif_regression(self, rec, tmp_path):
        """回归测试：透明底图必须能识别出内容（不能只剩 ``\\cdot``）。"""
        img = Image.new("RGBA", (160, 48), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((6, 14), "y=x+1", fill=(0, 0, 0, 255))
        p = tmp_path / "t.gif"
        img.save(p)
        r = rec.recognize(str(p))
        assert r.ok is True, f"透明底识别失败: {r.reason} / {r.latex!r}"
        # 关键断言：不能是退化输出
        assert r.latex.strip() not in (r"\cdot", r"\_", ""), f"退化成 {r.latex!r}"

    def test_qc_rejects_cjk_output(self, rec, tmp_path):
        """含中文的整块图（如 A/B/C/D 四选项）应被门禁拦下，而不是当好公式入库。"""
        img = Image.new("RGB", (400, 120), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((6, 6), "A.", fill=(0, 0, 0))
        d.text((40, 6), "\u82e5 lim x = a", fill=(0, 0, 0))
        p = tmp_path / "cjk.png"
        img.save(p)
        r = rec.recognize(str(p))
        # 要么识别不出内容（ok=False），要么 ok=True 但 latex 里不含 CJK
        if r.ok:
            assert not any("\u4e00" <= ch <= "\u9fff" for ch in r.latex)
        else:
            assert r.reason  # 必须给出原因


# --------------------------------------------------------------------------- #
# 4. 契约：结果对象字段齐全
# --------------------------------------------------------------------------- #
def test_formula_result_defaults():
    r = _FR(ok=False)
    assert r.latex == ""
    assert r.engine == ""
    assert r.confidence is None
    assert r.extra == {}
    assert r.to_dict()["elapsed"] == 0.0
