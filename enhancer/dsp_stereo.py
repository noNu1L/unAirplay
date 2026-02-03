"""
Stereo Enhancement using Mid-Side Processing

Time-domain stereo width enhancement using Mid-Side (M/S) processing.
Adjusts the stereo width by manipulating the side (difference) signal.
"""
import numpy as np

from core.utils import log


class StereoEnhancer:
    """
    Stereo Width Enhancer using Mid-Side Processing

    Enhances stereo width by adjusting the balance between
    mid (center) and side (stereo difference) signals.

    Mid = (L + R) / 2  (center content: vocals, bass)
    Side = (L - R) / 2 (stereo content: ambience, width)

    Increasing side signal relative to mid increases stereo width.
    """

    def __init__(self, width: float = 1.0):
        """
        Initialize stereo enhancer

        Args:
            width: Stereo width multiplier (1.0 = original, >1.0 = wider, <1.0 = narrower)
        """
        self.width = width
        self.enabled = False

        log("DSP", "Stereo Enhancer initialized")

    def set_width(self, width: float):
        """
        Set stereo width

        Args:
            width: Stereo width multiplier
                   - 0.0 = mono (no stereo)
                   - 1.0 = original stereo width
                   - >1.0 = enhanced stereo width
        """
        self.width = width

    def set_enabled(self, enabled: bool):
        """Enable or disable stereo enhancement"""
        self.enabled = enabled

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Apply stereo enhancement

        Args:
            audio: Input audio of shape (n_samples, 2) - must be stereo

        Returns:
            Enhanced audio of same shape
        """
        if not self.enabled:
            return audio

        # Only process stereo audio
        if audio.ndim != 2 or audio.shape[1] != 2:
            return audio

        width = self.width

        # Mid-Side encoding
        mid = (audio[:, 0] + audio[:, 1]) / 2   # Center signal
        side = (audio[:, 0] - audio[:, 1]) / 2  # Stereo difference

        # Adjust stereo width
        side = side * width

        # Mid-Side decoding
        enhanced = np.zeros_like(audio)
        enhanced[:, 0] = mid + side  # Left = Mid + Side
        enhanced[:, 1] = mid - side  # Right = Mid - Side

        # Clip to prevent clipping
        enhanced = np.clip(enhanced, -1.0, 1.0)

        return enhanced

    def get_params(self) -> dict:
        """Get current parameters"""
        return {
            'use_stereo': self.enabled,
            'stereo_width': self.width,
        }
