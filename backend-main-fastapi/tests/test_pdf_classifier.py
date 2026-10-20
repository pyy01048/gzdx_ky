"""PDF 分类单测：digital / scanned / hybrid 三个分支 + 阈值边界。

不需要真实 PDF：把字符数统计和页数读取都 monkeypatch 掉，
只验证判定规则本身（doc §4.1）。
"""
from __future__ import annotations

import pytest

from services.parsers import pdf_classifier
from services.parsers.pdf_classifier import (
    DIGITAL_MIN_CHARS,
    SCANNED_MAX_CHARS,
    classify_pdf,
    needs_ocr_pages,
    page_char_counts,
    sample_page_numbers,
)


@pytest.fixture()
def fake_pdf(tmp_path, monkeypatch):
    """装好假的页数/字符数统计；返回 (pdf 路径, 设置函数)。

    :param counts: ``{1 基页码: 字符数}``
    :param total: 总页数
    :param raise_on: 设为 True 时让字符统计抛异常（模拟加密/损坏 PDF）
    """
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"%PDF-1.7\n")

    def _install(counts: dict, total: int = 10, raise_on: bool = False) -> str:
        monkeypatch.setattr(pdf_classifier, "_total_pages", lambda _path: total)

        def _fake_counts(_path, *, pages=None):
            if raise_on:
                raise RuntimeError("PDF 已加密")
            if pages is None:
                return dict(counts)
            return {p: counts.get(p, 0) for p in pages}

        monkeypatch.setattr(pdf_classifier, "page_char_counts", _fake_counts)
        return str(pdf_path)

    return _install


# --------------------------------------------------------------------------- #
# 抽样页
# --------------------------------------------------------------------------- #
def test_sample_pages_takes_first_middle_last():
    assert sample_page_numbers(1) == [1]
    assert sample_page_numbers(2) == [1, 2]
    picked = sample_page_numbers(10)
    assert picked[0] == 1 and picked[-1] == 10
    assert len(picked) == 3


# --------------------------------------------------------------------------- #
# 三个分支
# --------------------------------------------------------------------------- #
def test_digital_when_avg_chars_high(fake_pdf):
    pdf = fake_pdf({1: 200, 2: 180, 3: 220}, total=3)
    profile = classify_pdf(pdf)
    assert profile.kind == "digital"
    assert profile.avg_chars_per_page == pytest.approx(200.0)
    assert profile.error == ""


def test_scanned_when_avg_chars_low(fake_pdf):
    pdf = fake_pdf({1: 5, 2: 0, 3: 10}, total=3)
    profile = classify_pdf(pdf)
    assert profile.kind == "scanned"
    assert profile.avg_chars_per_page == pytest.approx(5.0)


def test_hybrid_when_avg_between_thresholds(fake_pdf):
    pdf = fake_pdf({1: 60, 2: 40, 3: 50}, total=3)
    profile = classify_pdf(pdf)
    assert profile.kind == "hybrid"
    assert profile.error == ""


# --------------------------------------------------------------------------- #
# 边界值：100 → digital，99 → hybrid；30 → hybrid，29 → scanned
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "chars,expect_kind",
    [
        (DIGITAL_MIN_CHARS, "digital"),      # 正好 100 → digital
        (DIGITAL_MIN_CHARS - 1, "hybrid"),  # 99 → hybrid
        (SCANNED_MAX_CHARS, "hybrid"),      # 正好 30 → hybrid
        (SCANNED_MAX_CHARS - 1, "scanned"),  # 29 → scanned
    ],
)
def test_threshold_boundaries(fake_pdf, chars, expect_kind):
    pdf = fake_pdf({1: chars, 2: chars, 3: chars}, total=3)
    assert classify_pdf(pdf).kind == expect_kind


# --------------------------------------------------------------------------- #
# hybrid 要全量统计：拿全量结果决定哪几页要 OCR
# --------------------------------------------------------------------------- #
def test_hybrid_rescans_all_pages_and_marks_ocr_pages(fake_pdf):
    # 抽样页是首页/中间页/末页（第 1/3/5 页），平均 50 字/页 → hybrid
    pages = {1: 50, 2: 12, 3: 50, 4: 8, 5: 50}
    pdf = fake_pdf(pages, total=5)
    profile = classify_pdf(pdf)
    assert profile.kind == "hybrid"
    assert profile.sampled_pages == [1, 3, 5]
    # 全量页都在 profile 里（hybrid 必须全量统计才能定位缺字页）
    assert set(profile.page_char_counts) == set(pages)
    assert needs_ocr_pages(profile) == [2, 4]


def test_needs_ocr_pages_only_below_threshold():
    profile = pdf_classifier.PdfProfile(
        kind="hybrid",
        avg_chars_per_page=50.0,
        sampled_pages=[1, 2, 3],
        page_char_counts={1: 100, 2: 29, 3: 30, 4: 0, 5: 31},
        total_pages=5,
    )
    # 严格小于 30 才算需要 OCR（30 整不算）
    assert needs_ocr_pages(profile) == [2, 4]
    assert needs_ocr_pages(profile, threshold=30) == [2, 4]
    assert needs_ocr_pages(profile, threshold=100) == [2, 3, 4, 5]


# --------------------------------------------------------------------------- #
# 容错：加密 / 损坏 / 文件不存在 → 降级成 scanned，且不裸崩
# --------------------------------------------------------------------------- #
def test_encrypted_pdf_degrades_to_scanned(fake_pdf):
    pdf = fake_pdf({}, total=5, raise_on=True)
    profile = classify_pdf(pdf)
    assert profile.kind == "scanned"
    assert "已加密" in profile.error


def test_missing_file_degrades_to_scanned():
    profile = classify_pdf("no-such-file.pdf")
    assert profile.kind == "scanned"
    assert profile.error


# --------------------------------------------------------------------------- #
# 真实 PDF 的字符统计（有 PyMuPDF 才跑）
# --------------------------------------------------------------------------- #
def test_page_char_counts_on_real_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "two.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "hello world", fontsize=12)
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    counts = page_char_counts(str(pdf))
    assert set(counts) == {1, 2}
    assert counts[1] > 0
    assert counts[2] == 0
