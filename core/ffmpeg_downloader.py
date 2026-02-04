"""
FFmpeg Audio Downloader
FFmpeg 音频下载器

Uses FFmpeg -c:a copy to quickly download audio to local cache file (no re-encoding).
Supports download-while-play scenarios.
使用 FFmpeg -c:a copy 快速下载音频到本地缓存文件（无重编码）。
支持边下载边播放的场景。
"""
import os
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional

from core.ffmpeg_utils import get_subprocess_kwargs, terminate_process
from core.utils import log_info, log_debug, log_warning, log_error


@dataclass
class DownloaderConfig:
    """
    Downloader configuration
    下载器配置
    """
    cache_dir: str                          # Cache directory / 缓存目录
    cache_filename: str                     # Cache filename (without extension) / 缓存文件名（不含扩展名）
    container_format: str = "matroska"      # Container format (matroska supports all audio codecs) / 容器格式 (matroska 支持所有音频编码)
    file_extension: str = "mkv"             # File extension / 文件扩展名


class FFmpegDownloader:
    """
    FFmpeg Audio Downloader
    FFmpeg 音频下载器

    Uses -c:a copy to quickly copy audio stream to local file without re-encoding.
    Supports download-while-read scenarios.
    使用 -c:a copy 快速复制音频流到本地文件，不重新编码。
    支持边下载边读取的场景。
    """

    def __init__(self, config: DownloaderConfig, tag: str = "FFmpegDownloader"):
        """
        Initialize downloader
        初始化下载器

        Args:
            config: Downloader configuration / 下载器配置
            tag: Log tag / 日志标签
        """
        self._config = config
        self._tag = tag
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._completed = False
        self._error: Optional[str] = None
        self._downloading = False
        self._seek_position = 0.0  # Download start position (for Seek scenarios) / 下载起始位置（用于 Seek 场景）

    @property
    def file_path(self) -> str:
        """
        Full path to cache file
        缓存文件完整路径
        """
        return os.path.join(
            self._config.cache_dir,
            f"{self._config.cache_filename}.{self._config.file_extension}"
        )

    @property
    def is_downloading(self) -> bool:
        """
        Whether downloading
        是否正在下载
        """
        return self._downloading

    @property
    def is_completed(self) -> bool:
        """
        Whether download is completed
        下载是否完成
        """
        return self._completed

    @property
    def error(self) -> Optional[str]:
        """
        Download error message
        下载错误信息
        """
        return self._error

    @property
    def seek_position(self) -> float:
        """
        Get current download start position (seconds)
        获取当前下载的起始位置（秒）
        """
        return self._seek_position

    def get_file_size(self) -> int:
        """
        Get current cache file size (bytes)
        获取当前缓存文件大小（字节）
        """
        try:
            return os.path.getsize(self.file_path) if os.path.exists(self.file_path) else 0
        except:
            return 0

    def start(self, url: str, seek_position: float = 0.0):
        """
        Start download (asynchronous, runs in background thread)
        启动下载（异步，在后台线程运行）

        Args:
            url: Audio URL / 音频 URL
            seek_position: Start position (seconds), for Seek scenarios / 起始位置（秒），用于 Seek 场景
        """
        self.stop()
        self.cleanup_file()

        self._seek_position = seek_position
        self._completed = False
        self._error = None
        self._downloading = True

        self._thread = threading.Thread(
            target=self._download_loop,
            args=(url, seek_position),
            daemon=True
        )
        self._thread.start()

    def stop(self):
        """
        Stop download
        停止下载
        """
        self._downloading = False

        terminate_process(self._process)
        self._process = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        self._thread = None

    def cleanup_file(self):
        """
        Clean up cache file
        清理缓存文件
        """
        try:
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
                log_debug(self._tag, f"Cache file cleaned: {self.file_path}")
        except Exception as e:
            log_warning(self._tag, f"Failed to cleanup cache file: {e}")

    def cleanup(self):
        """
        Stop download and clean up cache file
        停止下载并清理缓存文件
        """
        self.stop()
        self.cleanup_file()

    def _download_loop(self, url: str, seek_position: float = 0.0):
        """
        Download thread main loop
        下载线程主循环
        """
        log_info(self._tag, f"Download started" +
                 (f" (seek: {seek_position:.1f}s)" if seek_position > 0 else ""))
        log_debug(self._tag, f"URL: {url}")
        log_debug(self._tag, f"Cache file: {self.file_path}")

        cmd = ["ffmpeg", "-y"]  # Overwrite existing file / 覆盖已存在文件

        # Start download from specified position (for Seek scenarios) / 从指定位置开始下载（用于 Seek 场景）
        if seek_position > 0:
            cmd.extend(["-ss", str(seek_position)])

        cmd.extend([
            "-i", url,
            "-vn",  # No video / 无视频
            "-c:a", "copy",  # Copy audio stream (no re-encoding) / 复制音频流（不重编码）
            "-f", self._config.container_format,
            self.file_path
        ])

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **get_subprocess_kwargs()
            )

            # Wait for process to complete / 等待进程完成
            _, stderr = self._process.communicate()
            exit_code = self._process.returncode

            if not self._downloading:
                # Manually stopped / 被手动停止
                log_debug(self._tag, "Download cancelled")
                return

            if exit_code == 0:
                self._completed = True
                file_size = self.get_file_size()
                log_info(self._tag, f"Download completed: {file_size // 1024}KB")
            else:
                error_msg = stderr.decode("utf-8", errors="ignore")[:200] if stderr else "Unknown error"
                self._error = error_msg
                log_error(self._tag, f"Download failed (exit code {exit_code}): {error_msg}")

        except Exception as e:
            self._error = str(e)
            log_error(self._tag, f"Download error: {e}")

        finally:
            self._process = None
            self._downloading = False

        log_debug(self._tag, "Download thread ended")
