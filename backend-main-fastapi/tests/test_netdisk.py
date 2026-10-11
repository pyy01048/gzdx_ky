"""百度网盘模块回归测试。

**不联网**：用假的 httpx 响应验证错误解析、token 刷新判定、下载行为。
这些正是原实现出错的地方（不检查 errno、不刷新 token、下载不带 UA → 403）。

运行：pytest tests/test_netdisk.py -v
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.netdisk_service import (
    NetdiskService, NetdiskError, NetdiskAuthError, ERRNO_HINT,
    _looks_valid_device_id, _generate_device_id,
)


class FakeResp:
    """最小 httpx.Response 替身。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


# --------------------------------------------------------------------------- #
# 错误码解析
# --------------------------------------------------------------------------- #

class TestErrnoHandling:

    def test_success_passes_through(self):
        data = {"errno": 0, "list": [1, 2]}
        assert NetdiskService._check_errno(data) is data

    def test_missing_errno_treated_as_success(self):
        """有些接口（如 quota）不返回 errno，不能当失败。"""
        data = {"total": 100}
        assert NetdiskService._check_errno(data) is data

    def test_auth_errno_raises_auth_error(self):
        """errno=-6 是"身份验证失败"，必须抛 AuthError 让上层提示重新授权。"""
        with pytest.raises(NetdiskAuthError) as ei:
            NetdiskService._check_errno({"errno": -6, "errmsg": "invalid access_token"})
        assert ei.value.errno == -6

    def test_scope_errno_raises_auth_error(self):
        with pytest.raises(NetdiskAuthError):
            NetdiskService._check_errno({"errno": 31034, "errmsg": "scope error"})

    def test_other_errno_raises_generic_error(self):
        with pytest.raises(NetdiskError) as ei:
            NetdiskService._check_errno({"errno": -7, "errmsg": "file not found"})
        assert ei.value.errno == -7
        assert not isinstance(ei.value, NetdiskAuthError)

    def test_error_message_includes_human_hint(self):
        """报错要带人话提示，否则前端只能显示一个数字。"""
        with pytest.raises(NetdiskError) as ei:
            NetdiskService._check_errno({"errno": -6})
        assert "授权" in str(ei.value) or "身份验证" in str(ei.value)

    def test_request_id_propagated(self):
        with pytest.raises(NetdiskError) as ei:
            NetdiskService._check_errno({"errno": -7, "errmsg": "x", "request_id": "abc123"})
        assert ei.value.request_id == "abc123"

    def test_all_hint_keys_are_ints(self):
        assert all(isinstance(k, int) for k in ERRNO_HINT)


# --------------------------------------------------------------------------- #
# 响应解析
# --------------------------------------------------------------------------- #

class TestParseJson:

    def test_non_json_raises(self):
        with pytest.raises(NetdiskError):
            NetdiskService._parse_json(FakeResp(ValueError("bad json")))

    def test_non_dict_raises(self):
        with pytest.raises(NetdiskError):
            NetdiskService._parse_json(FakeResp([1, 2, 3]))

    def test_dict_ok(self):
        assert NetdiskService._parse_json(FakeResp({"a": 1})) == {"a": 1}


# --------------------------------------------------------------------------- #
# device_id
# --------------------------------------------------------------------------- #

class TestDeviceId:

    def test_generated_is_32_hex(self):
        d = _generate_device_id()
        assert len(d) == 32
        assert _looks_valid_device_id(d)

    def test_rejects_bad_ids(self):
        """百度要求 32 位十六进制；填个 app_id 数字会被拒。"""
        assert not _looks_valid_device_id("")
        assert not _looks_valid_device_id("124216938")
        assert not _looks_valid_device_id("z" * 32)

    def test_accepts_app_id_style_is_rejected(self):
        """常见的错误写法：把 app_id 当 device_id。"""
        assert not _looks_valid_device_id("124216938")


