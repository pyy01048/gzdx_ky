from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


INGEST = _load("ingest_source_folder")
P = _load("ingest_pdfs")


def test_normalize_empty_pdf_does_not_create_fake_toc():
    assert P.normalize_pdf_lines([]) == []
    assert P.normalize_pdf_lines(["", "第 3 页", "正文"]) == ["目录", "正文"]


def test_cache_key_separates_extraction_mode_and_page_range(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"pdf")
    full = P.cache_key_for(str(pdf), "scanned", None)
    assert full == P.cache_key_for(str(pdf), "scanned", None)
    assert full != P.cache_key_for(str(pdf), "digital", None)
    assert full != P.cache_key_for(str(pdf), "scanned", 5)


def test_extract_pdf_lines_reports_cache_hit_and_does_not_mix_page_ranges(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"pdf")
    monkeypatch.setattr(P, "CACHE_DIR", str(tmp_path / "cache"))
    calls = []

    def fake_parse(path, prefer, max_pages):
        calls.append(max_pages)
        return SimpleNamespace(pages=[SimpleNamespace(blocks=[SimpleNamespace(text=f"page-{max_pages}")])])

    monkeypatch.setattr(P, "route_parse", fake_parse)
    first, cached = P.extract_pdf_lines(str(pdf), "scanned", max_pages=5)
    second, cached_again = P.extract_pdf_lines(str(pdf), "scanned", max_pages=5)
    third, _ = P.extract_pdf_lines(str(pdf), "scanned", max_pages=None)

    assert first == ["page-5"]
    assert second == first
    assert third == ["page-None"]
    assert cached is False
    assert cached_again is True
    assert calls == [5, None]


def test_cache_index_resolves_only_matching_record(tmp_path, monkeypatch):
    index_path = tmp_path / "cache_index.json"
    monkeypatch.setattr(P, "CACHE_INDEX", str(index_path))
    P.remember_cache(
        rel="学科/自动控制/题目册.pdf",
        cache_key="abc",
        cache_file="abc.txt",
        kind="scanned",
        max_pages=None,
        chars=123,
    )
    assert P.find_cache_entry("学科\\自动控制\\题目册.pdf", "scanned", None) == {
        "rel": "学科/自动控制/题目册.pdf",
        "cache_key": "abc",
        "cache_file": "abc.txt",
        "kind": "scanned",
        "max_pages": None,
        "chars": 123,
    }
    assert P.find_cache_entry("学科/自动控制/题目册.pdf", "scanned", 5) is None


def test_option_key_must_be_one_letter():
    opts = [
        {"key": "A", "text": "甲"},
        {"key": "AB", "text": "乙"},
        {"key": "B", "text": "丙"},
    ]
    assert INGEST._sanitize_options(opts) == [
        {"key": "A", "text": "甲"},
        {"key": "B", "text": "丙"},
    ]


def test_exercise_parser_pairs_question_and_answer_by_number():
    question_lines = [
        "广告",
        "习题1-1",
        "(2005北航933)",
        "求如图所示f(t)的象函数F(s)",
        "f(t) t",
        "控制考研咨询VX：123",
        "习题1-2",
        "系统的开环增益为（ ）。",
        "(a) 5",
        "(b) 10",
        "(c) 20",
        "(d) 50",
    ]
    answer_lines = [
        "习题1-1",
        "解：由题意可得F(s)=1/s。",
        "习题1-2",
        "答案选(b)",
        "解：时间常数标准化后可得。",
    ]
    questions = P.parse_exercise_questions(question_lines, answer_lines)

    assert [q["no"] for q in questions] == ["1-1", "1-2"]
    assert questions[0]["answer"] == "见解析"
    assert "F(s)=1/s" in questions[0]["analysis"]
    assert "VX" not in questions[0]["stem"]
    assert questions[1]["qtype"] == "single"
    assert questions[1]["answer"] == "B"
    assert [o["key"] for o in questions[1]["options"]] == ["A", "B", "C", "D"]


