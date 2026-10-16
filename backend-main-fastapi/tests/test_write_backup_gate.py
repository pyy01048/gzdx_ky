"""写前备份闸门（P0-A2）：备份做不成，就不许写真库。

实测背景：V3.0 的备份层只支持 SQLite，而本项目 2026-10-14 已切 PostgreSQL，
于是 ``create_backup()`` 每次必然抛 ``FileNotFoundError``；旧实现把它 print 成
一行告警后 ``return None``，路由照常 commit —— 批量导入在**零备份、零回滚点**
状态下跑了整整一轮。这个缺陷本身不报错，所以躲过了全部既有测试。

本文件守住两件事：
  1. 备份失败必须升级成闸门异常，并在写点转成明确 HTTP 错误码（503）；
  2. 闸门不许再被"顺手 try/except 吞掉"退化回去 —— 因此断言的是**拒绝执行**
     （归档/写库函数一次都没被调用），而不只是断言返回值。

只用 conftest 的隔离测试库（红线：绝不碰生产库）。
"""
from __future__ import annotations

import pytest

PROD_URL = "postgresql+psycopg://u:p@127.0.0.1:5432/kaoyan"
SANDBOX_URL = "postgresql+psycopg://u:p@127.0.0.1:5432/kaoyan_test"


def _fail_backup(monkeypatch, msg: str = "模拟：pg_dump 不可用"):
    """把备份改成必失败，并伪装成"当前连的是真库"（否则测试沙箱会合法跳过）。"""
    from services import backup_service

    def boom(*_a, **_kw):
        raise RuntimeError(msg)

    monkeypatch.setattr(backup_service, "create_backup", boom)
    monkeypatch.setattr(backup_service, "is_test_database", lambda: False)


# --------------------------------------------------------------------------- #
# 1. 服务层：失败必须抛出，而不是 print 后放行
# --------------------------------------------------------------------------- #
def test_backup_failure_becomes_gate_error(monkeypatch):
    from services import kb_service

    _fail_backup(monkeypatch)
    with pytest.raises(kb_service.WriteBackupBlocked) as ei:
        kb_service.ensure_write_backup()
    assert "模拟：pg_dump 不可用" in str(ei.value), "闸门消息必须带上失败原因，否则用户无从修起"


def test_sandbox_database_skips_backup(monkeypatch):
    """测试沙箱跳过备份是**设计**，不是漏网：不得产生真实 dump，也不得触发清理。"""
    from services import backup_service, kb_service

    def forbidden(*_a, **_kw):
        raise AssertionError("测试沙箱不该做真实备份")

    monkeypatch.setattr(backup_service, "create_backup", forbidden)
    monkeypatch.setattr(backup_service, "is_test_database", lambda: True)
    assert kb_service.ensure_write_backup() is None


def test_is_test_database_recognition(monkeypatch, tmp_path):
    from services import backup_service as bs

    monkeypatch.setattr(bs, "IS_POSTGRES", True)
    monkeypatch.setattr(bs, "SQLALCHEMY_DATABASE_URL", SANDBOX_URL)
    assert bs.is_test_database() is True
    monkeypatch.setattr(bs, "SQLALCHEMY_DATABASE_URL", PROD_URL)
    assert bs.is_test_database() is False, "生产库被判成沙箱 = 写点全部失去备份保护"

    monkeypatch.setattr(bs, "IS_POSTGRES", False)
    in_temp = tmp_path / "qa_test.db"
    in_temp.write_bytes(b"x")
    monkeypatch.setattr(bs, "DB_PATH", str(in_temp))
    assert bs.is_test_database() is True
    monkeypatch.setattr(bs, "DB_PATH", "kaoyan.db")  # 工作目录下的真库位置，非临时目录
    assert bs.is_test_database() is False