# --------------------------------------------------------------------------- #
# 自动分类
# --------------------------------------------------------------------------- #

class TestAutoClassify:

    def _svc(self):
        return NetdiskService(db=None)

    def test_subject_beats_extension(self):
        """按学科分类比按扩展名有用：'数电笔记.pdf' 应归数电而非 PDF资料。"""
        assert self._svc().auto_classify("数电笔记.pdf") == "数字电子技术"
        assert self._svc().auto_classify("模电第四章讲义.pdf") == "模拟电子技术"
        assert self._svc().auto_classify("张宇1000题.pdf") == "数学"
        assert self._svc().auto_classify("恋恋有词unit1.mp3") == "英语"
        assert self._svc().auto_classify("肖秀荣四套卷.pdf") == "政治"

    def test_falls_back_to_extension(self):
        assert self._svc().auto_classify("abc.mp4") == "视频"
        assert self._svc().auto_classify("abc.zip") == "压缩包"

    def test_unknown_is_other(self):
        assert self._svc().auto_classify("xyzzy") == "其他"


# --------------------------------------------------------------------------- #
# 下载：必须带 pan.baidu.com UA
# --------------------------------------------------------------------------- #

class TestDownloadHeaders:
    """dlink 下载不带 `User-Agent: pan.baidu.com` 会被百度 403 —— 这是硬要求。"""

    def test_pan_user_agent_constant(self):
        assert NetdiskService.PAN_USER_AGENT == "pan.baidu.com"

    def test_download_url_embeds_token(self, monkeypatch):
        svc = NetdiskService(db=None)

        async def fake_token():
            return "TOKEN123"

        async def fake_info(fs_id):
            return {"dlink": "https://d.pcs.baidu.com/file/abc", "filename": "a.pdf", "size": 10}

        monkeypatch.setattr(svc, "_ensure_token", fake_token)
        monkeypatch.setattr(svc, "get_file_info", fake_info)

        import asyncio
        out = asyncio.run(svc.get_download_url("111"))
        assert "access_token=TOKEN123" in out["download_url"]
        assert out["filename"] == "a.pdf"

    def test_download_url_handles_existing_query(self, monkeypatch):
        """dlink 已带 query 时要用 & 拼接，不能出现两个 ?。"""
        svc = NetdiskService(db=None)

        async def fake_token():
            return "T"

        async def fake_info(fs_id):
            return {"dlink": "https://x/y?a=1", "filename": "a.pdf", "size": 1}

        monkeypatch.setattr(svc, "_ensure_token", fake_token)
        monkeypatch.setattr(svc, "get_file_info", fake_info)

        import asyncio
        out = asyncio.run(svc.get_download_url("1"))
        assert out["download_url"].count("?") == 1
        assert "&access_token=T" in out["download_url"]

    def test_missing_dlink_raises(self, monkeypatch):
        svc = NetdiskService(db=None)

        async def fake_token():
            return "T"

        async def fake_info(fs_id):
            return {"filename": "dir"}

        monkeypatch.setattr(svc, "_ensure_token", fake_token)
        monkeypatch.setattr(svc, "get_file_info", fake_info)

        import asyncio
        with pytest.raises(NetdiskError):
            asyncio.run(svc.get_download_url("1"))


# --------------------------------------------------------------------------- #
# token 过期判定
# --------------------------------------------------------------------------- #

