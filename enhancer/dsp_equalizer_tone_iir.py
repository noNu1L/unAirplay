"""
IIR Mode Equalizer & Tone Processor

Infinite Impulse Response
IIR 模式均衡器与音调处理器

Features:
- 10-band Graphic EQ using Biquad (Peaking) filters
- Spectral Enhancement using Shelf filters (Low-Shelf + High-Shelf)
- Stateful processing for streaming audio
- Zero latency (no buffering)

Architecture:
- Serial processing: Input -> EQ Bands -> Low-Shelf -> High-Shelf -> Output
- Direct Form II Transposed for numerical stability
- State preservation across audio blocks

Based on Robert Bristow-Johnson's Audio EQ Cookbook
"""
import numpy as np

from core.utils import log
from config import SAMPLE_RATE

# 10-band equalizer frequencies (Hz)
EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def design_peaking_filter(freq: float, gain_db: float, q: float, sample_rate: int):
    """
    Design Peaking EQ filter using RBJ Audio EQ Cookbook

    Args:
        freq: Center frequency (Hz)
        gain_db: Gain in dB (positive = boost, negative = cut)
        q: Q factor (bandwidth)
        sample_rate: Sample rate

    Returns:
        (b, a) coefficients or None if gain_db is 0
    """
    if abs(gain_db) < 0.01:
        return None

    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sample_rate
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / (2 * q)

    b0 = 1 + alpha * A
    b1 = -2 * cos_w0
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * cos_w0
    a2 = 1 - alpha / A

    b = np.array([b0 / a0, b1 / a0, b2 / a0])
    a = np.array([1.0, a1 / a0, a2 / a0])

    return b, a


def design_low_shelf(freq: float, gain_db: float, q: float, sample_rate: int):
    """
    Design Low-Shelf filter using RBJ Audio EQ Cookbook

    Args:
        freq: Center frequency (Hz)
        gain_db: Gain in dB
        q: Q factor (typically 0.707)
        sample_rate: Sample rate

    Returns:
        (b, a) coefficients or None if gain_db is 0
    """
    if abs(gain_db) < 0.01:
        return None

    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sample_rate
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / (2 * q)

    sqrt_A = np.sqrt(A)
    sqrt_A_alpha_2 = 2 * sqrt_A * alpha

    b0 = A * ((A + 1) - (A - 1) * cos_w0 + sqrt_A_alpha_2)
    b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
    b2 = A * ((A + 1) - (A - 1) * cos_w0 - sqrt_A_alpha_2)
    a0 = (A + 1) + (A - 1) * cos_w0 + sqrt_A_alpha_2
    a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
    a2 = (A + 1) + (A - 1) * cos_w0 - sqrt_A_alpha_2

    b = np.array([b0 / a0, b1 / a0, b2 / a0])
    a = np.array([1.0, a1 / a0, a2 / a0])

    return b, a


def design_high_shelf(freq: float, gain_db: float, q: float, sample_rate: int):
    """
    Design High-Shelf filter using RBJ Audio EQ Cookbook

    Args:
        freq: Center frequency (Hz)
        gain_db: Gain in dB
        q: Q factor (typically 0.707)
        sample_rate: Sample rate

    Returns:
        (b, a) coefficients or None if gain_db is 0
    """
    if abs(gain_db) < 0.01:
        return None

    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sample_rate
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / (2 * q)

    sqrt_A = np.sqrt(A)
    sqrt_A_alpha_2 = 2 * sqrt_A * alpha

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + sqrt_A_alpha_2)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - sqrt_A_alpha_2)
    a0 = (A + 1) - (A - 1) * cos_w0 + sqrt_A_alpha_2
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - sqrt_A_alpha_2

    b = np.array([b0 / a0, b1 / a0, b2 / a0])
    a = np.array([1.0, a1 / a0, a2 / a0])

    return b, a


