"""
FFmpeg PCM Decoder
FFmpeg PCM 解码器

Decodes audio files/URLs to PCM stream output.
Supports both S16LE (AirPlay) and F32LE (ServerSpeaker) formats.
将音频文件/URL 解码为 PCM 流输出。
支持 S16LE (AirPlay) 和 F32LE (ServerSpeaker) 两种格式。
"""
import subprocess
from dataclasses import dataclass
from typing import Optional

from config import SAMPLE_RATE, CHANNELS

from core.ffmpeg_utils import PCMFormat, get_subprocess_kwargs, terminate_process
from core.utils import log_info, log_debug, log_error


@dataclass
class DecoderConfig:
    """
    Decoder configuration
    解码器配置
    """
    sample_rate: int = SAMPLE_RATE                    # Sample rate / 采样率
    channels: int = CHANNELS                          # Number of channels / 声道数
    pcm_format: PCMFormat = PCMFormat.F32LE           # PCM output format / PCM 输出格式
    realtime: bool = False                            # -re realtime playback rate / -re 实时播放速率
    seek_position: float = 0.0                        # -ss start position (seconds) / -ss 起始位置（秒）
    buffer_size: int = 0                              # subprocess bufsize (0=default) / subprocess bufsize (0=默认)
    quiet: bool = True                                # Quiet mode (hide banner and logs) / 静默模式（隐藏 banner 和日志）


class FFmpegDecoder:
    """
    FFmpeg PCM Decoder
    FFmpeg PCM 解码器

    Starts FFmpeg process to decode input source to PCM stream output to stdout.
    启动 FFmpeg 进程，将输入源解码为 PCM 流输出到 stdout。
    """

    def __init__(self, config: DecoderConfig, tag: str = "FFmpegDecoder"):
        """
        Initialize decoder
        初始化解码器

        Args:
            config: Decoder configuration / 解码器配置
            tag: Log tag / 日志标签
        """
        self._config = config
        self._tag = tag
        self._process: Optional[subprocess.Popen] = None
        self._started = False

    @property
    def process(self) -> Optional[subprocess.Popen]:
        """
        FFmpeg process
        FFmpeg 进程
        """
        return self._process

    @property
    def stdout(self):
        """
        FFmpeg stdout stream
        FFmpeg stdout 流
        """
        return self._process.stdout if self._process else None

    @property
    def is_running(self) -> bool:
        """
        Whether decoder is running
        解码器是否正在运行
        """
        return self._process is not None and self._process.poll() is None

    @property
    def bytes_per_frame(self) -> int:
        """
        Bytes per frame (channels * bytes_per_sample)
        每帧字节数 (channels * bytes_per_sample)
        """
        return self._config.channels * self._config.pcm_format.bytes_per_sample

    def start(self, input_source: str) -> subprocess.Popen:
        """
        Start decoder
        启动解码器

        Args:
            input_source: Input source (file path or URL) / 输入源（文件路径或 URL）

        Returns:
            FFmpeg process object / FFmpeg 进程对象
        """
        if self._started:
            return self._process

        cmd = ["ffmpeg"]

        # Quiet mode / 静默模式
        if self._config.quiet:
            cmd.extend(["-hide_banner", "-loglevel", "error"])

        # Seek position / Seek 位置
        if self._config.seek_position > 0:
            cmd.extend(["-ss", str(self._config.seek_position)])

        # Realtime playback rate / 实时播放速率
        if self._config.realtime:
            cmd.append("-re")

        # Input and output settings / 输入和输出设置
        cmd.extend([
            "-i", input_source,
            "-vn",  # No video / 无视频
            "-acodec", self._config.pcm_format.codec,
            "-ar", str(self._config.sample_rate),
            "-ac", str(self._config.channels),
            "-f", self._config.pcm_format.format,
            "pipe:1"  # Output to stdout / 输出到 stdout
        ])

        log_debug(self._tag, f"Starting decoder: {self._config.pcm_format.name}, "
                 f"rate={self._config.sample_rate}, channels={self._config.channels}" +
                 (f", seek={self._config.seek_position}s" if self._config.seek_position > 0 else "") +
                 (", realtime" if self._config.realtime else ""))
        log_debug(self._tag, f"Input: {input_source}")

        try:
            kwargs = get_subprocess_kwargs()
            if self._config.buffer_size > 0:
                kwargs["bufsize"] = self._config.buffer_size

            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **kwargs
            )
            self._started = True

        except Exception as e:
            log_error(self._tag, f"Failed to start decoder: {e}")
            self._process = None

        return self._process

    def stop(self):
        """
        Stop decoder
        停止解码器
        """
        terminate_process(self._process)
        self._process = None
        self._started = False

    def read(self, size: int) -> bytes:
        """
        Read PCM data from decoder
        从解码器读取 PCM 数据

        Args:
            size: Number of bytes to read / 要读取的字节数

        Returns:
            PCM data, or empty bytes if EOF or error / PCM 数据，如果 EOF 或错误则返回空 bytes
        """
        if not self._process or not self._process.stdout:
            return b""
        try:
            return self._process.stdout.read(size)
        except:
            return b""
