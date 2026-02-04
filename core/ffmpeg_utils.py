"""
FFmpeg Common Utilities
FFmpeg 公共工具

Provides PCM format definitions and process management utility functions.
提供 PCM 格式定义和进程管理工具函数。
"""
import subprocess
import sys
from enum import Enum
from typing import Dict, Any, Optional


class PCMFormat(Enum):
    """
    PCM output format
    PCM 输出格式
    """
    S16LE = ("pcm_s16le", "s16le", 2, "int16")    # 16-bit signed (AirPlay)
    F32LE = ("pcm_f32le", "f32le", 4, "float32")  # 32-bit float (ServerSpeaker)

    @property
    def codec(self) -> str:
        """
        FFmpeg codec name
        FFmpeg codec 名称
        """
        return self.value[0]

    @property
    def format(self) -> str:
        """
        FFmpeg output format
        FFmpeg 输出格式
        """
        return self.value[1]

    @property
    def bytes_per_sample(self) -> int:
        """
        Bytes per sample
        每个采样的字节数
        """
        return self.value[2]

    @property
    def numpy_dtype(self) -> str:
        """
        Corresponding numpy dtype
        对应的 numpy dtype
        """
        return self.value[3]


def get_subprocess_kwargs() -> Dict[str, Any]:
    """
    Get platform-specific subprocess parameters
    获取平台相关的 subprocess 参数
    """
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def terminate_process(process: Optional[subprocess.Popen], timeout: float = 2.0):
    """
    Safely terminate a process
    安全终止进程
    """
    if not process:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except:
        try:
            process.kill()
        except:
            pass
