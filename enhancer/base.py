"""
音频增强器基类
"""
from abc import ABC, abstractmethod
import numpy as np


class BaseEnhancer(ABC):
    """音频增强器抽象基类"""

    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate

    @abstractmethod
    def enhance(self, audio: np.ndarray) -> np.ndarray:
        """
        增强音频

        参数:
            audio: shape (samples, channels), dtype float32

        返回:
            增强后的音频，同样 shape 和 dtype
        """
        pass

    @abstractmethod
    def set_params(self, **kwargs):
        """设置增强参数"""
        pass

    @abstractmethod
    def get_params(self) -> dict:
        """获取当前参数"""
        pass