def test_exercise_parser_accepts_ocr_mangled_numbers_and_multiple_answers():
    questions = P.parse_exercise_questions(
        ["习题15", "某道选择题的题干内容", "(a) 甲", "(b) 乙", "(c) 丙", "(d) 丁"],
        ["习题1-5", "答案选A、C", "解析：根据题意。"],
    )
    assert len(questions) == 1
    assert questions[0]["no"] == "1-5"
    assert questions[0]["qtype"] == "multiple"
    assert questions[0]["answer"] == "AC"


def test_exercise_quality_gate_rejects_cross_question_ocr_and_watermarks():
    questions = P.parse_exercise_questions(
        [
            "习题1-1",
            "（2005北航933）求如图所示f(t)象函数F(s)",
            "控制考研咨询VX：123",
            "165 真橙控制 专注自动化考研 bilibili",
            "（2003重庆大学844）",
            "习题1-2",
            "求下列函数f(t)的拉氏变换",
        ],
        ["习题1-1", "解：第一题。", "习题1-2", "解：第二题。"],
    )

    assert "bilibili" not in questions[0]["stem"]
    assert "cross_question_source" in P.exercise_question_issues(questions[0])
    assert "figure_missing" in P.exercise_question_issues(questions[0])
    importable, rejected = P.select_importable_exercise_questions(questions, "digital")
    assert [q["no"] for q in importable] == ["1-2"]
    assert rejected == 1


def test_scanned_exercise_candidates_are_not_auto_imported():
    questions = P.parse_exercise_questions(
        ["习题1-1", "已知某系统开环增益为正，求闭环增益"],
        ["习题1-1", "解：利用反馈关系。"],
    )

    assert questions
    assert P.select_importable_exercise_questions(questions, "scanned") == ([], 1)


def test_exercise_quality_gate_rejects_damaged_math_and_unordered_options():
    damaged = {"stem": "设函数f（一）=f()，判断奇偶性", "options": None}
    unordered = {
        "stem": "下列关于闭环控制系统特点的描述中，正确的选项有哪些",
        "options": [
            {"key": "A", "text": "甲"},
            {"key": "B", "text": "乙"},
            {"key": "D", "text": "丁"},
        ],
    }

    assert "math_ocr_unverified" in P.exercise_question_issues(damaged)
    assert "options_incomplete_reading" in P.exercise_question_issues(unordered)


def test_near_duplicate_is_not_automatically_merged(monkeypatch):
    class NearIndex:
        def lookup(self, _hash):
            return None

        def lookup_near(self, _norm):
            return (7, "另一道不同的题")

        def add(self, *_args, **_kwargs):
            pass

    class Result:
        def scalar(self):
            return 99

    monkeypatch.setattr(INGEST, "_exec", lambda *_args, **_kwargs: Result())
    question = {
        "stem": "已知某系统的开环传递函数为G(s)，求闭环传递函数",
        "options": None,
        "answer": "见解析",
        "analysis": "使用结构图等效变换。",
        "qtype": "calc",
        "atype": "subjective",
        "chapter": None,
    }
    assert INGEST.write_question(object(), question, NearIndex(), "自动控制原理", 32, "题目册", "习题") == "inserted"


@pytest.mark.parametrize("qtype", ["single", "multiple"])
def test_objective_question_without_valid_options_is_rejected(qtype):
    question = {
        "stem": "本题要求从给定选项中选出唯一正确的一项，并说明判断依据",
        "options": [{"key": "AB", "text": "非法选项"}],
        "answer": "A",
        "analysis": None,
        "qtype": qtype,
        "atype": "objective",
        "chapter": None,
    }
    assert INGEST.write_question(object(), question, object(), None, None, "题目册", "习题") == "invalid_options"


def test_probe_manifest_includes_fingerprint(tmp_path):
    probe = _load("probe_pdfs")
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"pdf")
    fp = probe.file_fingerprint(str(pdf))
    assert fp == probe.file_fingerprint(str(pdf))
    payload = {"files": [{"rel": "a.pdf", "fp": fp, "size_bytes": 3}]}
    assert json.loads(json.dumps(payload))["files"][0]["fp"] == fp
    assert os.path.getsize(pdf) == 3
