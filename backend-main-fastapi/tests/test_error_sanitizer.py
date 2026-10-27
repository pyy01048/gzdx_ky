"""错误响应脱敏回归：确保数据库底层异常（含 SQL/表名/列名/traceback）绝不回前端。

历史问题：大量路由写 ``raise HTTPException(status_code=..., detail=str(e))``，
而 ``e`` 是 SQLAlchemy/psycopg 的底层异常，含完整 SQL 与库结构。全局处理器
原先原样透传 ``detail``，等于把数据库 schema 免费送给任何能调接口的人。

本文件守住两件事：
1. ``sanitize_error_detail`` 纯函数对内部错误脱敏、对业务友好文案放行；
2. 真实注册的 ``http_exception_handler`` 把含 SQL 的 detail 拦下换成中性文案
   （直接调用已注册的处理器，绕过路由，避免被 SPA fallback 吞掉）。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from utils.exceptions import sanitize_error_detail


def _invoke(status: int, detail):
    """直接调用真实 app 注册的 StarletteHTTPException 处理器。"""
    from main import app as fastapi_app

    handler = fastapi_app.exception_handlers[StarletteHTTPException]
    scope = {
        "type": "http", "method": "GET", "path": "/__test",
        "headers": [], "query_string": b"",
    }
    request = Request(scope)

    async def _run():
        return await handler(request, StarletteHTTPException(status_code=status, detail=detail))

    return asyncio.run(_run())


def test_sanitize_pure_function():
    safe, redacted = sanitize_error_detail(
        'duplicate key value violates unique constraint "x_pkey"'
    )
    assert redacted is True
    assert "constraint" not in safe and "subject" not in safe

    safe2, redacted2 = sanitize_error_detail("科目不存在：中医综合")
    assert redacted2 is False
    assert safe2 == "科目不存在：中医综合"


def test_http_exception_sql_leak_redacted():
    r = _invoke(400, '保存失败: relation "subject_removals" does not exist')
    assert r.status_code == 400
    body = r.body.decode()
    assert "subject_removals" not in body
    assert "relation" not in body
    assert "操作失败" in body  # 中性文案落地


def test_http_exception_traceback_redacted():
    r = _invoke(500, 'Traceback (most recent call last): File "x.py", line 1')
    assert r.status_code == 500
    body = r.body.decode()
    assert "Traceback" not in body
    assert "File " not in body


def test_friendly_detail_preserved():
    r = _invoke(404, "科目不存在：中医综合")
    assert r.status_code == 404
    assert "科目不存在：中医综合" in r.body.decode()
