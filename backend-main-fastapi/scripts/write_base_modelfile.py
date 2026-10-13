# -*- coding: utf-8 -*-
"""生成同基座对照的 Modelfile（sed 处理 Windows 反斜杠路径会炸，改用 Python）。"""
import io
import re

SRC = "data/lora_finetune_v3b/Modelfile"
DST = "temp/Modelfile.base3b"
BASE = r"C:\Users\33884\.cache\modelscope\hub\models\Qwen--Qwen2.5-3B-Instruct\snapshots\master"

src = io.open(SRC, encoding="utf-8").read()
out = re.sub(r"(?m)^FROM .*$", lambda m: "FROM " + BASE, src, count=1)
io.open(DST, "w", encoding="utf-8").write(out)
print("FROM 行:", [ln for ln in out.splitlines() if ln.startswith("FROM")])
