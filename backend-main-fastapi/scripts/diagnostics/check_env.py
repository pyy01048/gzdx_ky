# -*- coding: utf-8 -*-
"""环境自检：一条命令看清"能不能跑起来"，缺什么直接说。

由 启动.bat 的「环境自检」调用，也可单独运行：
    python check_env.py
"""

import importlib
import os
import shutil
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

# 本脚本位于 backend/scripts/diagnostics/，后端根目录需向上两级。
# （历史 bug：曾直接用脚本自身目录当 BACKEND，导致 .env/数据库/static 全部找不到，
#   自检误报「数据库不存在/前端未构建/缺少 .env」，实际平台是好的。）
_HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, BACKEND)

# 数据库路径与 database.py 保持一致：优先 .env / 环境变量 DATABASE_PATH，
# 回退到 backend/data/kaoyan.db。
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND, ".env"))
except Exception:
    pass
_configured_db = os.environ.get("DATABASE_PATH", "").strip()
DB = _configured_db or os.path.join(BACKEND, "data", "kaoyan.db")

OK, WARN, FAIL = "[OK  ]", "[警告]", "[缺失]"
problems: list[str] = []
warnings: list[str] = []


def hdr(t: str) -> None:
    print("\n" + "-" * 66)
    print(f"  {t}")
    print("-" * 66)


# --------------------------------------------------------------------------- #
hdr("1. 运行环境")
print(f"  Python      {sys.version.split()[0]}  ({sys.executable})")
if sys.version_info < (3, 10):
    problems.append("Python 版本过低，需要 3.10+")
    print(f"  {FAIL} 需要 Python 3.10 或更高")
else:
    print(f"  {OK} 版本满足要求")

if os.path.exists(os.path.join(BACKEND, ".env")):
    print(f"  {OK} .env 配置文件存在")
else:
    warnings.append("缺少 .env，将使用默认配置（HOST=127.0.0.1）")
    print(f"  {WARN} 未找到 .env，使用默认值")

# --------------------------------------------------------------------------- #
hdr("2. 关键依赖")
REQUIRED = {
    "fastapi": "Web 框架",
    "uvicorn": "ASGI 服务器",
    "sqlalchemy": "ORM",
    "pydantic": "数据校验",
    "httpx": "HTTP 客户端",
}
OPTIONAL = {
    "jieba": "中文分词（缺了检索质量会明显下降）",
    "pypdfium2": "PDF 渲染（扫描件 OCR 需要）",
    "rapidocr_onnxruntime": "本地 OCR（扫描件识别）",
    "fastembed": "本地向量嵌入",
    "pypdf": "PDF 文本提取",
    "docx": "Word 解析",
    "pptx": "PPT 解析",
    "openpyxl": "Excel 解析",
    "psutil": "硬件探测",
}
for mod, desc in REQUIRED.items():
    try:
        importlib.import_module(mod)
        print(f"  {OK} {mod:<22} {desc}")
    except Exception:
        problems.append(f"缺少必需依赖 {mod}")
        print(f"  {FAIL} {mod:<22} {desc}")
for mod, desc in OPTIONAL.items():
    try:
        importlib.import_module(mod)
        print(f"  {OK} {mod:<22} {desc}")
    except Exception:
        warnings.append(f"可选依赖 {mod} 未安装（{desc}）")
        print(f"  {WARN} {mod:<22} {desc}")

# --------------------------------------------------------------------------- #
hdr("3. 数据库")
# 后端开关：postgresql | sqlite（与 core.db_session.database_backend() 同口径）。
# 2026-10-28 修复（P2-3）：此前只认 SQLite，在 DATABASE_BACKEND=postgresql 时
# 会误报「数据库不存在」。现在按后端分派：PG 走真实连接检查，sqlite 走文件检查。
BACKEND_TYPE = os.environ.get("DATABASE_BACKEND", "").strip().lower() or "postgresql"

if BACKEND_TYPE == "postgresql":
    try:
        from sqlalchemy import text
        from core.db_session import SessionLocal as PGSession, IS_POSTGRES

        if not IS_POSTGRES:
            problems.append("DATABASE_BACKEND=postgresql 但连接串不是 PostgreSQL，请检查 .env")
            print(f"  {FAIL} 配置为 PostgreSQL，但 SQLALCHEMY_DATABASE_URL 不是 postgresql://")
        else:
            db = PGSession()
            try:
                tables = db.execute(
                    text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
                ).scalar()
                docs = db.execute(text("SELECT count(*) FROM documents")).scalar()
                chunks = db.execute(text("SELECT count(*) FROM knowledge_chunks")).scalar()
                kps = db.execute(text("SELECT count(*) FROM knowledge_points")).scalar()
                quiz = db.execute(text("SELECT count(*) FROM quiz_questions")).scalar()
                empty = db.execute(text(
                    "SELECT count(*) FROM documents "
                    "WHERE content IS NULL OR length(trim(content))=0"
                )).scalar()
                print(f"  {OK} PostgreSQL 已连接（{tables} 张表）")
                print(f"       文档 {docs} · 分块 {chunks} · 知识点 {kps} · 真题 {quiz}")
                if empty:
                    warnings.append(f"{empty} 篇文档正文为空（可跑 kb_pipeline --heal）")
                    print(f"  {WARN} {empty} 篇文档正文为空")
            finally:
                db.close()
    except Exception as e:
        problems.append(f"PostgreSQL 连接失败: {e}")
        print(f"  {FAIL} PostgreSQL 连接失败: {e}")
