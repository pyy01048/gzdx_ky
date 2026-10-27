# -*- coding: utf-8 -*-
"""Ollama 客户端地址归一化单测（P0-1 回归护栏）。

背景：本机用户级 `OLLAMA_HOST=0.0.0.0:11434`（服务端监听语义），裸读的模块
拿到缺 scheme 的地址后，httpx 直接抛
`Request URL is missing an 'http://' or 'https://' protocol`，
表现为 `/api/ai/local/status` 恒为 `available:false, models:[]`。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.ollama_host import DEFAULT_OLLAMA_HOST, resolve_ollama_host  # noqa: E402


def test_missing_scheme_gets_http_prefix() -> None:
    assert resolve_ollama_host("127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_wildcard_listener_rewritten_to_loopback() -> None:
    """`0.0.0.0` 是监听地址，Windows 上连不上，必须换 127.0.0.1。"""
    assert resolve_ollama_host("0.0.0.0:11434") == "http://127.0.0.1:11434"
    assert resolve_ollama_host("http://0.0.0.0:11434") == "http://127.0.0.1:11434"


def test_ipv6_wildcard_rewritten_to_loopback() -> None:
    assert resolve_ollama_host("[::]:11434") == "http://127.0.0.1:11434"
    assert resolve_ollama_host("http://[::]:11434") == "http://127.0.0.1:11434"


def test_already_valid_url_passes_through() -> None:
    assert resolve_ollama_host("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert resolve_ollama_host("https://ollama.example.com:11434") == (
        "https://ollama.example.com:11434"
    )


def test_trailing_slash_and_whitespace_stripped() -> None:
    assert resolve_ollama_host("  http://127.0.0.1:11434/  ") == (
        "http://127.0.0.1:11434"
    )


def test_empty_returns_default() -> None:
    assert resolve_ollama_host("") == DEFAULT_OLLAMA_HOST
    assert resolve_ollama_host(None) == DEFAULT_OLLAMA_HOST


def test_reads_env_var(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    assert resolve_ollama_host() == "http://127.0.0.1:11434"
    monkeypatch.delenv("OLLAMA_HOST")
    assert resolve_ollama_host() == DEFAULT_OLLAMA_HOST


def test_explicit_arg_wins_over_env(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    assert resolve_ollama_host("http://10.0.0.5:11434") == "http://10.0.0.5:11434"


def test_custom_port_preserved() -> None:
    assert resolve_ollama_host("0.0.0.0:11500") == "http://127.0.0.1:11500"


def test_path_preserved_for_proxied_deploy() -> None:
    assert resolve_ollama_host("http://0.0.0.0:11434/ollama") == (
        "http://127.0.0.1:11434/ollama"
    )


def test_credentials_preserved_when_rewriting_host() -> None:
    assert resolve_ollama_host("http://user:pass@0.0.0.0:11434") == (
        "http://user:pass@127.0.0.1:11434"
    )
