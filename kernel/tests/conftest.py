# -*- coding: utf-8 -*-
"""kernel 测试公共夹具：不依赖数据库/网络/原服务即可运行。"""
import sys
from pathlib import Path

import pytest

# 保证 `import kernel` 可用（tests 目录在包外一层运行时也能找到仓库根）
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kernel.config_loader import load_config  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def rules_cfg(cfg):
    return cfg.rules


@pytest.fixture(scope="session")
def drift_cfg(cfg):
    return cfg.rules.drift


@pytest.fixture(scope="session")
def compliance_cfg(cfg):
    return cfg.compliance


@pytest.fixture(scope="session")
def audit_cfg(cfg):
    return cfg.audit


@pytest.fixture(scope="session")
def fsrs_cfg(cfg):
    return cfg.fsrs
