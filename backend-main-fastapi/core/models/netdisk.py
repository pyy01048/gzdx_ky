"""网盘相关数据模型。

对齐 core/sql/103_netdisk_four_tables.sql。
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..pg_types import JSONBObject
from .base import Base, DateTimeUTC


class ThirdPartyAccount(Base):
    """第三方网盘账号凭据（token加密存储）"""

    __tablename__ = "third_party_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="用户ID")
    provider: Mapped[str] = mapped_column(String(50), nullable=False, comment="服务商：baidu/quark/aliyun等")
    uk_provider_uid: Mapped[str] = mapped_column(String(200), nullable=False, comment="平台唯一标识")
    access_token_encrypted: Mapped[bytes | None] = mapped_column(Text, comment="AES-256-GCM加密的access_token")
    refresh_token_encrypted: Mapped[bytes | None] = mapped_column(Text, comment="AES-256-GCM加密的refresh_token")
    token_expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="token过期时间")
    account_name: Mapped[str | None] = mapped_column(String(200), comment="账号别名")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true", comment="是否启用")
    last_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTimeUTC, comment="最后同步时间")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), onupdate=func.now(), nullable=False)


class NetdiskFileCache(Base):
    """网盘文件列表缓存（短期有效，避免频繁API调用）"""

    __tablename__ = "netdisk_file_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uk_account_fs: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True, comment="uk+provider+fs_path组合键")
    file_list: Mapped[list] = mapped_column(JSONBObject, nullable=False, comment="文件列表快照")
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False, comment="过期时间")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), nullable=False)


class PreviewSession(Base):
    """文件预览会话（记录播放/阅读进度）"""

    __tablename__ = "preview_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="用户ID")
    file_id: Mapped[str] = mapped_column(String(200), nullable=False, comment="文件唯一标识")
    play_position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="播放位置（秒）")
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", comment="阅读进度百分比")
    page_number: Mapped[int | None] = mapped_column(Integer, comment="PDF当前页码")
    session_expires_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, nullable=False, comment="会话过期时间")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), onupdate=func.now(), nullable=False)


class NetdiskOperationLog(Base):
    """网盘操作审计日志"""

    __tablename__ = "netdisk_operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="用户ID")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作名：netdisk.bind/unbind/preview等")
    provider: Mapped[str | None] = mapped_column(String(50), comment="服务商")
    resource_id: Mapped[str | None] = mapped_column(String(200), comment="涉及的文件ID或账号ID")
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="状态：success/failure")
    error_code: Mapped[str | None] = mapped_column(String(20), comment="错误码")
    error_message: Mapped[str | None] = mapped_column(Text, comment="错误详情")
    ip_address: Mapped[str | None] = mapped_column(String(50), comment="客户端IP")
    extra_metadata: Mapped[dict | None] = mapped_column(JSONBObject, comment="额外上下文")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTimeUTC, server_default=func.now(), nullable=False)


__all__ = ["ThirdPartyAccount", "NetdiskFileCache", "PreviewSession", "NetdiskOperationLog"]
