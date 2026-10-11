# -*- coding: utf-8 -*-
"""V11 模块5：services/circuit_analysis 的回归测试。

覆盖：
  - 优先引擎 CircuitVisionService 的成功映射 / 回退主路径；
  - OCR（Paddle→RapidOCR 回退）、文本 LLM、VLM 兜底各环节失败时的降级路径；
  - 全部失败时：有题面 → degraded（题面兜底）；无图无题面 → failed；绝不抛异常；
  - 成功路径：mock OCR + mock 文本 LLM 走通；
  - 真实路径：PIL 自绘一张简单电路图，真实跑一遍本地 RapidOCR（Paddle 8888
    预期不可达，会快速失败回退），LLM 层 mock 掉避免单元测试等几分钟。
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# 无论从哪个工作目录运行都能 import 后端包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import circuit_analysis as ca  # noqa: E402

QUESTION = "求该放大电路的静态工作点与电压放大倍数。"

STRUCTURED_DESC = (
    "【元器件清单】R1=10kΩ，C1=100µF，Q1=9013 NPN，VCC=+5V。\n"
    "【连接关系】信号经 R1 基极输入，Q1 集电极输出，发射极接地。\n"
    "【电路类型】共射极放大电路。\n"
    "【与题面结合】按题面求静态工作点：IBQ≈VCC/Rb 起算。"
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def fake_image_path(tmp_path):
    """造一个真实存在的假图片文件：绕过主流程的图片存在性门禁，OCR/LLM 仍全 mock。"""
    p = tmp_path / "fake.png"
    p.write_bytes(b"\x89PNG\r\n fake circuit")
    return str(p)


# --------------------------------------------------------------------------- #
# 纯函数：标签提取 / 电路类型解析 / 优先引擎结果映射
# --------------------------------------------------------------------------- #
def test_extract_labels_unit():
    text = "R1=10k  C1  VCC +5V  GND  100uF  输入  输出  random junk"
    labels = ca._extract_labels(text)
    assert "R1" in labels
    assert "C1" in labels
    assert "VCC" in labels
    assert "GND" in labels
    assert "random" not in labels
    # 去重（大小写不敏感）
    assert ca._extract_labels("R1 r1 R2") == ["R1", "R2"]


def test_parse_circuit_type():
    assert ca._parse_circuit_type(STRUCTURED_DESC) == "共射极放大电路"
    assert ca._parse_circuit_type("没有小节的描述") is None


def test_map_circuit_vision():
    cv = {
        "ok": True,
        "circuit_type": "amplifier",
        "circuit_type_cn": "共射极放大电路",
        "components": [
            {"designator": "R1", "type": "resistor", "value": "10k", "net_nodes": ["Vcc", "Base"]},
            {"designator": "unknown", "type": "unknown", "value": "unknown", "net_nodes": ["unknown"]},
        ],
        "nodes": ["Vcc", "GND", "unknown"],
        "ocr_labels": ["R1", "C1"],
        "description": "单管共射放大电路。",
        "question_hints": "结合题面求静态工作点。",
        "engines": {"vlm": "ok", "ocr": "unavailable"},
    }
    mapped = ca._map_circuit_vision(cv, QUESTION)
    assert mapped["status"] == "ok"
    assert mapped["circuit_type"] == "共射极放大电路"
    # unknown 必须被过滤；components 位号 + nodes + ocr_labels 合并去重
    assert "R1" in mapped["labels"]
    assert "GND" in mapped["labels"]
    assert "C1" in mapped["labels"]
    assert "unknown" not in mapped["labels"]
    assert mapped["labels"].count("R1") == 1
    assert "单管共射放大电路" in mapped["description"]
    assert mapped["degraded_reason"] is None
    assert mapped["question_text"] == QUESTION
    assert mapped["engine"].startswith("circuit_vision(")


# --------------------------------------------------------------------------- #
# 优先引擎 CircuitVisionService：成功直接返回 / 失败回退主路径
# --------------------------------------------------------------------------- #
def test_priority_circuit_vision_short_circuits(monkeypatch):
    """优先引擎返回 ok 映射时，主路径（OCR/LLM）一次都不该被调用。"""
    mapped = {
        "status": "ok", "engine": "circuit_vision(qwen2.5vl:7b)",
        "labels": ["R1", "C1"], "description": "已有描述", "circuit_type": "共射放大",
        "degraded_reason": None, "question_text": QUESTION,
    }
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=mapped))

    result = run(ca.analyze_circuit_image("nonexistent.png", QUESTION))
    assert result is mapped
    assert result["status"] == "ok"


def test_fallback_when_priority_unavailable(monkeypatch, fake_image_path):
    """优先引擎不可用（返回 None）→ 落到自有 Paddle/RapidOCR + qwen3 主路径。"""
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    # Paddle 挂掉（8888 实测不可达），RapidOCR 给出标签
    monkeypatch.setattr(ca, "_ocr_paddle", AsyncMock(side_effect=RuntimeError("connect refused")))
    monkeypatch.setattr(ca, "_ocr_local", MagicMock(return_value="R1=10k C1 VCC GND"))
    monkeypatch.setattr(ca, "_text_describe", AsyncMock(return_value=STRUCTURED_DESC))

    result = run(ca.analyze_circuit_image(fake_image_path, QUESTION))

    assert result["status"] == "degraded"          # Paddle 失败 → 如实降级
    assert "PaddleOCR" in result["degraded_reason"]
    assert "R1" in result["labels"] and "GND" in result["labels"]
    assert result["circuit_type"] == "共射极放大电路"
    assert "ocr:paddleocr" not in result["engine"]
    assert "ocr:rapidocr" in result["engine"]
    assert "llm:qwen3:8b" in result["engine"]


# --------------------------------------------------------------------------- #
# 降级路径：任一环节失败
# --------------------------------------------------------------------------- #
def test_ocr_all_fail_but_text_llm_ok(monkeypatch, fake_image_path):
    """OCR 全挂、图片标签为空时，文本 LLM 仍能基于题面输出 → degraded。"""
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    monkeypatch.setattr(ca, "_ocr_paddle", AsyncMock(side_effect=RuntimeError("paddle down")))
    monkeypatch.setattr(ca, "_ocr_local", MagicMock(return_value=""))
    monkeypatch.setattr(ca, "_text_describe", AsyncMock(return_value=STRUCTURED_DESC))
    monkeypatch.setattr(ca, "_vlm_describe", AsyncMock(return_value="VLM兜底描述"))

    result = run(ca.analyze_circuit_image(fake_image_path, QUESTION))

    # 标签过少（0 个）→ 按设计跳过文本 LLM，先 VLM
    assert result["engine"].endswith("llm:qwen2.5vl:7b")
    assert result["status"] == "degraded"
    assert "PaddleOCR" in result["degraded_reason"] or "RapidOCR" in result["degraded_reason"]


def test_all_fail_degraded_with_question(monkeypatch):
    """OCR + 文本 LLM + VLM 全部失败，但题面文字在 → degraded + 题面兜底，不抛异常。"""
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    monkeypatch.setattr(ca, "_ocr_paddle", AsyncMock(side_effect=RuntimeError("paddle down")))
    monkeypatch.setattr(ca, "_ocr_local", MagicMock(side_effect=RuntimeError("rapidocr down")))
    monkeypatch.setattr(ca, "_text_describe", AsyncMock(side_effect=RuntimeError("ollama down")))
    monkeypatch.setattr(ca, "_vlm_describe", AsyncMock(side_effect=RuntimeError("vlm down")))

    result = run(ca.analyze_circuit_image("fake.png", QUESTION))

    assert result["status"] == "degraded"
    assert result["degraded_reason"], "必须如实记录失败环节"
    # 题面兜底描述里必须能看到题面文字
    assert QUESTION in result["description"]
    # 冻结键齐全
    for k in ("status", "engine", "labels", "description",
              "circuit_type", "degraded_reason", "question_text"):
        assert k in result
    assert result["question_text"] == QUESTION


def test_all_fail_failed_when_nothing_else(monkeypatch):
    """图不存在 + 无题面 + 所有引擎挂 → failed，description 为空，不抛异常。"""
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    monkeypatch.setattr(ca, "_text_describe", AsyncMock(side_effect=RuntimeError("x")))
    monkeypatch.setattr(ca, "_vlm_describe", AsyncMock(side_effect=RuntimeError("x")))

    result = run(ca.analyze_circuit_image("no_such_file.png", ""))

    assert result["status"] == "failed"
    assert result["description"] == ""
    assert result["degraded_reason"]


# --------------------------------------------------------------------------- #
# VLM 兜底逻辑：标签过少跳过文本 LLM；VLM 失败再回退文本 LLM
# --------------------------------------------------------------------------- #
def test_few_labels_trigger_vlm_not_text_llm(monkeypatch, fake_image_path):
    """只识别到 1 个标签（< MIN_LABELS）→ 不调用文本 LLM，直接 VLM 读图。"""
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    monkeypatch.setattr(ca, "_ocr_paddle", AsyncMock(side_effect=RuntimeError("paddle down")))
    monkeypatch.setattr(ca, "_ocr_local", MagicMock(return_value="R1"))
    text_llm = AsyncMock(return_value=STRUCTURED_DESC)
    vlm = AsyncMock(return_value="【电路类型】反相比例运算放大电路。VLM读图描述。")
    monkeypatch.setattr(ca, "_text_describe", text_llm)
    monkeypatch.setattr(ca, "_vlm_describe", vlm)

    result = run(ca.analyze_circuit_image(fake_image_path, QUESTION))

    text_llm.assert_not_awaited()  # 标签过少，文本 LLM 不该被调用
    vlm.assert_awaited_once()
    assert result["status"] == "degraded"          # OCR 标签过少本身即降级
    assert result["circuit_type"] == "反相比例运算放大电路"
    assert "llm:qwen2.5vl:7b" in result["engine"]


def test_vlm_failure_then_text_llm_retry(monkeypatch, fake_image_path):
    """标签过少 → VLM 失败 → 再用题面+少量标签试文本 LLM，成功则给出描述。"""
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    monkeypatch.setattr(ca, "_ocr_paddle", AsyncMock(side_effect=RuntimeError("paddle down")))
    monkeypatch.setattr(ca, "_ocr_local", MagicMock(return_value="R1"))
    monkeypatch.setattr(ca, "_vlm_describe", AsyncMock(side_effect=RuntimeError("vlm down")))
    monkeypatch.setattr(ca, "_text_describe", AsyncMock(return_value=STRUCTURED_DESC))

    result = run(ca.analyze_circuit_image(fake_image_path, QUESTION))

    assert result["status"] == "degraded"
    assert "VLM" in result["degraded_reason"]
    assert result["circuit_type"] == "共射极放大电路"
    assert "llm:qwen3:8b" in result["engine"]


# --------------------------------------------------------------------------- #
# 成功路径：mock OCR + mock 文本 LLM（labels 充足）
# --------------------------------------------------------------------------- #
def test_own_success_path_ok(monkeypatch, fake_image_path):
    """优先引擎不可用，但 Paddle OCR 出标签 + 文本 LLM 结构化描述成功 → status=ok。"""
    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    monkeypatch.setattr(ca, "_ocr_paddle", AsyncMock(return_value="R1=10k C1=100uF VCC GND"))
    monkeypatch.setattr(ca, "_text_describe", AsyncMock(return_value=STRUCTURED_DESC))
    monkeypatch.setattr(ca, "_vlm_describe", AsyncMock(return_value="不该用到"))

    result = run(ca.analyze_circuit_image(fake_image_path, QUESTION))

    assert result["status"] == "ok"
    assert result["degraded_reason"] is None
    # 位号/网络名必须提取到；数值参数（100uF）作为图内文字一并收录属预期
    for want in ("R1", "C1", "VCC", "GND"):
        assert want in result["labels"]
    assert result["circuit_type"] == "共射极放大电路"
    assert "ocr:paddleocr" in result["engine"]
    assert "llm:qwen3:8b" in result["engine"]


# --------------------------------------------------------------------------- #
# 真实路径：PIL 自绘电路图 → 真实 RapidOCR（Paddle 8888 预期拒连）
# --------------------------------------------------------------------------- #
def _draw_dummy_circuit(path: str) -> None:
    """画一张极简电路图：电源/地 + 电阻电容方框 + 文字标签。"""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()

    # 导线
    draw.line([(60, 60), (580, 60)], fill="black", width=3)      # 电源母线
    draw.line([(60, 360), (580, 360)], fill="black", width=3)    # 地母线
    draw.line([(160, 60), (160, 120)], fill="black", width=3)
    draw.line([(160, 220), (160, 360)], fill="black", width=3)

    # 电阻方框 + 电容
    draw.rectangle([(130, 120), (190, 220)], outline="black", width=3)
    draw.ellipse([(330, 150), (380, 210)], outline="black", width=3)
    draw.line([(380, 180), (430, 180)], fill="black", width=3)

    # 文字标签（RapidOCR 对印刷体识别率较好）
    draw.text((280, 30), "VCC +5V", fill="black", font=font)
    draw.text((280, 380), "GND", fill="black", font=font)
    draw.text((90, 160), "R1 10k", fill="black", font=font)
    draw.text((320, 120), "C1", fill="black", font=font)
    draw.text((60, 200), "Vin", fill="black", font=font)
    img.save(path)


def test_real_image_ocr_smoke(tmp_path, monkeypatch):
    """自绘电路图真实跑通 OCR 层（Paddle 预期拒连 → RapidOCR 回退），LLM mock。"""
    img_path = str(tmp_path / "dummy_circuit.png")
    _draw_dummy_circuit(img_path)

    monkeypatch.setattr(ca, "_circuit_vision_priority", AsyncMock(return_value=None))
    monkeypatch.setattr(ca, "_text_describe", AsyncMock(return_value=STRUCTURED_DESC))
    monkeypatch.setattr(ca, "_vlm_describe", AsyncMock(return_value="VLM描述"))

    result = run(ca.analyze_circuit_image(img_path, QUESTION))

    # 无论 RapidOCR 识别出多少，都必须返回合法冻结结构且不抛异常
    assert set(result.keys()) == {
        "status", "engine", "labels", "description",
        "circuit_type", "degraded_reason", "question_text",
    }
    assert result["status"] in ("ok", "degraded")
    assert result["description"]  # 题面/标签兜底也一定有内容
    # 如实打印本次真实 OCR 识别到的标签（自检报告用）
    print(f"\n[smoke] engine={result['engine']} labels={result['labels']} "
          f"status={result['status']} reason={result['degraded_reason']}")
