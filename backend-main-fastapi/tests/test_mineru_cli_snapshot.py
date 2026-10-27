# -*- coding: utf-8 -*-
"""MinerU CLI 契约快照测试。

为什么要快照：解析层是**按命令行参数**调 MinerU 的，而 MinerU 的 CLI 在不同
版本间改过形态（2.x 是 ``mineru -p ... -o ...``，4.x 变成 ``mineru parse ...``，
更老的版本还有 ``--task doc``，2.7.6 已经没有了）。如果只是把参数写死在代码里，
MinerU 一升级就会**静默跑错参数**（要么 no such option，要么参数被忽略后产出
一堆空文件）。

所以这里把 CLI 的 help 原文存成固定文件：

    tests/fixtures/mineru_cli_help.txt

并断言两件事：

1. 解析层实际会拼出的每个 flag，都必须出现在这份契约里；
2. 如果本机能找到真的 mineru，可执行文件的 help 必须仍然包含这些关键 flag
   —— MinerU 升级后这条会立刻红，提醒人来更新快照和代码。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "mineru_cli_help.txt")

#: 解析层在 2.x 形态下依赖的关键 flag（2.7.6 实测存在）
KEY_FLAGS_2X = ("-p", "--path", "-o", "--output", "-s", "--start", "-e", "--end")


@pytest.fixture(scope="module")
def snapshot() -> str:
    assert os.path.isfile(FIXTURE), f"缺少 CLI 契约快照: {FIXTURE}"
    with open(FIXTURE, "r", encoding="utf-8") as fh:
        return fh.read()


def test_snapshot_contains_key_flags(snapshot):
    for flag in KEY_FLAGS_2X:
        assert flag in snapshot, f"CLI 契约快照里没有 {flag}（MinerU 改版了？）"


def test_snapshot_documents_provenance(snapshot):
    """快照必须写明来源与重抓方式，否则没人知道它什么时候过期了。"""
    assert "mineru --help" in snapshot
    assert "fixtures/mineru_cli_help.txt" in snapshot


def test_parser_command_only_uses_flags_in_snapshot(snapshot):
    """解析层拼出来的命令里，每个 flag 都必须真的存在于契约里。"""
    from services.parsers.mineru_parser import MinerUParser

    parser = MinerUParser()
    cmd = parser._cmd_2x("mineru", "a.pdf", "out_dir", page_numbers=[1, 3], help_text=snapshot)
    flags = [tok for tok in cmd[1:] if tok.startswith("-")]
    for flag in flags:
        assert flag in snapshot, f"命令用了契约里没有的 flag: {flag}"
    # 2.x 的页范围是 0 基
    assert "-s" in cmd and "0" in cmd
    assert "-e" in cmd and "2" in cmd


def test_legacy_task_flag_dropped_when_unsupported(snapshot):
    """老版本的 --task doc 在 2.7.6 里不存在 → 不能硬传（会 no such option）。"""
    from services.parsers.mineru_parser import MinerUParser

    parser = MinerUParser()
    cmd = parser._cmd_2x("mineru", "a.pdf", "out", help_text=snapshot)
    assert "--task" not in cmd


def test_legacy_task_flag_kept_when_supported():
    """help 里确实有 --task 时要保留（老版本仍按 --task doc 跑）。"""
    from services.parsers.mineru_parser import MinerUParser

    help_text = "Usage: mineru [OPTIONS]\n  -p, --path PATH\n  --task [doc|ocr]\n"
    parser = MinerUParser()
    cmd = parser._cmd_2x("mineru", "a.pdf", "out", help_text=help_text)
    assert "--task" in cmd and "doc" in cmd


def test_flag_filtering_rules():
    from services.parsers.mineru_parser import _flag_supported

    text = "  -p, --path PATH   input\n  -o, --output PATH  output\n"
    assert _flag_supported("-p", text) is True
    assert _flag_supported("--path", text) is True
    assert _flag_supported("--task", text) is False
    # 探测不到 help 时不做过滤（保持旧行为）
    assert _flag_supported("--task", "") is True


def test_live_cli_still_matches_snapshot(snapshot):
    """本机装了 mineru 的话，现场 help 必须仍然包含关键 flag（升级即红）。"""
    binary = shutil.which("mineru")
    if not binary:
        for env in ("MINERU_BIN", "KAOYAN_OCR_BIN"):
            candidate = (os.environ.get(env) or "").strip()
            if candidate and os.path.isfile(candidate):
                binary = candidate
                break
    if not binary:
        pytest.skip("本机没有可用的 mineru 可执行文件")

    try:
        proc = subprocess.run(
            [binary, "--help"], capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
    except Exception:  # noqa: BLE001
        pytest.skip("调用 mineru --help 失败")
    live = (proc.stdout or "") + (proc.stderr or "")
    for flag in KEY_FLAGS_2X:
        assert flag in live, (
            f"现场 mineru --help 里没有 {flag} —— CLI 改版了，请更新 "
            f"tests/fixtures/mineru_cli_help.txt 与 services/parsers/mineru_parser.py"
        )


def test_probe_detects_flavor(snapshot):
    """按 help 判定形态：2.x（有 --path）与 4.x（有 parse 子命令）。"""
    from services.parsers.mineru_parser import MinerUParser

    parser = MinerUParser()
    parser._probe_cache = None
    # 直接用内部判定逻辑验证，不真调 mineru
    from services.parsers.mineru_parser import _flavor_from_help

    assert _flavor_from_help(snapshot) == "2x"
    assert _flavor_from_help("  Commands:\n    parse  Parse a document file.\n") == "4x"
    assert _flavor_from_help("") == "unknown"