class TestTokenStatus:

    def _svc_with(self, monkeypatch, cfg):
        svc = NetdiskService(db=None)
        monkeypatch.setattr(svc, "_get_config", lambda: cfg)
        return svc

    def _cfg(self, **over):
        base = {
            "app_key": "k", "secret_key": "s", "app_id": "1",
            "access_token": "t", "refresh_token": "r",
            "expires_at": None, "device_id": "", "scope": "basic,netdisk",
        }
        base.update(over)
        return base

    def test_not_authorized(self, monkeypatch):
        svc = self._svc_with(monkeypatch, self._cfg(access_token=""))
        st = svc.token_status()
        assert st["authorized"] is False

    def test_expired_detected(self, monkeypatch):
        past = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)).isoformat()
        svc = self._svc_with(monkeypatch, self._cfg(expires_at=past))
        st = svc.token_status()
        assert st["expired"] is True
        assert st["expires_in_seconds"] < 0

    def test_valid_remaining(self, monkeypatch):
        future = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=10)).isoformat()
        svc = self._svc_with(monkeypatch, self._cfg(expires_at=future))
        st = svc.token_status()
        assert st["expired"] is False
        assert st["expires_in_seconds"] > 0
        assert st["has_refresh_token"] is True

    def test_corrupt_expires_at_does_not_crash(self, monkeypatch):
        """脏数据不应让整个接口 500。"""
        svc = self._svc_with(monkeypatch, self._cfg(expires_at="not-a-date"))
        st = svc.token_status()
        assert st["authorized"] is True
        assert st["expired"] is None

    def test_no_token_raises_auth_error(self, monkeypatch):
        svc = self._svc_with(monkeypatch, self._cfg(access_token=""))
        import asyncio
        with pytest.raises(NetdiskAuthError):
            asyncio.run(svc._ensure_token())


# --------------------------------------------------------------------------- #
# 自动刷新
# --------------------------------------------------------------------------- #

class TestAutoRefresh:
    """接近过期应自动刷新 —— 原实现有 refresh_token 却从不使用。"""

    def test_refreshes_when_near_expiry(self, monkeypatch):
        soon = (datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=60)).isoformat()
        cfg = {
            "app_key": "k", "secret_key": "s", "app_id": "1",
            "access_token": "OLD", "refresh_token": "R",
            "expires_at": soon, "device_id": "", "scope": "basic,netdisk",
        }
        svc = NetdiskService(db=None)
        monkeypatch.setattr(svc, "_get_config", lambda: dict(cfg))

        called = {"n": 0}

        async def fake_refresh():
            called["n"] += 1
            cfg["access_token"] = "NEW"
            return {"success": True}

        monkeypatch.setattr(svc, "refresh_access_token", fake_refresh)

        import asyncio
        token = asyncio.run(svc._ensure_token())
        assert called["n"] == 1, "接近过期时应触发刷新"
        assert token == "NEW", "刷新后应返回新 token"

    def test_no_refresh_when_fresh(self, monkeypatch):
        far = (datetime.datetime.now(datetime.UTC)
               + datetime.timedelta(days=20)).isoformat()
        cfg = {
            "app_key": "k", "secret_key": "s", "app_id": "1",
            "access_token": "GOOD", "refresh_token": "R",
            "expires_at": far, "device_id": "", "scope": "basic,netdisk",
        }
        svc = NetdiskService(db=None)
        monkeypatch.setattr(svc, "_get_config", lambda: dict(cfg))

        called = {"n": 0}

        async def fake_refresh():
            called["n"] += 1
            return {"success": True}

        monkeypatch.setattr(svc, "refresh_access_token", fake_refresh)

        import asyncio
        token = asyncio.run(svc._ensure_token())
        assert called["n"] == 0, "token 还很久才过期，不该刷新"
        assert token == "GOOD"

    def test_expired_without_refresh_token_raises(self, monkeypatch):
        past = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)).isoformat()
        cfg = {
            "app_key": "k", "secret_key": "s", "app_id": "1",
            "access_token": "OLD", "refresh_token": "",
            "expires_at": past, "device_id": "", "scope": "basic,netdisk",
        }
        svc = NetdiskService(db=None)
        monkeypatch.setattr(svc, "_get_config", lambda: dict(cfg))

        import asyncio
        with pytest.raises(NetdiskAuthError) as ei:
            asyncio.run(svc._ensure_token())
        assert "重新授权" in ei.value.errmsg
