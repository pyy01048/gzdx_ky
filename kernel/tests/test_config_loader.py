# -*- coding: utf-8 -*-
"""config_loader：冻结 dataclass、缺省回退、显式错误（不静默吞配置问题）。"""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from kernel.config_loader import (
    ConfigError,
    KernelConfig,
    load_compliance_config,
    load_config,
    load_fsrs_config,
    load_rules_config,
    parse_simple_yaml,
)


class TestYamlParser:
    def test_scalars_and_lists(self):
        doc = parse_simple_yaml("a: 1\nb: 0.5\nc: true\nd: hello\ne: [x, y, z]\nf: []\n")
        assert doc["a"] == 1 and doc["b"] == 0.5
        assert doc["c"] is True
        assert doc["d"] == "hello"
        assert doc["e"] == ["x", "y", "z"]
        assert doc["f"] == []

    def test_comments_and_blank_lines(self):
        doc = parse_simple_yaml("# c\n\nk: v  # trailing\n")
        assert doc == {"k": "v"}


class TestLoaders:
    def test_load_all_four(self):
        rules = load_rules_config()
        comp = load_compliance_config()
        audit_cfg = __import__("kernel.config_loader", fromlist=["load_audit_config"]).load_audit_config()
        fsrs_cfg = load_fsrs_config()
        assert rules.drift.on_track_band == 0.15 and rules.drift.recovery_band == 0.35
        assert rules.drift.min_days == 3
        assert "gets" in comp.banned_functions
        assert audit_cfg.tuimian_cum_pp == 10
        assert fsrs_cfg.desired_retention == 0.9

    def test_frozen_dataclasses(self):
        cfg = load_config()
        assert isinstance(cfg, KernelConfig)
        with pytest.raises(FrozenInstanceError):
            cfg.rules.drift.on_track_band = 0.99  # type: ignore[misc]
        with pytest.raises((FrozenInstanceError, AttributeError)):
            cfg.fsrs.desired_retention = 0.5  # type: ignore[misc]

    def test_tuple_fields_immutable(self):
        cfg = load_config()
        assert isinstance(cfg.rules.priority_order, tuple)
        assert cfg.rules.priority_order[0] == "R2"
        assert isinstance(cfg.compliance.banned_functions, tuple)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            load_rules_config(base=tmp_path / "nowhere")

    def test_bad_value_raises(self, tmp_path):
        d = tmp_path / "config"
        d.mkdir()
        (d / "rules.yaml").write_text("drift:\n  window_days: not_a_number\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_rules_config(base=tmp_path)

    def test_shipped_configs_under_kernel_dir(self):
        base = Path(__file__).resolve().parents[1]
        for name in ("rules.yaml", "compliance.yaml", "audit.yaml", "fsrs.yaml"):
            assert (base / "config" / name).exists()
