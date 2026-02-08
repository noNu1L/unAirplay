"""
FFmpeg Availability Checker
FFmpeg 可用性检查器

Checks if FFmpeg is installed and accessible in the system PATH.
检查 FFmpeg 是否已安装并可在系统 PATH 中访问。
"""
import subprocess
import shutil
import re
from typing import Optional, Tuple

from core.utils import log_info, log_warning, log_error


def get_ffmpeg_version() -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Get FFmpeg version information
    获取 FFmpeg 版本信息

    Returns:
        (is_available, version_string, version_number)
        (是否可用, 版本字符串, 版本号如 "6.0")
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return False, None, None

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            # 提取版本号，支持多种格式：
            # "ffmpeg version 6.0" -> "6.0"
            # "ffmpeg version N-122571-g4ad20a2c09" -> "N-122571"
            match = re.search(r'ffmpeg version (\S+)', version_line)
            version_num = match.group(1) if match else None
            return True, version_line, version_num
        return False, None, None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return False, None, None


def check_ffmpeg() -> Tuple[bool, Optional[str]]:
    """
    Check if FFmpeg is available in system PATH
    检查 FFmpeg 是否在系统 PATH 中可用

    Returns:
        (is_available, version_or_error)
        (是否可用, 版本号或错误信息)
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return False, "FFmpeg not found in system PATH"

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            return True, version_line
        else:
            return False, "FFmpeg found but failed to get version"
    except FileNotFoundError:
        return False, "FFmpeg not found in system PATH"
    except subprocess.TimeoutExpired:
        return False, "FFmpeg check timed out"
    except Exception as e:
        return False, f"FFmpeg check failed: {e}"


def check_ffmpeg_or_exit(tag: str = "Startup"):
    """
    Check FFmpeg availability and exit if not found
    检查 FFmpeg 可用性，如果未找到则退出程序

    Args:
        tag: Log tag / 日志标签
    """
    is_available, info = check_ffmpeg()

    if is_available:
        log_info(tag, f"FFmpeg: {info}")
        return True

    log_error(tag, f"FFmpeg check failed: {info}")
    log_error(tag, "")
    log_error(tag, "=" * 60)
    log_error(tag, "  FFmpeg is required but not found!")
    log_error(tag, "  FFmpeg 是必需的，但未找到！")
    log_error(tag, "=" * 60)
    log_error(tag, "")
    log_error(tag, "Windows:")
    log_error(tag, "  Option 1: winget install ffmpeg")
    log_error(tag, "  Option 2: Manual install")
    log_error(tag, "    1. Download from https://ffmpeg.org/download.html")
    log_error(tag, "    2. Extract to installation directory (e.g., C:\\Program Files\\ffmpeg)")
    log_error(tag, "    3. Add the bin folder to system PATH")
    log_error(tag, "       (System Properties -> Environment Variables -> Path -> New)")
    log_error(tag, "  方式1: winget install ffmpeg")
    log_error(tag, "  方式2: 手动安装")
    log_error(tag, "    1. 下载: https://ffmpeg.org/download.html")
    log_error(tag, "    2. 解压到安装目录（如: C:\\Program Files\\ffmpeg）")
    log_error(tag, "    3. 将 bin 文件夹添加到系统环境变量 PATH")
    log_error(tag, "       (系统属性 -> 环境变量 -> Path -> 新建)")
    log_error(tag, "")
    log_error(tag, "Linux: sudo apt install ffmpeg")
    log_error(tag, "macOS: brew install ffmpeg")
    log_error(tag, "")
    log_error(tag, "=" * 60)

    import sys
    sys.exit(1)


def check_ffmpeg_with_warning(tag: str = "FFmpegCheck") -> bool:
    """
    Check FFmpeg availability and show warning if not found (but don't exit)
    检查 FFmpeg 可用性，如果未找到则显示警告（但不退出）

    Args:
        tag: Log tag / 日志标签

    Returns:
        True if available, False otherwise
        如果可用返回 True，否则返回 False
    """
    is_available, info = check_ffmpeg()

    if is_available:
        log_info(tag, f"FFmpeg: {info}")
        return True
    else:
        log_warning(tag, f"FFmpeg not available: {info}")
        log_warning(tag, "Some features may not work without FFmpeg")
        return False
