"""
Audio Enhancer Base Class
"""
from abc import ABC, abstractmethod
import numpy as np

from config import SAMPLE_RATE


class BaseEnhancer(ABC):
    """Abstract base class for audio enhancers"""

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate

    @abstractmethod
    def enhance(self, audio: np.ndarray) -> np.ndarray:
        """
        Enhance audio

        Args:
            audio: shape (samples, channels), dtype float32

        Returns:
            Enhanced audio with same shape and dtype
        """
        pass

    @abstractmethod
    def set_params(self, **kwargs):
        """Set enhancement parameters"""
        pass

    @abstractmethod
    def get_params(self) -> dict:
        """Get current parameters"""
        pass
