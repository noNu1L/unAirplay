"""
Dynamic Range Compression

Time-domain dynamic range compression for audio processing.
Reduces the dynamic range by attenuating signals above a threshold.
"""
import numpy as np

from core.utils import log


class DynamicCompressor:
    """
    Dynamic Range Compressor

    Reduces the dynamic range of audio by compressing signals
    that exceed a threshold. Uses time-domain processing for
    fast transient response.

    Parameters:
    - threshold: Level above which compression is applied (0.0-1.0)
    - ratio: Compression ratio (e.g., 3.0 means 3:1 compression)
    - makeup_gain: Output gain to compensate for compression
    """

    def __init__(self, threshold: float = 0.7, ratio: float = 3.0, makeup_gain: float = 1.2):
        """
        Initialize compressor

        Args:
            threshold: Compression threshold (0.0-1.0)
            ratio: Compression ratio (1.0 = no compression)
            makeup_gain: Output gain multiplier
        """
        self.threshold = threshold
        self.ratio = ratio
        self.makeup_gain = makeup_gain
        self.enabled = False

        log("DSP", "Dynamic Compressor initialized")

    def set_params(self, threshold: float = None, ratio: float = None, makeup_gain: float = None):
        """
        Set compressor parameters

        Args:
            threshold: Compression threshold (0.0-1.0)
            ratio: Compression ratio
            makeup_gain: Output gain multiplier
        """
        if threshold is not None:
            self.threshold = threshold
        if ratio is not None:
            self.ratio = ratio
        if makeup_gain is not None:
            self.makeup_gain = makeup_gain

    def set_enabled(self, enabled: bool):
        """Enable or disable compression"""
        self.enabled = enabled

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply dynamic range compression

        Args:
            audio: Input audio of shape (n_samples, channels)

        Returns:
            Compressed audio of same shape
        """
        if not self.enabled:
            return audio

        threshold = self.threshold
        ratio = self.ratio
        makeup = self.makeup_gain

        abs_audio = np.abs(audio)

        # Apply compression to samples above threshold
        compressed = np.where(
            abs_audio > threshold,
            threshold + (abs_audio - threshold) / ratio,
            abs_audio
        )

        # Restore sign and apply makeup gain
        result = np.sign(audio) * compressed * makeup

        # Clip to prevent clipping
        result = np.clip(result, -1.0, 1.0)

        return result

    def get_params(self) -> dict:
        """Get current parameters"""
        return {
            'use_compression': self.enabled,
            'compression_threshold': self.threshold,
            'compression_ratio': self.ratio,
            'compression_makeup': self.makeup_gain,
        }
