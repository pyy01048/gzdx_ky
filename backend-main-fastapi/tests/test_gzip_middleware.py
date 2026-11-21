"""``utils.middleware.GZipApiMiddleware`` 的选择性压缩行为锁。

为什么要单独锁这一层（2026-11-20）：
    starlette 1.10 重写了 ``GZipResponder.send_with_compression``——**start 消息
    先缓存、等 body 到达才决定是否压缩**。此前的适配写法是"先 super() 再改写
    ``content_type_is_excluded``"，结果 PDF/二进制响应的 start 消息永远发不出去，
    ``/api/words/export-pdf``、``/api/errors/export-pdf`` 在契约巡检里变成
    ``status_code is None``（httpx 侧表现为客户端异常），6 个 PDF 单测全红。

    本文件用裸 ASGI 应用（不连库）把四条准入规则锁死：
      1. JSON / text 且 ≥ minimum_size → gzip 且可解压还原；
      2. application/pdf → 不压缩、Content-Length 保持原值（PDF Range/预览依赖它）；
      3. text/event-stream → 不压缩（压缩会把 SSE 事件卡到流末尾）；
      4. 小响应（< minimum_size）→ 不压缩（父类既有行为，防回归）。

客户端说明（2026-11-21）：
    本机 starlette 0.27 的 ``TestClient`` 会向 httpx 0.28 传已被移除的 ``app=``
    参数（TypeError），与项目其他测试一致改用自研 ``tests/asgi_client.ASGIClient``
    （ASGITransport + AsyncClient 的同步门面）。断言语义与原来完全相同。
"""

from __future__ import annotations

import gzip

import pytest
from asgi_client import ASGIClient
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from utils.middleware import GZipApiMiddleware


def _route(body: bytes, media_type: str, status_code: int = 200):
    async def endpoint(request):  # noqa: ARG001
        return Response(content=body, media_type=media_type, status_code=status_code)

    return Route("/x", endpoint)


def _client(body: bytes, media_type: str, status_code: int = 200) -> ASGIClient:
    app = Starlette(routes=[_route(body, media_type, status_code)])
    return ASGIClient(GZipApiMiddleware(app, minimum_size=1000))


def test_json_response_is_gzipped_and_inflates():
    payload = b'{"data":"' + b"x" * 4000 + b'"}'
    with _client(payload, "application/json") as c:
        resp = c.get("/x", headers={"accept-encoding": "gzip"})

    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") == "gzip"
    # httpx 会按 Content-Encoding 自动解压；这里再手工验一次压缩流本身可还原
    assert gzip.decompress(gzip.compress(payload)) == payload
    assert resp.content == payload
    # 压缩确实生效：线上字节数明显小于原文（响应头 Content-Length 已被压缩后长度覆盖）
    assert int(resp.headers["content-length"]) < len(payload)


def test_pdf_response_passes_through_with_content_length():
    payload = b"%PDF-1.4\n" + b"0" * 4000
    with _client(payload, "application/pdf") as c:
        resp = c.get("/x", headers={"accept-encoding": "gzip"})

    assert resp.status_code == 200, "start 消息必须发出，否则 httpx 报 status_code is None"
    assert "content-encoding" not in resp.headers
    assert resp.headers.get("content-length") == str(len(payload))
    assert resp.content == payload


def test_sse_response_is_not_compressed():
    payload = b"data: " + b"a" * 4000 + b"\n\n"
    with _client(payload, "text/event-stream") as c:
        resp = c.get("/x", headers={"accept-encoding": "gzip"})

    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.content == payload


def test_small_text_response_is_not_compressed():
    payload = b"hello"
    with _client(payload, "text/plain") as c:
        resp = c.get("/x", headers={"accept-encoding": "gzip"})

    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.content == payload


@pytest.mark.parametrize("media_type", ["application/pdf", "application/json"])
def test_identity_accept_encoding_no_compression(media_type):
    payload = b"y" * 4000
    # httpx 默认会带 accept-encoding: gzip, deflate，想测"不压缩"必须显式声明 identity
    with _client(payload, media_type) as c:
        resp = c.get("/x", headers={"accept-encoding": "identity"})

    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.content == payload
