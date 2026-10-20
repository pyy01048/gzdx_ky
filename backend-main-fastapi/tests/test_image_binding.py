# -*- coding: utf-8 -*-
"""配图三信号绑定单测（docx/34 §4.5 第 7 条）。

三种情形：
1. **只有图注命中**：题干写「图1-3」，图注文本也写「图1-3」→ 编号一致即绑定
   （不看距离，因为编号是显式引用）。
2. **只有「如图」+ 同页邻近**：题干只说「如图」→ 必须同页且垂直距离 < 200px 才绑。
3. **都不命中**：题干说「如图」但没有可绑的图 → figure_missing = 1（宁缺毋滥，
   绝不硬塞一张不相干的图）。

纯函数测试：不碰数据库、不需要 mineru、不需要真实 PDF。
"""
from __future__ import annotations

from services.ingest_pipeline import bind_question_images


def _q(stem, page=3, box=(50, 100, 500, 130)):
    return {
        "qno": 1,
        "stem": stem,
        "page": page,
        "blocks": [{"text": stem, "box": list(box), "score": 0.9}],
    }


def _fig(page=3, text="", bbox=(50, 200, 500, 400), block_id="f1", image_path="figs/f1.png"):
    return {
        "page_no": page,
        "block_id": block_id,
        "text": text,
        "image_path": image_path,
        "bbox": list(bbox),
    }


# --------------------------------------------------------------------------- #
# 情形 1：图注（编号）命中
# --------------------------------------------------------------------------- #
def test_caption_number_match_binds_far_figure():
    """题干「图1-3」+ 图注「图1-3」→ 绑定，哪怕图离得很远。"""
    result = bind_question_images(
        [_q("如图1-3所示的电路，下面说法正确的是（　）")],
        [_fig(text="图1-3 放大电路示意图", bbox=(50, 700, 500, 900))],
    )
    assert result["figures_bound"] == 1
    assert result["figure_missing"] == 0
    binding = result["bindings"][0]
    assert binding["block_id"] == "f1"
    assert "caption" in binding["signals"]
    assert binding["is_primary"] is True
    assert binding["bbox"] == [50.0, 700.0, 500.0, 900.0]
    assert binding["width"] == 450 and binding["height"] == 200


def test_caption_mismatch_does_not_bind():
    """题干说「图1-3」，图注是「图2-1」→ 不绑定。"""
    result = bind_question_images(
        [_q("如图1-3所示的电路，下面说法正确的是（　）")],
        [_fig(text="图2-1 另一种电路", bbox=(50, 200, 500, 400))],
    )
    assert result["figures_bound"] == 0
    assert result["figure_missing"] == 1


# --------------------------------------------------------------------------- #
# 情形 2：题干「如图」+ 同页邻近
# --------------------------------------------------------------------------- #
def test_stem_mention_with_nearby_figure_binds():
    """题干「如图所示」+ 同页相邻（垂直距离 < 200px）的 figure → 绑定。"""
    result = bind_question_images(
        [_q("如图所示的电路，其电压放大倍数约为（　）")],
        [_fig(text="", bbox=(50, 200, 500, 400))],
    )
    assert result["figures_bound"] == 1
    assert result["figure_missing"] == 0
    signals = result["bindings"][0]["signals"]
    assert "stem_mentions_figure" in signals
    assert "bbox_proximity" in signals


def test_stem_mention_with_far_figure_is_missing():
    """题干「如图所示」但图在 570px 之外 → 不绑定，figure_missing=1。"""
    result = bind_question_images(
        [_q("如图所示的电路，其电压放大倍数约为（　）")],
        [_fig(text="", bbox=(50, 700, 500, 900))],
    )
    assert result["figures_bound"] == 0
    assert result["figure_missing"] == 1
    assert result["missing"][0]["reason"] == "figure_referenced_but_not_bound"


def test_stem_mention_without_any_figure_is_missing():
    """完全没有 figure 块 → figure_missing=1。"""
    result = bind_question_images(
        [_q("如图所示的电路，其电压放大倍数约为（　）")],
        [],
    )
    assert result["figures_bound"] == 0
    assert result["figure_missing"] == 1


# --------------------------------------------------------------------------- #
# 情形 3：题干不指图 → 不绑、不算缺图
# --------------------------------------------------------------------------- #
def test_question_without_figure_reference_binds_nothing():
    """题干没说「如图」→ 即使旁边有图也不绑（避免把图塞给不相干的题）。"""
    result = bind_question_images(
        [_q("数字电路中与非门的输入端不能悬空。")],
        [_fig(text="图1-1 与非门", bbox=(50, 200, 500, 400))],
    )
    assert result["figures_bound"] == 0
    assert result["figure_missing"] == 0


def test_figure_on_other_page_is_not_bound():
    """不同页的图不绑（跨页题合并不在本函数职责内）。"""
    result = bind_question_images(
        [_q("如图所示的电路，其电压放大倍数约为（　）", page=3)],
        [_fig(page=4, text="", bbox=(50, 200, 500, 400))],
    )
    assert result["figures_bound"] == 0
    assert result["figure_missing"] == 1


def test_primary_is_largest_area():
    """同题多图 → 面积最大的那个是主图。"""
    result = bind_question_images(
        [_q("如图所示的电路及其等效电路（　）")],
        [
            _fig(text="", bbox=(50, 200, 200, 300), block_id="small"),
            _fig(text="", bbox=(50, 320, 500, 700), block_id="big"),
        ],
    )
    assert result["figures_bound"] == 2
    primary = [b for b in result["bindings"] if b["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["block_id"] == "big"
