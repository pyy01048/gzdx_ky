"""网盘凭据：不出接口 + 密文落库（P0-SEC）。

改造前真实存在的四条泄露路径，本文件逐条钉住：

1. ``GET /api/netdisk/platform-configs`` 把 access_token / app_key / secret_key
   连同 ``extra`` 里的 refresh_token 一起下发（旧代码 ``**extra`` 会把嵌套键
   提升到顶层），浏览器和它的缓存层因此持有可用凭据；
2. ``POST /api/netdisk/callback`` 把 access_token 回传给前端，前端存进
   localStorage —— XSS 可直接读走；
3. ``platform_configs`` 三个凭据列明文落库，而本项目每天做 ``pg_dump`` 备份，
   备份是纯文本 —— 备份外流等于凭据外流；
4. ``GET /netdisk/files`` 与 ``/preview/{id}`` 把带签名的 dlink / 含
   ``access_token`` query 的 M3U8 地址交给浏览器，地址会进历史、referer 与
   上层访问日志。

约定：测试用哨兵值（``SENTINEL-*``）而不是真实凭据；.env 里的真 key 不参与
断言，也不得出现在任何断言失败信息里。

同类的 ``ai_providers.api_key`` 走同一套 EncryptedText（它的 GET 早就只回
has_api_key），本文件末尾一并钉住落库形态。

运行：pytest tests/test_netdisk_credentials.py -v
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import base64

import pytest
from sqlalchemy import orm as sa_orm, text

from database import SessionLocal, engine
from models import AIProvider, NetdiskFile, PlatformConfig
from services.netdisk_service import NetdiskService
from utils import secret_codec as sc

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


APPKEY = "SENTINEL-APPKEY-8f2b"
SECRET = "SENTINEL-SECRETKEY-3c7a"
ATOKEN = "SENTINEL-ACCESS-" + "t" * 48   # 接近真实 access_token 的长度
RTOKEN = "SENTINEL-REFRESH-9d41"
AIKEY = "SENTINEL-AIKEY-sk-0f3c9a"


def _raw_row(platform="baidu_netdisk"):
    """绕过 ORM 直接读列：验证「落库形态」，ORM 会自动解密所以看不出区别。"""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT token, app_key, secret_key, CAST(extra AS TEXT) "
                "FROM platform_configs WHERE platform_name = :p"
            ),
            {"p": platform},
        ).fetchone()


@pytest.fixture
def baidu_cfg(db_schema):  # noqa: ARG001 - db_schema 只保证测试库已建表
    """交出凭据列已清空的 baidu_netdisk **ORM 行**，用例结束后原样还原。

    会话级共享库里别的用例可能已经种过这一行，直接删会让它们找不到数据，
    所以先快照再还原，而不是 cleanup 删行。
    """
    db = SessionLocal()

    def _live():
        return (
            db.query(PlatformConfig)
            .filter(PlatformConfig.platform_name == "baidu_netdisk")
            .first()
        )

    row = _live()
    snapshot = None
    try:
        if row:
            snapshot = (row.token, row.app_key, row.secret_key, dict(row.extra or {}))
            row.token, row.app_key, row.secret_key, row.extra = None, None, None, {}
            db.commit()
        else:
            row = PlatformConfig(platform_name="baidu_netdisk")
            db.add(row)
            db.commit()
        yield row
    finally:
        live = _live()
        if snapshot is None:
            if live:
                db.delete(live)
        else:
            if live is None:
                live = PlatformConfig(platform_name="baidu_netdisk")
                db.add(live)
            live.token, live.app_key, live.secret_key, live.extra = snapshot
        db.commit()
        db.close()


def _db_of(obj):
    """取 ORM 行自己的 Session：用例里要 commit / 建关联行时用它，而不是另开连接。"""
    return sa_orm.object_session(obj)


def _read_back():
    """新开会话再读一次 baidu_netdisk。

    直接 refresh 原对象不行：PUT 接口用的是应用自己的会话，测试会话里的
    ORM 对象根本不知道那一轮写入发生过 —— 只有重新查一遍才证明
    「落库密文 → 读出明文」这条链真的通。
    """
    db = SessionLocal()
    try:
        return (
            db.query(PlatformConfig)
            .filter(PlatformConfig.platform_name == "baidu_netdisk")
            .first()
        )
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 3. 落库形态：密文
# --------------------------------------------------------------------------- #
class TestCiphertextAtRest:

    def test_credential_columns_are_sealed(self, baidu_cfg):
        baidu_cfg.token = ATOKEN
        baidu_cfg.app_key = APPKEY
        baidu_cfg.secret_key = SECRET
        _db_of(baidu_cfg).commit()

        raw = _raw_row()
        for value in raw[:3]:
            assert sc.is_sealed(value), f"凭据列未加密落库，备份外流即凭据外流：{str(value)[:12]}…"
        assert ATOKEN not in "".join(str(v) for v in raw), "明文凭据出现在库行里"

        # ORM 侧读回来仍是明文：加密对业务透明，不需要每个调用点自己解
        fresh = _read_back()
        assert fresh.token == ATOKEN
        assert fresh.secret_key == SECRET

    def test_refresh_token_in_extra_is_sealed(self, baidu_cfg):
        svc = NetdiskService(_db_of(baidu_cfg))
        svc._save_config(  # noqa: SLF001 - 就是要测这个写入口
            access_token=ATOKEN, refresh_token=RTOKEN, expires_at="2099-01-01T00:00:00"
        )
        raw = _raw_row()
        assert RTOKEN not in raw[3], "extra 里的 refresh_token 明文落库"
        assert sc.is_sealed(json.loads(raw[3])["refresh_token"])

        cfg = svc._get_config()  # noqa: SLF001
        assert cfg["refresh_token"] == RTOKEN, "读取侧没解封，refresh 会拿密文去换 token"

    def test_legacy_plaintext_row_stays_readable(self, baidu_cfg):
        """迁移前的明文行不能读成密文：无 enc:v1: 前缀即原样返回，下次写入自动升级。"""
        db = _db_of(baidu_cfg)
        db.execute(
            text(
                "UPDATE platform_configs SET token = :t WHERE platform_name = 'baidu_netdisk'"
            ),
            {"t": "LEGACY-PLAINTEXT-TOKEN"},
        )
        db.commit()
        assert _raw_row()[0] == "LEGACY-PLAINTEXT-TOKEN"
        assert _read_back().token == "LEGACY-PLAINTEXT-TOKEN"


# --------------------------------------------------------------------------- #
# 3b. 同类的 ai_providers.api_key：只钉落库形态（GET 早已只回 has_api_key）
# --------------------------------------------------------------------------- #
@pytest.fixture
def ai_provider(db_schema):  # noqa: ARG001 - db_schema 只保证测试库已建表
    """临时服务商行，name 唯一所以用完即删，不污染启动种下的 3 条默认配置。"""
    db = SessionLocal()
    row = AIProvider(
        name="SENTINEL-provider",
        provider_type="openai_compatible",
        base_url="https://sentinel.invalid/v1",
        model_name="sentinel-model",
        is_enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        yield row
    finally:
        live = db.query(AIProvider).filter(AIProvider.id == row.id).first()
        if live:
            db.delete(live)
        db.commit()
        db.close()


class TestAiProviderKeyAtRest:

    def _raw_key(self, provider_id):
        with engine.connect() as conn:
            return conn.execute(
                text("SELECT api_key FROM ai_providers WHERE id = :i"), {"i": provider_id}
            ).scalar()

    def test_api_key_is_sealed_on_write(self, ai_provider):
        ai_provider.api_key = AIKEY
        _db_of(ai_provider).commit()

        raw = self._raw_key(ai_provider.id)
        assert sc.is_sealed(raw), f"api_key 明文落库：{str(raw)[:12]}…"
        assert AIKEY not in raw

        db = SessionLocal()
        try:
            fresh = db.query(AIProvider).filter(AIProvider.id == ai_provider.id).one()
            assert fresh.api_key == AIKEY, "读出侧没解封，网关会拿密文去请求上游"
        finally:
            db.close()

    def test_providers_list_still_only_reports_has_flag(self, client, ai_provider):
        ai_provider.api_key = AIKEY
        _db_of(ai_provider).commit()

        resp = client.get("/api/ai/providers")
        assert resp.status_code == 200, resp.text
        assert AIKEY not in resp.text
        mine = [p for p in resp.json() if p["name"] == "SENTINEL-provider"]
        assert mine and mine[0]["has_api_key"] is True


# --------------------------------------------------------------------------- #
# 1 & 2. 传输层：凭据不出接口
# --------------------------------------------------------------------------- #
class TestCredentialsNeverLeave:

    def _assert_no_secret(self, payload):
        """整份响应文本级扫描 —— 提升顶层、嵌套 extra、序列化遗漏都躲不掉。"""
        blob = json.dumps(payload, ensure_ascii=False)
        for value in (APPKEY, SECRET, ATOKEN, RTOKEN):
            assert value not in blob, f"凭据 {value[:12]}… 出现在响应体里"

    def test_platform_configs_only_reports_has_flags(self, client, baidu_cfg):
        baidu_cfg.token = ATOKEN
        baidu_cfg.app_key = APPKEY
        baidu_cfg.secret_key = SECRET
        baidu_cfg.extra = sc.seal_extra({"refresh_token": RTOKEN, "sync_dir": "/考研资料"})
        _db_of(baidu_cfg).commit()

        resp = client.get("/api/netdisk/platform-configs")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        self._assert_no_secret(body)

        baidu = body["configs"]["baidu"]
        assert baidu["has_app_key"] is True
        assert baidu["has_secret_key"] is True
        assert baidu["has_token"] is True
        assert baidu["has_refresh_token"] is True
        # 非敏感配置照常可见，前端才能继续显示同步目录
        assert baidu["sync_dir"] == "/考研资料"

        single = client.get("/api/netdisk/platform-config/baidu")
        assert single.status_code == 200, single.text
        self._assert_no_secret(single.json())
        assert single.json()["authorized"] is True

    def test_put_response_does_not_echo_credentials(self, client, baidu_cfg):
        resp = client.put(
            "/api/netdisk/platform-config/baidu",
            json={"app_key": APPKEY, "secret_key": SECRET},
        )
        assert resp.status_code == 200, resp.text
        self._assert_no_secret(resp.json())
        assert resp.json()["has_secret_key"] is True

    def test_empty_secret_means_unchanged_not_cleared(self, client, baidu_cfg):
        """GET 不回原值，所以表单留空是「没碰过」而不是「清空」，否则一次保存就抹掉密钥。"""
        client.put(
            "/api/netdisk/platform-config/baidu",
            json={"app_key": APPKEY, "secret_key": SECRET},
        )
        resp = client.put(
            "/api/netdisk/platform-config/baidu",
            json={"app_key": "", "secret_key": "", "sync_enabled": True},
        )
        assert resp.status_code == 200, resp.text

        fresh = _read_back()
        assert fresh.app_key == APPKEY, "留空提交把已存的 app_key 抹掉了"
        assert fresh.secret_key == SECRET
        assert fresh.sync_enabled is True

    def test_has_flags_from_client_are_ignored(self, client, baidu_cfg):
        """前端表单很容易把 GET 到的状态位原样 POST 回来，这些键不许进 extra。"""
        client.put(
            "/api/netdisk/platform-config/baidu",
            json={"has_secret_key": True, "authorized": True, "configured": False},
        )
        raw = _raw_row()
        stored = json.loads(raw[3])
        assert "has_secret_key" not in stored
        assert "authorized" not in stored

    def test_callback_returns_status_not_access_token(self, monkeypatch, db_schema):  # noqa: ARG001
        svc = NetdiskService(None)
        payload = {
            "access_token": ATOKEN,
            "refresh_token": RTOKEN,
            "expires_in": 2592000,
            "scope": "basic,netdisk",
        }

        class FakeResp:
            status_code = 200

            def json(self):
                return payload

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, params=None):
                return FakeResp()

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(svc, "_save_token", lambda data: None)
        monkeypatch.setattr(
            svc, "_get_config", lambda: {"app_key": APPKEY, "secret_key": SECRET}
        )

        import asyncio

        result = asyncio.run(svc.handle_callback("code123", "oob"))
        assert result["success"] is True
        assert "access_token" not in result, "token 回传后会被前端存进 localStorage"
        assert result["has_refresh_token"] is True


# --------------------------------------------------------------------------- #
# 4. 下载地址：dlink / M3U8 不下发，取流统一走后端代理
# --------------------------------------------------------------------------- #
class TestDownloadPathsAreProxied:

    def _mkfile(self, db):
        row = NetdiskFile(
            file_name="信号与系统冲刺.pdf",
            path="/考研资料/冲刺/信号与系统冲刺.pdf",
            file_type="pdf",
            size=1024,
            category="讲义",
            fs_id="1065450778599627",
            download_link="https://d.pcs.baidu.com/file/abc?sign=SENTINEL-DLINK-SIGN",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def test_files_list_has_no_dlink(self, client, baidu_cfg, monkeypatch):
        db = _db_of(baidu_cfg)
        file_row = self._mkfile(db)
        try:
            async def fake_list(self, path="/", page=1, num=50):
                return {
                    "list": [
                        {
                            "fs_id": 999,
                            "server_filename": "远程.pdf",
                            "path": "/考研资料/远程.pdf",
                            "size": 2048,
                            "isdir": 0,
                            "dlink": "https://d.pcs.baidu.com/remote?sign=SENTINEL-REMOTE-DLINK",
                        }
                    ]
                }

            monkeypatch.setattr(NetdiskService, "get_file_list", fake_list)
            resp = client.get("/api/netdisk/files", params={"path": "/考研资料/"})
            assert resp.status_code == 200, resp.text
            blob = resp.text
            assert "SENTINEL-DLINK-SIGN" not in blob
            assert "SENTINEL-REMOTE-DLINK" not in blob
            assert "download_link" not in blob
            assert "dlink" not in blob
            # 但取流所需标识必须在，否则前端拼不出代理地址
            assert str(file_row.fs_id) in blob
        finally:
            db.delete(file_row)
            db.commit()

    def test_file_detail_has_no_dlink(self, client, baidu_cfg):
        db = _db_of(baidu_cfg)
        file_row = self._mkfile(db)
        try:
            resp = client.get(f"/api/netdisk/files/{file_row.id}")
            assert resp.status_code == 200, resp.text
            assert "SENTINEL-DLINK-SIGN" not in resp.text
        finally:
            db.delete(file_row)
            db.commit()

    def test_preview_returns_backend_proxy_path(self, client, baidu_cfg):
        db = _db_of(baidu_cfg)
        file_row = self._mkfile(db)
        try:
            resp = client.get(f"/api/netdisk/preview/{file_row.id}")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["mode"] == "backend_proxy"
            assert body["preview_url"] == f"/api/netdisk/files/{file_row.id}/content?disposition=inline"
            assert "access_token" not in resp.text, "预览地址不得携带 token"
            assert "pan.baidu.com" not in resp.text
        finally:
            db.delete(file_row)
            db.commit()


# --------------------------------------------------------------------------- #
# 加密原语本身
# --------------------------------------------------------------------------- #
class TestCodec:

    def test_roundtrip_and_seal_idempotent(self):
        once = sc.seal(ATOKEN)
        assert sc.unseal(once) == ATOKEN
        assert sc.seal(once) == once, "重复封装会套两层，读回来是密文"

    def test_empty_values_pass_through(self):
        assert sc.seal("") == ""
        assert sc.seal(None) is None
        assert sc.unseal(None) is None

    def test_same_plaintext_yields_different_ciphertext(self):
        """nonce 随机：等值查询密文列必然失效，所以凭据列只能整体存取。"""
        assert sc.seal(ATOKEN) != sc.seal(ATOKEN)

    def test_wrong_key_fails_loud(self):
        sealed = sc.seal(ATOKEN)
        other = os.environ.get(sc.SECRET_ENV_VAR)
        os.environ[sc.SECRET_ENV_VAR] = _b64(b"k" * 32)   # 另一把合法 32 字节钥
        sc.reset_key_cache()
        try:
            with pytest.raises(sc.SecretDecodeError):
                sc.unseal(sealed)
        finally:
            os.environ.pop(sc.SECRET_ENV_VAR, None)
            if other is not None:
                os.environ[sc.SECRET_ENV_VAR] = other
            sc.reset_key_cache()

    def test_tampered_ciphertext_fails_loud(self):
        sealed = sc.seal(ATOKEN)
        head, tail = sealed[:-4], sealed[-4:]
        flipped = "AAAA" if tail != "AAAA" else "BBBB"
        with pytest.raises(sc.SecretDecodeError):
            sc.unseal(head + flipped)

    def test_bad_base64_payload_fails_loud(self):
        with pytest.raises(sc.SecretDecodeError):
            sc.unseal("enc:v1:!!!not-base64!!!")

    def test_env_key_is_32_bytes(self):
        os.environ[sc.SECRET_ENV_VAR] = _b64(b"x" * 16)   # 合法 base64、非法长度
        sc.reset_key_cache()
        try:
            with pytest.raises(ValueError):
                sc.seal("x")
        finally:
            os.environ.pop(sc.SECRET_ENV_VAR, None)
            sc.reset_key_cache()

    def test_scrub_extra_drops_every_secret_key(self):
        extra = {"refresh_token": "r", "password": "p", "sessdata": "s", "sync_dir": "/x"}
        assert sc.scrub_extra(extra) == {"sync_dir": "/x"}
        assert sc.scrub_extra(None) == {}
