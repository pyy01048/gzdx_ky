# -*- coding: utf-8 -*-
"""kaoyan-kernel：证据驱动考研平台的确定性内核（S0 骨架）。

纯度规则（落地方案 §2.2）：
- 禁止 import models / database / fastapi / sqlalchemy / utils.scope；
- 输入输出只用 dataclass / dict / list；
- 时间一律 naive UTC datetime；
- 无 I/O（event_store 的 append 是唯一例外，且路径由调用方注入）；
- 依赖仅 fsrs（py-fsrs）、jsonschema、标准库。
"""

KERNEL_VERSION = "0.1.0-s0"

__all__ = ["KERNEL_VERSION"]
