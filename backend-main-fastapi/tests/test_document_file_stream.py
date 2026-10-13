"""#26 原文字节流：本地文档预览/下载 + 网盘服务端代理。

为什么要锁这几条：
- 库内实测 2611 篇里只有 **1857** 篇原文真在盘上，77 篇路径已失效、**238 篇是 IMA
  媒体号（本地从来没有这个文件）**、439 篇没登记路径。前端要能区分"没有原文"和
  "读失败"，否则按钮点了永远报错，用户会以为平台坏了。
- 单文件最大实测 **908 MB**，且 Starlette 0.27 的 `FileResponse` **不支持 Range**
  （源码里没有 range/206，已实测确认），而 Chrome 的 PDF 查看器是要发 Range 的。
- 网盘侧：百度 dlink **强制** `User-Agent: pan.baidu.com`，浏览器直连必 403，
  所以取流只能由后端代理。

只用 conftest 临时库 + pytest 临时目录（红线：绝不碰 D:\\平台\\database\\kaoyan.db）。
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

BODY = b"%PDF-1.4\n0123456789abcdef\n%%EOF\n"
NAME = "数字电子技术 第6版.pdf"


@pytest.fixture()
def local_root(tmp_path, monkeypatch):
    """把允许读取的根换成临时目录（真原文在 BASE_DIR 下，测试不能依赖它）。"""
    import routers.documents as dmod

    root = os.path.realpath(str(tmp_path))
    monkeypatch.setattr(dmod, "LOCAL_FILE_ROOTS", [root])
    return root


def _touch(root, name=NAME, body=BODY):
    """在允许根内落一个真文件，返回绝对路径。"""
    p = os.path.join(root, name)
    with open(p, "wb") as fh:
        fh.write(body)
    return p


def _doc(file_name, file_path, **kw):
    """只建 Document 行（不碰磁盘），返回 doc.id。"""
    from database import SessionLocal
    from models import Document

    db = SessionLocal()
    try:
        doc = Document(file_name=file_name, file_path=file_path, file_type="pdf",
                       size=len(BODY), index_status="indexed", **kw)
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id
    finally:
        db.close()


def _cleanup(*ids):
    from database import SessionLocal
    from models import Document, NetdiskFile

    db = SessionLocal()
    try:
        for i in ids:
            for model in (Document, NetdiskFile):
                row = db.query(model).filter(model.id == i).first()
                if row:
                    db.delete(row)
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 本地原文
# --------------------------------------------------------------------------- #
def test_raw_streams_whole_file_and_advertises_ranges(client, local_root):
    did = _doc(NAME, _touch(local_root))
    try:
        r = client.get(f"/api/documents/{did}/raw")
        assert r.status_code == 200, r.text
        assert r.content == BODY
        assert r.headers["accept-ranges"] == "bytes"
        assert r.headers["content-length"] == str(len(BODY))
        assert r.headers["content-type"].startswith("application/pdf")
        cd = r.headers["content-disposition"]
        assert cd.startswith("inline;")
        assert "filename*=UTF-8''" in cd
    finally:
        _cleanup(did)


def test_range_request_returns_206_slice(client, local_root):
    did = _doc(NAME, _touch(local_root))
    try:
        r = client.get(f"/api/documents/{did}/raw", headers={"Range": "bytes=5-9"})
        assert r.status_code == 206, r.text
        assert r.content == BODY[5:10]
        assert r.headers["content-range"] == f"bytes 5-9/{len(BODY)}"
        assert r.headers["content-length"] == "5"
    finally:
        _cleanup(did)


def test_suffix_range_and_unsatisfiable_range(client, local_root):
    did = _doc(NAME, _touch(local_root))
    try:
        r = client.get(f"/api/documents/{did}/raw", headers={"Range": "bytes=-4"})
        assert r.status_code == 206, r.text
        assert r.content == BODY[-4:]
        assert r.headers["content-range"] == \
            f"bytes {len(BODY) - 4}-{len(BODY) - 1}/{len(BODY)}"

        r2 = client.get(f"/api/documents/{did}/raw", headers={"Range": "bytes=99999-"})
        assert r2.status_code == 416, r2.text
        assert r2.headers["content-range"] == f"bytes */{len(BODY)}"

        # bytes=-0 是零长区间，不能算出 start>end 的畸形 Content-Range
        r3 = client.get(f"/api/documents/{did}/raw", headers={"Range": "bytes=-0"})
        assert r3.status_code == 416, r3.text

        # 整区间等价于全量 200
        r4 = client.get(f"/api/documents/{did}/raw", headers={"Range": "bytes=0-"})
        assert r4.status_code == 200 and r4.content == BODY
    finally:
        _cleanup(did)


def test_download_attachment_keeps_chinese_name(client, local_root):
    cn = "模拟电子技术（第5版）.pdf"
    did = _doc(cn, _touch(local_root, cn))
    try:
        r = client.get(f"/api/documents/{did}/download")
        assert r.status_code == 200, r.text
        cd = r.headers["content-disposition"]
        assert cd.startswith("attachment;")
        # 中文名必须走 RFC 5987，ASCII 兜底也不能缺
        assert "filename*=UTF-8''%E6%A8%A1%E6%8B%9F" in cd
        assert 'filename="' in cd
        assert r.content == BODY
    finally:
        _cleanup(did)


def test_deleted_original_gives_explainable_404(client, local_root):
    did = _doc("已被移走的书.pdf", os.path.join(local_root, "已被移走的书.pdf"))
    try:
        r = client.get(f"/api/documents/{did}/raw")
        assert r.status_code == 404
        assert "已不在磁盘" in r.json()["detail"]
    finally:
        _cleanup(did)


def test_ima_media_id_is_not_mistaken_for_a_local_file(client, local_root):
    """IMA 那 238 篇把媒体号写在 file_path 上：不能说它"文件丢失"，要说本地没有。"""
    media = "pdf_cls1_b6e72461ef4664490f7889896f15acdd_4a7119067c3def1312cd"
    did = _doc("《计算机组成原理》唐朔飞.pdf", media, ima_media_id=media)
    try:
        r = client.get(f"/api/documents/{did}/raw")
        assert r.status_code == 404
        assert "媒体号" in r.json()["detail"]
    finally:
        _cleanup(did)


def test_path_outside_allowed_root_is_refused(client, local_root):
    """红线：file_path 是绝对路径也不能读出允许目录之外（防遍历）。"""
    outside = tempfile.mkdtemp(prefix="qa_escape_")
    try:
        victim = os.path.join(outside, "secret.pdf")
        with open(victim, "wb") as fh:
            fh.write(BODY)
        did = _doc("secret.pdf", victim)
        try:
            r = client.get(f"/api/documents/{did}/raw")
            assert r.status_code == 404, r.text
            assert "越出允许目录" in r.json()["detail"]
        finally:
            _cleanup(did)
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_dotdot_traversal_is_refused(client, local_root):
    """红线：`..` 拼出来的路径归一化后不在根内就拒绝，且不去 stat 它（不泄露存在性）。"""
    evil = os.path.join(local_root, "..", "..", "windows_secret.pdf")
    did = _doc("windows_secret.pdf", evil)
    try:
        r = client.get(f"/api/documents/{did}/raw")
        assert r.status_code == 404
        assert "越出允许目录" in r.json()["detail"]
    finally:
        _cleanup(did)


def test_list_marks_file_availability_per_doc(client, local_root):
    ok = _doc("在盘上的.pdf", _touch(local_root, "在盘上的.pdf"))
    gone = _doc("没了.pdf", os.path.join(local_root, "没了.pdf"))
    try:
        rows = {d["id"]: d for d in client.get("/api/documents").json()}
        assert rows[ok]["has_local_file"] is True
        assert rows[ok]["local_file_note"] is None
        assert rows[gone]["has_local_file"] is False
        assert "已不在磁盘" in rows[gone]["local_file_note"]
    finally:
        _cleanup(ok, gone)


def test_unknown_doc_id_is_404(client, local_root):  # noqa: ARG001
    assert client.get("/api/documents/999999/raw").status_code == 404
    assert client.get("/api/documents/999999/download").status_code == 404


# --------------------------------------------------------------------------- #
# 网盘服务端代理
# --------------------------------------------------------------------------- #
def _netdisk_row(**kw):
    from database import SessionLocal
    from models import NetdiskFile

    db = SessionLocal()
    try:
        row = NetdiskFile(**kw)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _parse_range(header, total):
    """把 `bytes=start-end` 解成 (start, end)。只覆盖测试用到的简单形态。"""
    spec = header.split("=", 1)[1]
    start_s, _, end_s = spec.partition("-")
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else total - 1
    return start, min(end, total - 1)


class _FakeUpstreamResp:
    """替身：只保留 `_proxy_stream` 真正读到的字段。"""

    def __init__(self, body, status_code=200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers if headers is not None else {"content-length": str(len(body))}

    async def aiter_bytes(self, chunk_size=1 << 20):  # noqa: ARG002
        # 故意用 7 字节小块：大块会掩盖「漏拼 / 重复拼接」的 bug
        for i in range(0, len(self._body), 7):
            yield self._body[i:i + 7]


class _FakeOpenDownload:
    """替身：模拟 `@asynccontextmanager` 形态的 open_download，yield (resp, client)。"""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp, None

    async def __aexit__(self, *exc):  # noqa: ARG002
        return False


@pytest.fixture()
def fake_pan(monkeypatch):
    """把百度的「取链接」与「打开下载流」两步替成假数据（绝不联网）。

    必须 patch **当前真实入口** `open_download()`：`_proxy_stream` 在 0202eee
    为支持视频/图片 Range seek 改用 `open_download`（返回 206 + Content-Range），
    旧的 `iter_download` 已不在代理链路上。
    只 patch 旧名字会让 patch **静默失效** —— 测试真的去打上游，拿到的是
    404/502 而不是断言失败，排查成本极高（曾经就是这个原因让本文件红了两处）。
    """
    from services.netdisk_service import NetdiskService

    state = {"size": len(BODY), "error": None}

    async def fake_url(self, fs_id):  # noqa: ARG001
        if state["error"]:
            raise state["error"]
        return {"download_url": "https://pan.baidu.com/disk/x", "filename": "x.pdf",
                "size": state["size"], "md5": ""}

    def fake_open(self, fs_id, *, range_header=None):  # noqa: ARG001
        if state["error"]:
            raise state["error"]
        if range_header:
            start, end = _parse_range(range_header, len(BODY))
            return _FakeOpenDownload(_FakeUpstreamResp(
                BODY[start:end + 1],
                status_code=206,
                headers={"content-length": str(end - start + 1),
                         "content-range": f"bytes {start}-{end}/{len(BODY)}"},
            ))
        return _FakeOpenDownload(_FakeUpstreamResp(BODY))

    monkeypatch.setattr(NetdiskService, "get_download_url", fake_url)
    monkeypatch.setattr(NetdiskService, "open_download", fake_open)
    return state


def test_netdisk_content_proxies_bytes_through_server(client, fake_pan):
    fid = _netdisk_row(file_name="考研政治真题 2025.pdf", fs_id="10001", size=len(BODY))
    try:
        r = client.get(f"/api/netdisk/files/{fid}/content")
        assert r.status_code == 200, r.text
        assert r.content == BODY
        assert r.headers["content-disposition"].startswith("inline;")
        assert "filename*=UTF-8''" in r.headers["content-disposition"]
        assert r.headers["content-length"] == str(len(BODY))
        # 0202eee 起声明 support Range：视频 <video> 拖动进度条 / 图片分段加载都依赖它
        assert r.headers["accept-ranges"] == "bytes"
    finally:
        _cleanup(fid)


def test_netdisk_content_attachment_and_size_guard(client, fake_pan, monkeypatch):
    import routers.netdisk as nd

    monkeypatch.setattr(nd, "MAX_DOWNLOAD_BYTES", 8)
    fid = _netdisk_row(file_name="过大的视频.pdf", fs_id="10002", size=len(BODY))
    try:
        big = client.get(f"/api/netdisk/files/{fid}/content")
        assert big.status_code == 413
        # 非 404 走统一错误体：字符串 detail 落在 message 字段（utils/exceptions.py）
        assert "超过代理上限" in big.json()["message"]

        monkeypatch.setattr(nd, "MAX_DOWNLOAD_BYTES", 10 ** 9)
        ok = client.get(f"/api/netdisk/files/{fid}/content",
                        params={"disposition": "attachment"})
        assert ok.status_code == 200
        assert ok.headers["content-disposition"].startswith("attachment;")

        bad = client.get(f"/api/netdisk/files/{fid}/content",
                         params={"disposition": "evil\r\nX: 1"})
        assert bad.status_code == 400
    finally:
        _cleanup(fid)


def test_netdisk_content_error_mapping(client, fake_pan):
    from services.netdisk_service import NetdiskAuthError

    fid = _netdisk_row(file_name="没fsid.pdf", size=10)
    fid2 = _netdisk_row(file_name="token失效.pdf", fs_id="10003", size=10)
    try:
        assert client.get(f"/api/netdisk/files/{fid}/content").status_code == 400
        fake_pan["error"] = NetdiskAuthError(-6, "access_token 失效")
        r = client.get(f"/api/netdisk/files/{fid2}/content")
        assert r.status_code == 401
        assert r.json()["detail"]["action"] == "reauthorize"
        assert client.get("/api/netdisk/files/999999/content").status_code == 404
    finally:
        _cleanup(fid, fid2)


# --------------------------------------------------------------------------- #
# 按 fs_id 取流：网盘目录页（Pan.jsx）只持有 fs_id，没有本地记录 id
# --------------------------------------------------------------------------- #
def _netdisk_id_by_fs(fs_id):
    from database import SessionLocal
    from models import NetdiskFile

    db = SessionLocal()
    try:
        row = db.query(NetdiskFile).filter(NetdiskFile.fs_id == fs_id).first()
        return row.id if row else None
    finally:
        db.close()


def test_netdisk_content_by_fsid_streams_existing_row(client, fake_pan):
    fid = _netdisk_row(file_name="百度云里的讲义.pdf", fs_id="20001", size=len(BODY))
    try:
        r = client.get("/api/netdisk/content", params={"fs_id": "20001"})
        assert r.status_code == 200, r.text
        assert r.content == BODY
        assert r.headers["accept-ranges"] == "bytes"
    finally:
        _cleanup(fid)


def test_netdisk_content_passes_through_range_206(client, fake_pan):
    """代理必须透传 Range（206 + Content-Range）。

    0202eee 的核心收益：百度 dlink 支持 Range 时后端回 206，视频播放器才能 seek。
    这条锁住它——退化成 200 全量会让 908MB 的课视频「不能拖进度条」。
    """
    fid = _netdisk_row(file_name="能拖进度条的课.mp4", fs_id="10009", size=len(BODY))
    try:
        r = client.get(f"/api/netdisk/files/{fid}/content",
                       headers={"Range": "bytes=5-9"})
        assert r.status_code == 206, r.text
        assert r.content == BODY[5:10]
        assert r.headers["content-range"] == f"bytes 5-9/{len(BODY)}"
        assert r.headers["accept-ranges"] == "bytes"
    finally:
        _cleanup(fid)


def test_netdisk_content_by_fsid_creates_missing_row(client, fake_pan, monkeypatch):
    """目录里第一次见到的文件：先补一行 NetdiskFile，再把流吐出去。"""
    from services.netdisk_service import NetdiskService

    async def fake_info(self, fs_id):  # noqa: ARG001
        return {"filename": "目录里新见的.pdf", "path": "/考研/目录里新见的.pdf",
                "size": len(BODY)}

    monkeypatch.setattr(NetdiskService, "get_file_info", fake_info)
    r = client.get("/api/netdisk/content",
                   params={"fs_id": "20002", "disposition": "attachment"})
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith("attachment;")
    created = _netdisk_id_by_fs("20002")
    assert created is not None
    _cleanup(created)


def test_netdisk_content_by_fsid_rejects_junk_and_bad_disposition(client, fake_pan):
    bad = client.get("/api/netdisk/content", params={"fs_id": "1;drop table"})
    assert bad.status_code == 400
    assert "fs_id" in bad.json()["message"]

    fid = _netdisk_row(file_name="按fsid取.pdf", fs_id="20003", size=len(BODY))
    try:
        d = client.get("/api/netdisk/content",
                       params={"fs_id": "20003", "disposition": "evil\r\nX: 1"})
        assert d.status_code == 400
    finally:
        _cleanup(fid)
