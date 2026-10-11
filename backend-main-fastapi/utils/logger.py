"""
统一日志系统
- 控制台输出 + 文件输出
- 按天滚动日志文件
- 错误日志单独文件
- 统一日志格式
"""
import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime


# 日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 日志级别
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging():
    """配置全局日志系统"""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # 清除已有处理器（避免重复）
    root_logger.handlers.clear()

    # 1. 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(console_handler)

    # 2. 常规日志文件（按天滚动，保留30天）
    info_file = os.path.join(LOG_DIR, "app.log")
    info_handler = TimedRotatingFileHandler(
        info_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    info_handler.suffix = "%Y-%m-%d"
    root_logger.addHandler(info_handler)

    # 3. 错误日志文件（仅 ERROR 及以上）
    error_file = os.path.join(LOG_DIR, "error.log")
    error_handler = TimedRotatingFileHandler(
        error_file,
        when="midnight",
        interval=1,
        backupCount=90,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    error_handler.suffix = "%Y-%m-%d"
    root_logger.addHandler(error_handler)

    # 降低第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)
    logging.getLogger("pdfplumber").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取指定名称的日志器"""
    return logging.getLogger(name)


# 便捷函数
def info(msg: str, *args, **kwargs):
    logging.info(msg, *args, **kwargs)


def warning(msg: str, *args, **kwargs):
    logging.warning(msg, *args, **kwargs)


def error(msg: str, *args, **kwargs):
    logging.error(msg, *args, **kwargs)


def debug(msg: str, *args, **kwargs):
    logging.debug(msg, *args, **kwargs)


def exception(msg: str, *args, **kwargs):
    """记录异常堆栈"""
    logging.exception(msg, *args, **kwargs)