class StatefulBiquad:
    """
    Stateful Biquad filter for streaming audio

    Uses Direct Form II Transposed structure.
    Maintains state across audio blocks.
    """

    def __init__(self, b=None, a=None, channels: int = 2):
        """
        Initialize biquad filter

        Args:
            b: Numerator coefficients [b0, b1, b2] or None for bypass
            a: Denominator coefficients [1.0, a1, a2] or None for bypass
            channels: Number of audio channels
        """
        self.channels = channels
        self.bypass = (b is None or a is None)

        if not self.bypass:
            self.b0, self.b1, self.b2 = float(b[0]), float(b[1]), float(b[2])
            self.a1, self.a2 = float(a[1]), float(a[2])
        else:
            self.b0, self.b1, self.b2 = 1.0, 0.0, 0.0
            self.a1, self.a2 = 0.0, 0.0

        # State variables for each channel
        self._state = np.zeros((channels, 2), dtype=np.float64)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Process audio through the filter

        Args:
            audio: Input audio of shape (n_samples, channels)

        Returns:
            Filtered audio of same shape
        """
        if self.bypass:
            return audio

        result = np.zeros_like(audio, dtype=np.float64)
        for ch in range(min(audio.shape[1], self.channels)):
            result[:, ch] = self._process_channel(audio[:, ch], ch)
        return result.astype(audio.dtype)

    def _process_channel(self, x: np.ndarray, ch: int) -> np.ndarray:
        """Process single channel with state preservation"""
        n = len(x)
        y = np.zeros(n, dtype=np.float64)

        z1, z2 = self._state[ch]
        b0, b1, b2 = self.b0, self.b1, self.b2
        a1, a2 = self.a1, self.a2

        for i in range(n):
            xi = float(x[i])
            yi = b0 * xi + z1
            z1 = b1 * xi - a1 * yi + z2
            z2 = b2 * xi - a2 * yi
            y[i] = yi

        self._state[ch, 0] = z1
        self._state[ch, 1] = z2

        return y

    def update_coefficients(self, b, a):
        """Update filter coefficients (state preserved)"""
        if b is None or a is None:
            self.bypass = True
        else:
            self.bypass = False
            self.b0, self.b1, self.b2 = float(b[0]), float(b[1]), float(b[2])
            self.a1, self.a2 = float(a[1]), float(a[2])

    def reset(self):
        """Reset filter state"""
        self._state.fill(0.0)


class EqualizerToneIIR:
    """
    IIR Mode Equalizer & Tone Processor

    Combines 10-band graphic EQ with spectral enhancement (Low/High Shelf).
    All processing uses IIR (Biquad) filters.

    Processing chain (serial):
    Input -> 10x Peaking EQ -> Low-Shelf -> High-Shelf -> Output

    TODO: IIR 模式可以使用引入 scipy进行性能优化，但是包比较大
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = 2):
        """
        Initialize IIR processor

        Args:
            sample_rate: Audio sample rate
            channels: Number of audio channels
        """
        self.sample_rate = sample_rate
        self.channels = channels

        # Enable flags
        self.eq_enabled = True
        self.spectral_enabled = True

        # EQ parameters
        self.eq_gains = {freq: 0.0 for freq in EQ_BANDS}  # dB
        self.eq_q = 1.4  # Q factor for peaking filters

        # Spectral parameters
        self.low_shelf_freq = 150  # Hz
        self.high_shelf_freq = 8000  # Hz
        self.shelf_q = 0.707  # Butterworth-like Q
        self.bass_gain = 1.0  # Linear gain (0.5-2.0)
        self.treble_gain = 1.0  # Linear gain (0.5-2.0)

        # EQ filters (10 bands)
        self._eq_filters = {}
        for freq in EQ_BANDS:
            self._eq_filters[freq] = StatefulBiquad(channels=channels)

        # Shelf filters
        self._low_shelf = StatefulBiquad(channels=channels)
        self._high_shelf = StatefulBiquad(channels=channels)

        # Current dB values for shelf filters (for change detection)
        self._current_bass_db = 0.0
        self._current_treble_db = 0.0

        log("DSP", f"EqualizerToneIIR initialized: {len(EQ_BANDS)} EQ bands + 2 Shelf filters")

    def set_eq_gains(self, **kwargs):
        """
        Set EQ band gains

        Args:
            eq_31, eq_62, ..., eq_16000: Gain in dB for each band
        """
        for freq in EQ_BANDS:
            key = f'eq_{freq}'
            if key in kwargs:
                new_gain = kwargs[key]
                if new_gain != self.eq_gains[freq]:
                    self.eq_gains[freq] = new_gain
                    self._update_eq_filter(freq, new_gain)

    def _update_eq_filter(self, freq: int, gain_db: float):
        """Update a single EQ filter's coefficients"""
        result = design_peaking_filter(freq, gain_db, self.eq_q, self.sample_rate)
        if result:
            b, a = result
            self._eq_filters[freq].update_coefficients(b, a)
        else:
            self._eq_filters[freq].update_coefficients(None, None)

    def set_spectral_gains(self, bass_gain: float = None, treble_gain: float = None):
        """
        Set spectral gains

        Args:
            bass_gain: Low frequency gain (0.5-2.0, linear)
            treble_gain: High frequency gain (0.5-2.0, linear)
        """
        if bass_gain is not None:
            self.bass_gain = bass_gain
            bass_db = self._gain_to_db(bass_gain)
            if abs(bass_db - self._current_bass_db) > 0.1:
                self._current_bass_db = bass_db
                result = design_low_shelf(self.low_shelf_freq, bass_db, self.shelf_q, self.sample_rate)
                if result:
                    self._low_shelf.update_coefficients(*result)
                else:
                    self._low_shelf.update_coefficients(None, None)

        if treble_gain is not None:
            self.treble_gain = treble_gain
            treble_db = self._gain_to_db(treble_gain)
            if abs(treble_db - self._current_treble_db) > 0.1:
                self._current_treble_db = treble_db
                result = design_high_shelf(self.high_shelf_freq, treble_db, self.shelf_q, self.sample_rate)
                if result:
                    self._high_shelf.update_coefficients(*result)
                else:
                    self._high_shelf.update_coefficients(None, None)

    def _gain_to_db(self, gain: float) -> float:
        """Convert linear gain to dB"""
        if gain <= 0:
            return -60.0
        return 20.0 * np.log10(gain)

    def set_enabled(self, eq_enabled: bool = None, spectral_enabled: bool = None):
        """Set enable flags"""
        if eq_enabled is not None:
            self.eq_enabled = eq_enabled
        if spectral_enabled is not None:
            self.spectral_enabled = spectral_enabled

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Process audio through IIR filter chain

        Args:
            audio: Input audio of shape (n_samples, channels)

        Returns:
            Processed audio of same shape
        """
        result = audio.astype(np.float64)

        # 1. Apply 10-band EQ
        if self.eq_enabled:
            for freq in EQ_BANDS:
                if self.eq_gains[freq] != 0:
                    result = self._eq_filters[freq].process(result)

        # 2. Apply Spectral (Shelf filters)
        if self.spectral_enabled:
            # Low-Shelf
            if self.bass_gain != 1.0:
                result = self._low_shelf.process(result)
            # High-Shelf
            if self.treble_gain != 1.0:
                result = self._high_shelf.process(result)

        return result.astype(np.float32)

    def reset(self):
        """Reset all filter states"""
        for filt in self._eq_filters.values():
            filt.reset()
        self._low_shelf.reset()
        self._high_shelf.reset()

    def get_params(self) -> dict:
        """Get current parameters"""
        params = {
            'eq_enabled': self.eq_enabled,
            'spectral_enabled': self.spectral_enabled,
            'lowfreq_gain': self.bass_gain,
            'highfreq_gain': self.treble_gain,
        }
        for freq in EQ_BANDS:
            params[f'eq_{freq}'] = self.eq_gains[freq]
        return params
