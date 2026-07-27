
import logging
import os

from utils.path_tool import get_abs_path
from datetime import datetime

# 日志保存的根目录
LOG_ROOT = get_abs_path("logs")

# 检查日志文件是否存在
os.makedirs(LOG_ROOT, exist_ok=True)

# 配置日志格式
DEFAULT_LOG_FORMAT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s:%(filename)s:%(lineno)d:%(funcName)s - %(message)s"
)

def get_logger(
        name: str = "agent",
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        log_file = None
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 避免重复添加Handler
    if logger.handlers:
        return logger

    # 控制台Handler
    console_handle = logging.StreamHandler()
    console_handle.setLevel(console_level)
    console_handle.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(console_handle)

    # 文件Handler
    if not log_file:
        log_file = os.path.join(LOG_ROOT, f"{name}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(DEFAULT_LOG_FORMAT)

    logger.addHandler(file_handler)

    return logger

# 快捷获取日志器
logger = get_logger()

"""
之后可直接导入logger变量，即可使用
"""

if __name__ == '__main__':
    logger.info("信息日志")
    logger.error("错误日志")
    logger.warning("警告日志")
    logger.debug("调试日志")
