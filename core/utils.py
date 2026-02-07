"""
Logging utilities module
"""
from datetime import datetime
import threading

# Log levels
LOG_LEVEL_DEBUG = 0
LOG_LEVEL_INFO = 1
LOG_LEVEL_WARNING = 2
LOG_LEVEL_ERROR = 3

# Current log level (configurable, will be set based on config.DEBUG)
_current_log_level = LOG_LEVEL_INFO

# Lock for atomic logging
_log_lock = threading.Lock()


def set_log_level(level: int):
    """Set the log level"""
    global _current_log_level
    _current_log_level = level


def log(tag: str, message: str, level: int = LOG_LEVEL_INFO):
    """
    Formatted log output.

    Args:
        tag: Log tag
        message: Log message
        level: Log level (LOG_LEVEL_DEBUG, LOG_LEVEL_INFO, LOG_LEVEL_WARNING, LOG_LEVEL_ERROR)
    """
    if level < _current_log_level:
        return

    now = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    level_str = {
        LOG_LEVEL_DEBUG: "DEBUG",
        LOG_LEVEL_INFO: "INFO",
        LOG_LEVEL_WARNING: "WARN",
        LOG_LEVEL_ERROR: "ERROR"
    }.get(level, "INFO")

    with _log_lock:
        print(f"[{now}] [{level_str}] [{tag}] {message}", flush=True)


def log_debug(tag: str, message: str):
    """Output DEBUG level log"""
    log(tag, message, LOG_LEVEL_DEBUG)


def log_info(tag: str, message: str):
    """Output INFO level log"""
    log(tag, message, LOG_LEVEL_INFO)


def log_warning(tag: str, message: str):
    """Output WARNING level log"""
    log(tag, message, LOG_LEVEL_WARNING)


def log_error(tag: str, message: str):
    """Output ERROR level log"""
    log(tag, message, LOG_LEVEL_ERROR)
