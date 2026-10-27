# -*- coding: utf-8 -*-
"""数据同步第 1 步：本地 pg_dump 导出六张表（data-only, -Fc）。
凭据从 backend-main-fastapi/.env 读取（PG_* 变量），不落明文。执行后可删。"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 读取本地 .env（与 pipeline.config 同源）
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

pg_bin = os.environ.get("PG_BIN_DIR", "")
pg_dump = str(Path(pg_bin) / "pg_dump") if pg_bin else "pg_dump"
out = ROOT.parent / "deploy" / "datasync_20261019.dump"

env = dict(os.environ)
# pg_dump 的密码通道：环境变量注入（值来自 .env，本脚本不落任何明文）
for k in ("PG_HOST", "PG_PORT", "PG_DATABASE", "PG_USER", "PG_PASSWORD"):
    assert os.environ.get(k), f"缺少 {k}（检查 .env）"
env["PGPASSWORD"] = os.environ["PG_PASSWORD"]

tables = [
    "kaoyan_schools", "kaoyan_majors", "quiz_questions",
    "documents", "knowledge_chunks", "chunk_vectors",
]
cmd = [
    pg_dump, "-h", os.environ["PG_HOST"], "-p", os.environ.get("PG_PORT", "5432"),
    "-U", os.environ["PG_USER"], "-d", os.environ["PG_DATABASE"],
    "--data-only", "--no-owner", "-Fc", "-f", str(out),
]
for t in tables:
    cmd += ["-t", t]

print("导出 →", out)
subprocess.run(cmd, env=env, check=True)
size = out.stat().st_size
print(f"完成：{size/1024/1024:.1f} MB")
