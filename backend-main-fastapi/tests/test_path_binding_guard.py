"""去机器绑定守卫（P0-B1）。

实测背景：本仓库曾在运行时代码里写死本机路径与口令，换一台机器（或换一个数据
落位）就直接失效，而且失效方式各不相同——有的抛异常、有的静默当成"没有这个后端"。
典型三处：``exam_engine`` 的真题索引路径、``kb_ingest`` 的 KB 根目录、
``ocr_router`` 的 Marvis ``run.ps1``；另有 4 个管线脚本各写一份同一条带口令的 DSN。

本文件守两条：
  1. **扫描**：services/routers/core/pipeline 的源码里不允许出现本机绝对路径字面量
     （AST 常量级扫描，注释和 docstring 不算，避免"为了过检而删说明"）。
  2. **降级**：真题索引指不到时，检索这一路必须退化成空索引而不是抛异常——它藏在
     搜索链路里，让它崩等于让搜索 500。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIRS = ("services", "routers", "core", "pipeline")

#: 本机绝对路径字面量：盘符 + 只有这台机器才有的目录名
MACHINE_PATH_RE = re.compile(r"[A-Za-z]:[\\/](?:平台|Users|真题|pgsql|Program Files)")


def _string_constants(path: Path) -> list[tuple[int, str]]:
    """取**可执行**字符串常量（模块/类/函数 docstring 除外）。

    docstring 里常常是在叙述"这里曾写死过什么、现在改走哪个环境变量"，那是有用的
    历史说明而不是机器绑定；把它们算进来，只会逼人删掉说明来过检。
    """
    # utf-8-sig：仓库里有带 BOM 的脚本，直接 utf-8 读会让 ast 第一个字符就报错
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                doc_ids.add(id(first.value))
    return [(n.lineno, n.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids]


def test_runtime_code_has_no_machine_bound_paths():
    offenders: list[str] = []
    for d in RUNTIME_DIRS:
        for f in sorted((BACKEND_DIR / d).rglob("*.py")):
            for lineno, val in _string_constants(f):
                if MACHINE_PATH_RE.search(val):
                    offenders.append(f"{f.relative_to(BACKEND_DIR)}:{lineno}: {val[:60]}")
    assert not offenders, (
        "运行时代码里出现了本机绝对路径，换机器即失效。请改走环境变量解析"
        "（KAOYAN_EXAM_INDEX / KAOYAN_EXAM_DIR / KAOYAN_KB_ROOT / "
        "LOCAL_OCR_GPU_RUN_PS1 / DATABASE_URL / PG_*）：\n" + "\n".join(offenders)
    )


def test_pipeline_scripts_do_not_embed_credentials():
    """管线脚本的连接串一律经 pipeline.config.pg_database_url() 取，代码里不留口令。"""
    offenders = []
    for f in sorted((BACKEND_DIR / "pipeline").rglob("*.py")):
        for lineno, val in _string_constants(f):
            if "://" in val and "@" in val:  # user:pass@host 形态 = 内嵌凭据
                offenders.append(f"{f.name}:{lineno}")
        if "PG_DEFAULT" in f.read_text(encoding="utf-8"):
            offenders.append(f"{f.name}: 仍有 PG_DEFAULT 常量")
    assert not offenders, f"管线脚本内嵌了带口令的 DSN：{offenders}"


# --------------------------------------------------------------------------- #
# 真题索引：找不到必须降级，不能炸
# --------------------------------------------------------------------------- #
def test_index_resolver_honours_env_file(monkeypatch, tmp_path):
    from services import exam_engine

    p = tmp_path / "index.pkl"
    p.write_bytes(b"not-a-pickle")  # 只验解析，不验内容
    monkeypatch.setenv(exam_engine.INDEX_FILE_ENV, str(p))
    assert exam_engine.resolve_index_file() == p


def test_index_resolver_returns_none_when_missing(monkeypatch, tmp_path):
    from services import exam_engine

    monkeypatch.setenv(exam_engine.INDEX_FILE_ENV, str(tmp_path / "nope.pkl"))
    monkeypatch.setenv(exam_engine.INDEX_DIR_ENV, str(tmp_path / "empty-dir"))
    # 默认落位也可能在这台机器上真实存在，所以要把它一并挪开
    monkeypatch.setattr(exam_engine, "_DEFAULT_INDEX_DIR", tmp_path / "no-such-dir")
    assert exam_engine.resolve_index_file() is None


def test_exam_index_degrades_to_empty_without_file(monkeypatch, tmp_path):
    """解析不到索引 → loaded=False、total=0、retrieve 返回空列表且不抛异常。"""
    from services import exam_engine

    monkeypatch.setenv(exam_engine.INDEX_FILE_ENV, "")
    monkeypatch.setenv(exam_engine.INDEX_DIR_ENV, "")
    monkeypatch.setattr(exam_engine, "_DEFAULT_INDEX_DIR", tmp_path / "no-such-dir")

    idx = exam_engine.ExamIndex()
    assert idx.loaded is False
    assert idx.total == 0 and idx.n_docs == 0
    assert idx.retrieve("非线性失真", 3) == []


def test_kb_ingest_root_uses_single_authority(monkeypatch, tmp_path):
    """kb_ingest 不再自带 KB_ROOT 字面量，必须复用 kb_service.resolve_kb_root()。"""
    from services import kb_service

    monkeypatch.setenv("KAOYAN_KB_ROOT", str(tmp_path))
    # resolve_kb_root() 返回 str（KB 路径在全仓以 str 传递），比对前归一
    assert Path(kb_service.resolve_kb_root()) == tmp_path

    src = (BACKEND_DIR / "services" / "kb_ingest.py").read_text(encoding="utf-8")
    assert "resolve_kb_root" in src, "kb_ingest 的 KB 根必须来自 resolve_kb_root()"
    literals = {v for _l, v in _string_constants(BACKEND_DIR / "services" / "kb_ingest.py")}
    assert "KB_ROOT" not in literals, (
        "kb_ingest 不应再自带 KB_ROOT 环境变量——与 KAOYAN_KB_ROOT 同义不同名，"
        "两套名字必然只有一套生效"
    )
