"""
日志配置
"""
import sys
import os
from loguru import logger
from config.settings import LOG_LEVEL, LOG_RETENTION, LOG_DIR

os.makedirs(LOG_DIR, exist_ok=True)

# 移除默认 handler
logger.remove()

# 控制台输出
logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    colorize=True,
)

# 文件日志 — 按天轮转
logger.add(
    os.path.join(LOG_DIR, "trading_{time:YYYY-MM-DD}.log"),
    level="DEBUG",
    rotation="00:00",
    retention=LOG_RETENTION,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    encoding="utf-8",
)

# 错误日志单独存储
logger.add(
    os.path.join(LOG_DIR, "error.log"),
    level="ERROR",
    rotation="10 MB",
    retention="90 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}\n{exception}",
    encoding="utf-8",
)

# 快捷导出
get_logger = logger.bind
