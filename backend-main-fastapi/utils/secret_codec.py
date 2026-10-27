"""平台凭据的落库加密（AES-256-GCM）与序列化脱敏。

为什么要加密 ``platform_configs`` 的凭据列
------------------------------------------
那三列存的是百度网盘 OAuth 的 access_token / app_key / secret_key，
拿到就能列全量文件、下载课件、以用户身份写网盘。加密前它们是明文，
而本项目每天做 ``pg_dump`` 备份（``data/backups``）、还会用
``pipeline/migrate_all.py`` 整表搬运 —— 备份文件是纯文本，一次外流
等于凭据外流，且事后无法判断泄露的是哪一份。

密钥从哪来
----------
优先环境变量 ``KAOYAN_SECRET_KEY``（base64 或 hex 编码的 32 字节）。
没配时在 ``core.db_session.DATA_DIR/.secret_key`` 生成并保存一把随机
密钥（权限 0600）。自动生成是为了「空库装好就能跑」—— 部署第一步就
要求先生成密钥文件不符合本项目「无数据也要能用」的目标；但也绝不
硬编码一个默认密钥，硬编码的密钥等于没加密。

密文格式
--------
``enc:v1:<base64(nonce(12) || ciphertext || tag(16))>``。带版本前缀而
不是裸 base64，是为了两件事：

1. 读侧能区分「已加密」与「历史明文行」，明文原样返回、下次写入自动
   升级，迁移不需要停机；
2. 将来换算法或轮换密钥时可以同时读旧格式。

选 GCM 而不是 CBC：CBC 没有认证标签，密文能被静默篡改并解密出垃圾值，
而凭据被篡改的后果是「拿着一把坏 token 反复认证失败」。

解密失败一律抛 :class:`SecretDecodeError`，不回落成原值 —— 回落会让
调用方把密文当 token 发给百度，故障点从「密钥不对」漂移到「网盘报错」，
排查成本翻倍。
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import secrets
import threading
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

__all__ = [
    "SECRET_ENV_VAR",
    "SECRET_EXTRA_KEYS",
    "EncryptedText",
    "SecretDecodeError",
    "is_sealed",
    "seal",
    "unseal",
    "seal_extra",
    "unseal_extra",
    "reset_key_cache",
]

#: 主密钥的环境变量名（值为 base64 或 hex 的 32 字节）。
SECRET_ENV_VAR = "KAOYAN_SECRET_KEY"

#: 密文前缀；同时是「这行是否已加密」的判据。
PREFIX = "enc:v1:"

_NONCE_BYTES = 12

#: ``PlatformConfig.extra`` 里属于凭据的子键。整列 JSON 加密会打掉
#: ``extra->>'mode'`` 这类 PG 查询（``services/model_gateway`` 在用），
#: 所以只逐子键封装，非敏感子键保持明文可查。
SECRET_EXTRA_KEYS = ("refresh_token", "access_token", "password", "cookie", "session_token", "sessdata")


class SecretDecodeError(RuntimeError):
    """密文无法解开：密钥不匹配、内容被篡改，或前缀完整但载荷损坏。"""


# --------------------------------------------------------------------------- #
# 密钥装载
# --------------------------------------------------------------------------- #
_lock = threading.Lock()
_cached_key: Optional[bytes] = None


def _decode_raw_key(raw: str) -> bytes:
    """把 env 里的字符串解成 32 字节；base64 失败再试 hex，都不行则报错。"""
    for decoder in (base64.b64decode, binascii.unhexlify):
        try:
            key = decoder(raw)
        except (binascii.Error, ValueError):
            continue
        if len(key) == 32:
            return key
    raise ValueError(
        f"{SECRET_ENV_VAR} 必须是 base64 或 hex 编码的 32 字节密钥"
        "（生成：python -c \"import secrets;print(secrets.token_hex(32))\"）"
    )


def _key_file() -> str:
    from core.db_session import DATA_DIR

    return os.path.join(DATA_DIR, ".secret_key")


def _load_key() -> bytes:
    global _cached_key
    if _cached_key is not None:
        return _cached_key
    with _lock:
        if _cached_key is not None:
            return _cached_key
        raw = (os.environ.get(SECRET_ENV_VAR) or "").strip()
        if raw:
            _cached_key = _decode_raw_key(raw)
        else:
            _cached_key = _load_or_create_key_file()
        return _cached_key


def _load_or_create_key_file() -> bytes:
    path = _key_file()
    if os.path.exists(path):
        with open(path, "r", encoding="ascii") as handle:
            return base64.b64decode(handle.read().strip())

    os.makedirs(os.path.dirname(path), exist_ok=True)
    key = secrets.token_bytes(32)
    # O_EXCL：两个进程同时初始化时后到的那个会失败，然后读到同一把已落盘的
    # 密钥 —— 各写各的会让先写进去的行再也解不开。
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, base64.b64encode(key) + b"\n")
    finally:
        os.close(fd)
    logging.getLogger(__name__).warning(
        "%s 未配置 %s，已在 %s 生成随机密钥（0600）。多实例部署请把这一份"
        "收进环境变量，否则各实例密钥不同、互相解不开对方的行。",
        __name__, SECRET_ENV_VAR, path,
    )
    return key


def reset_key_cache() -> None:
    """丢掉内存里的主密钥 —— 换 env 后（含测试）必须调，否则继续用旧钥。"""
    global _cached_key
    with _lock:
        _cached_key = None


# --------------------------------------------------------------------------- #
# 单值封装
# --------------------------------------------------------------------------- #
def is_sealed(value: Optional[str]) -> bool:
    """该字符串是否是本模块写出的密文。"""
    return isinstance(value, str) and value.startswith(PREFIX)


def seal(plaintext: Optional[str]) -> Optional[str]:
    """加密；``None``/空串原样返回（空凭据不该产生一条密文），已加密的不重复封。"""
    if not plaintext or is_sealed(plaintext):
        return plaintext
    data = plaintext.encode("utf-8")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ct = AESGCM(_load_key()).encrypt(nonce, data, None)
    return PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def unseal(value: Optional[str]) -> Optional[str]:
    """解密；非密文（历史明文行）原样返回。"""
    if not value:
        return value
    if not is_sealed(value):
        return value
    try:
        blob = base64.b64decode(value[len(PREFIX):], validate=False)
    except (binascii.Error, ValueError) as exc:
        raise SecretDecodeError(f"{value[:16]}… 前缀完整但载荷不是合法 base64") from exc
    if len(blob) <= _NONCE_BYTES:
        raise SecretDecodeError(f"{value[:16]}… 载荷长度不足，不是合法密文")
    try:
        pt = AESGCM(_load_key()).decrypt(blob[:_NONCE_BYTES], blob[_NONCE_BYTES:], None)
    except InvalidTag as exc:
        raise SecretDecodeError(
            "凭据解密失败：主密钥与这行密文不匹配（换过 KAOYAN_SECRET_KEY、"
            "或 data/.secret_key 被重建），请用原密钥恢复后重新授权网盘"
        ) from exc
    return pt.decode("utf-8")


# --------------------------------------------------------------------------- #
# extra JSON 里的敏感子键
# --------------------------------------------------------------------------- #
def seal_extra(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """封存 extra 中的凭据子键，返回新字典（不改入参，ORM 的 JSON 列要整块赋值）。"""
    out = dict(extra or {})
    for key in SECRET_EXTRA_KEYS:
        if key in out:
            out[key] = seal(out[key])
    return out


def unseal_extra(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """解开封存的凭据子键，返回新字典。"""
    out = dict(extra or {})
    for key in SECRET_EXTRA_KEYS:
        if key in out:
            out[key] = unseal(out[key])
    return out


def scrub_extra(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """删掉凭据子键 —— 给任何要出接口的响应体用，明文密文都不许走。"""
    return {k: v for k, v in (extra or {}).items() if k not in SECRET_EXTRA_KEYS}


# --------------------------------------------------------------------------- #
# ORM 列类型：写入即加密，读出即解密
# --------------------------------------------------------------------------- #
class EncryptedText(TypeDecorator):
    """透明加解密的文本列。

    放在类型层而不是各调用点自行 ``seal``，是为了让「忘记加密」变成不可能：
    平台凭据的写入点分散在 ``main.py`` 种子、``routers/netdisk.py`` 的 PUT、
    ``services/netdisk_service.py`` 的 OAuth 回调、``routers/ai.py`` 等处，
    靠约定逐个包裹迟早漏一个。

    约束：这三列只能整体存取，不能拿密文做等值/模糊查询 —— GCM 每次加密
    都换 nonce，同一明文对应不同密文。全仓检索确认目前没有任何
    ``filter(PlatformConfig.token == ...)`` 之类的用法，新增此类查询要改走
    应用层解密后比对。
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        return seal(value) if isinstance(value, str) else value

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        return unseal(value) if isinstance(value, str) else value