# --------------------------------------------------------------------------- #
# 2. 路由层：闸门转成明确错误码
# --------------------------------------------------------------------------- #
def test_scan_root_refuses_and_never_archives(client, monkeypatch):
    """验收红线：人为让备份失败时，``scan-root`` 必须拒绝执行且不落一行盘。"""
    from services import kb_service

    calls: list = []
    monkeypatch.setattr(
        kb_service, "scan_root_and_archive",
        lambda db, **kw: calls.append(kw) or {"moved": 0},
    )
    _fail_backup(monkeypatch)

    r = client.post("/api/documents/scan-root", json={"dry_run": False})

    assert r.status_code == 503, r.text
    body = r.json()
    # 全局异常处理器把 HTTPException 统一成 {code, message}，所以这里读 message；
    # code 必须是 SERVICE_UNAVAILABLE 而不是 UNKNOWN_ERROR —— 前端要能区分
    # "服务故意挡下"和"服务坏了"，否则只能弹一句无意义的未知错误。
    assert body.get("code") == "SERVICE_UNAVAILABLE", r.text
    assert "写前备份失败" in str(body.get("message")), r.text
    assert "模拟：pg_dump 不可用" in str(body.get("message")), "拒绝原因必须回给用户，否则无从修起"
    assert calls == [], "备份没做成却执行了归档 —— 正是本次要根治的静默裸写"


def test_bulk_purge_refuses_without_backup(client, monkeypatch):
    """``purge`` 是不可逆物理删除：闸门必须排在它前面。"""
    from database import SessionLocal
    from models import Document

    monkeypatch.setenv("KAOYAN_ALLOW_PHYSICAL_DELETE", "1")
    db = SessionLocal()
    try:
        d = Document(file_name="GATE-purge.txt", file_path="GATE-purge.txt",
                     file_type="txt", size=10, subject="数学", doc_type="raw",
                     index_status="pending")
        db.add(d)
        db.commit()
        doc_id = d.id
    finally:
        db.close()

    _fail_backup(monkeypatch)
    r = client.post("/api/documents/bulk",
                    json={"action": "purge", "doc_ids": [doc_id]})
    assert r.status_code == 503, r.text

    db = SessionLocal()
    try:
        assert db.query(Document).filter(Document.id == doc_id).first() is not None, \
            "被拦截却已经把文档删了"
        db.query(Document).filter(Document.id == doc_id).delete()
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 3. 结构守卫：防退化
# --------------------------------------------------------------------------- #
def test_gate_is_registered_and_wired_at_every_write_site(client, app_module):
    """防退化两件事：闸门异常有人接、写点数量没缩水。

    - **有人接**：``WriteBackupBlocked`` 必须注册进全局异常处理器。没注册时它会掉进
      兜底 ``Exception`` 处理器 → 500 UNKNOWN_ERROR，写入照样被中止，但用户和前端
      看不出"是自己没配 PG_BIN_DIR"，排查成本极高。
    - **数量没缩水**：documents.py 的 6 处写点（archive / bulk×3 / scan-root /
      repair-file-paths）逐个用 AST 数，避免以后加写接口时漏掉闸门。
    """
    import ast
    import inspect

    from services.kb_service import WriteBackupBlocked

    handlers = app_module.exception_handlers
    assert WriteBackupBlocked in handlers, "503 闸门异常没人接 → 会退化成 500 UNKNOWN_ERROR"

    import routers.documents as docs

    gated = 0
    for fn in ast.walk(ast.parse(inspect.getsource(docs))):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "ensure_write_backup":
                gated += 1
    assert gated >= 6, f"备份闸门覆盖的写点数降到 {gated}（原 6 处：archive/bulk×3/scan-root/repair）"

    # 批量入库路径同样要有回滚点：网盘全量入库、知识库候选题确认入库
    for mod_name, endpoint in (("routers.netdisk", "ingest_all_netdisk"),
                               ("routers.kb_import", "confirm")):
        mod = __import__(mod_name, fromlist=["*"])
        fn = getattr(mod, endpoint)
        body = inspect.getsource(fn)
        assert "ensure_write_backup()" in body, f"{endpoint} 丢了写前备份闸门"