else:
    if os.path.exists(DB):
        size = os.path.getsize(DB) / 1024 / 1024
        print(f"  {OK} 数据库存在  {size:.0f} MB")
        try:
            conn = sqlite3.connect(DB)
            tables = conn.execute(
                "select count(*) from sqlite_master where type='table'").fetchone()[0]
            docs = conn.execute("select count(*) from documents").fetchone()[0]
            chunks = conn.execute("select count(*) from knowledge_chunks").fetchone()[0]
            kps = conn.execute("select count(*) from knowledge_points").fetchone()[0]
            quiz = conn.execute("select count(*) from quiz_questions").fetchone()[0]
            print(f"       表 {tables} 个 · 文档 {docs} · 分块 {chunks} · 知识点 {kps} · 真题 {quiz}")
            empty = conn.execute(
                "select count(*) from documents where content is null or length(trim(content))=0"
            ).fetchone()[0]
            if empty:
                warnings.append(f"{empty} 篇文档正文为空（可跑 kb_pipeline --heal）")
                print(f"  {WARN} {empty} 篇文档正文为空")
            conn.close()
        except Exception as e:
            problems.append(f"数据库读取失败: {e}")
            print(f"  {FAIL} 读取失败: {e}")
    else:
        problems.append("数据库不存在，首次启动会自动创建（但知识库是空的）")
        print(f"  {WARN} 数据库不存在，首次启动会自动创建")

# --------------------------------------------------------------------------- #
hdr("4. 本地模型（Ollama）")
ollama = shutil.which("ollama") or next(
    (p for p in (
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"),
        os.path.expandvars(r"%ProgramFiles%\Ollama\ollama.exe"),
    ) if os.path.isfile(p)), None)
if ollama:
    print(f"  {OK} Ollama 已安装: {ollama}")
    try:
        import json
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            models = json.loads(r.read().decode()).get("models", [])
        if models:
            print(f"  {OK} 服务运行中，已装 {len(models)} 个模型:")
            for m in models:
                print(f"       · {m.get('name')}  {round((m.get('size') or 0)/1024**3, 1)} GB")
        else:
            warnings.append("Ollama 已装但没有任何模型，本地 AI 不可用")
            print(f"  {WARN} 服务运行中，但一个模型都没装")
            print("       安装推荐模型: python setup_local_models.py --pull")
    except Exception:
        warnings.append("Ollama 已装但服务未启动")
        print(f"  {WARN} 服务未启动（打开 Ollama 即可，或用云端 API 兜底）")
else:
    warnings.append("未安装 Ollama，本地模型不可用（会走云端 API）")
    print(f"  {WARN} 未安装 —— 本地 AI 不可用，将走云端 API")

# --------------------------------------------------------------------------- #
hdr("5. 前端构建产物")
static = os.path.join(BACKEND, "static")
index = os.path.join(static, "index.html")
if os.path.exists(index):
    n = sum(len(f) for _, _, f in os.walk(static))
    print(f"  {OK} 前端已构建（static/ 共 {n} 个文件）")
else:
    problems.append("前端未构建，页面打不开")
    print(f"  {FAIL} 未找到 static/index.html")
    print("       构建: cd frontend && npm install && npm run build")

# --------------------------------------------------------------------------- #
hdr("6. 端口占用")
PORT = int(os.getenv("PORT", "8000"))
try:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    in_use = s.connect_ex(("127.0.0.1", PORT)) == 0
    s.close()
    if in_use:
        print(f"  [提示] {PORT} 端口已被占用（服务可能已在运行）")
    else:
        print(f"  {OK} {PORT} 端口空闲")
except Exception as e:
    print(f"  {WARN} 端口检查失败: {e}")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 66)
if problems:
    print(f"  ❌ 发现 {len(problems)} 个阻断问题：")
    for p in problems:
        print(f"     · {p}")
else:
    print("  ✅ 没有阻断问题，可以启动")
if warnings:
    print(f"\n  ⚠️  {len(warnings)} 个提醒（不阻断，但会影响功能）：")
    for w in warnings:
        print(f"     · {w}")
print("=" * 66)
print("\n  启动方式: 双击 启动.bat，或运行 python main.py")
print()
