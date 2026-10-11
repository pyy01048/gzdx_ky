"""
数据库自动备份服务 V3.0
每天自动备份，保留最近7天，支持在线备份（不需要停服务）
"""
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from database import BASE_DIR

BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
DB_PATH = os.path.join(BASE_DIR, "data", "kaoyan.db")
MAX_BACKUPS = 7  # 保留最近7天


def ensure_backup_dir():
    """确保备份目录存在"""
    os.makedirs(BACKUP_DIR, exist_ok=True)


def create_backup() -> str:
    """
    创建数据库备份（使用 SQLite .backup 在线备份，不需要停服务）
    返回备份文件路径
    """
    ensure_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"kaoyan_{timestamp}.db")

    try:
        # 使用 SQLite 在线备份（支持 WAL 模式，不需要停服务）
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        src.close()

        # 清理旧备份
        cleanup_old_backups()

        size = os.path.getsize(backup_path)
        print(f"[backup] 数据库备份成功: {backup_path} ({size / 1024 / 1024:.2f} MB)")
        return backup_path
    except Exception as e:
        print(f"[backup] 数据库备份失败: {e}")
        # 降级方案：直接复制文件
        try:
            shutil.copy2(DB_PATH, backup_path)
            cleanup_old_backups()
            print(f"[backup] 降级备份成功（直接复制）: {backup_path}")
            return backup_path
        except Exception as e2:
            print(f"[backup] 降级备份也失败: {e2}")
            return None


def cleanup_old_backups():
    """清理超过 MAX_BACKUPS 个的旧备份"""
    backups = sorted(Path(BACKUP_DIR).glob("kaoyan_*.db"))
    if len(backups) > MAX_BACKUPS:
        old_backups = backups[:-MAX_BACKUPS]
        for old in old_backups:
            try:
                old.unlink()
                print(f"[backup] 清理旧备份: {old}")
            except Exception as e:
                print(f"[backup] 清理旧备份失败: {old}, {e}")


def list_backups() -> list:
    """列出所有备份"""
    ensure_backup_dir()
    backups = []
    for f in sorted(Path(BACKUP_DIR).glob("kaoyan_*.db"), reverse=True):
        stat = f.stat()
        backups.append({
            "name": f.name,
            "path": str(f),
            "size": stat.st_size,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return backups


def restore_backup(backup_path: str) -> bool:
    """
    从备份恢复数据库
    注意：恢复前会自动创建当前数据库的备份
    """
    if not os.path.exists(backup_path):
        print(f"[backup] 备份文件不存在: {backup_path}")
        return False

    try:
        # 先备份当前数据库
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_restore_path = os.path.join(BACKUP_DIR, f"pre_restore_{timestamp}.db")
        shutil.copy2(DB_PATH, pre_restore_path)
        print(f"[backup] 恢复前已备份当前数据库: {pre_restore_path}")

        # 恢复备份
        shutil.copy2(backup_path, DB_PATH)
        print(f"[backup] 数据库恢复成功: {backup_path}")
        return True
    except Exception as e:
        print(f"[backup] 数据库恢复失败: {e}")
        return False


def should_backup_today() -> bool:
    """判断今天是否已经备份过"""
    ensure_backup_dir()
    today = datetime.now().strftime("%Y%m%d")
    for f in Path(BACKUP_DIR).glob("kaoyan_*.db"):
        if today in f.name:
            return False
    return True


def daily_backup_if_needed():
    """如果今天还没备份，则创建备份"""
    if should_backup_today():
        return create_backup()
    return None
