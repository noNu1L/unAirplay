"""
IIR Mode Equalizer & Tone Processor

Infinite Impulse Response
IIR 模式均衡器与音调处理器

Features:
- 10-band Graphic EQ using Biquad (Peaking) filters
- Spectral Enhancement using Shelf filters (Low-Shelf + High-Shelf)
- Stateful processing for streaming audio
- Zero latency (no buffering)
- High performance using scipy.signal.sosfilt (C implementation)
- Glitch-free parameter changes (fixed filter chain with soft bypass)

Architecture:
- Fixed SOS chain: 10 EQ bands + 2 Shelf filters = 12 sections (always)
- Soft bypass: 0dB filters use identity SOS [1,0,0,1,0,0]
- State preservation: zi is never reset on parameter changes
- Single sosfilt call for maximum efficiency

Based on Robert Bristow-Johnson's Audio EQ Cookbook
"""
import numpy as np
from scipy.signal import sosfilt

from core.utils import log
from config import SAMPLE_RATE

# 10-band equalizer frequencies (Hz)
EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

# Total number of filter sections (fixed)
# 10 EQ bands + 1 Low-Shelf + 1 High-Shelf = 12
N_SECTIONS = len(EQ_BANDS) + 2

# Identity SOS (unity gain, no filtering): [b0, b1, b2, a0, a1, a2]
IDENTITY_SOS = np.array([1.0, 0.0, 0.0, 1.0, 0.0, 0.0])


def design_peaking_filter(freq: float, gain_db: float, q: float, sample_rate: int):
    """
    Design Peaking EQ filter using RBJ Audio EQ Cookbook

    Args:
        freq: Center frequency (Hz)
        gain_db: Gain in dB (positive = boost, negative = cut)
        q: Q factor (bandwidth)
        sample_rate: Sample rate

    Returns:
        SOS coefficients [b0, b1, b2, 1, a1, a2]
    """
    if abs(gain_db) < 0.01:
        return IDENTITY_SOS.copy()

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

    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0])


def design_low_shelf(freq: float, gain_db: float, q: float, sample_rate: int):
    """
    Design Low-Shelf filter using RBJ Audio EQ Cookbook

    Args:
        freq: Center frequency (Hz)
        gain_db: Gain in dB
        q: Q factor (typically 0.707)
        sample_rate: Sample rate

    Returns:
        SOS coefficients [b0, b1, b2, 1, a1, a2]
    """
    if abs(gain_db) < 0.01:
        return IDENTITY_SOS.copy()

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

    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0])


def design_high_shelf(freq: float, gain_db: float, q: float, sample_rate: int):
    """
    Design High-Shelf filter using RBJ Audio EQ Cookbook

    Args:
        freq: Center frequency (Hz)
        gain_db: Gain in dB
        q: Q factor (typically 0.707)
        sample_rate: Sample rate

    Returns:
        SOS coefficients [b0, b1, b2, 1, a1, a2]
    """
    if abs(gain_db) < 0.01:
        return IDENTITY_SOS.copy()

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

    return np.array([b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0])


class EqualizerToneIIR:
    """
    IIR Mode Equalizer & Tone Processor

    Combines 10-band graphic EQ with spectral enhancement (Low/High Shelf).
    All processing uses IIR (Biquad) filters via scipy.signal.sosfilt.

    Processing chain (fixed 12 sections):
    Input -> [10x EQ + Low-Shelf + High-Shelf] -> Output

    Features:
    - Fixed filter chain size (12 sections) - no dimension changes
    - Soft bypass using identity SOS [1,0,0,1,0,0] for 0dB bands
    - State preservation on parameter changes - no pops/clicks
    - scipy C implementation for ~10-50x speedup
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

        # Fixed SOS array: always 12 sections (10 EQ + 2 Shelf)
        # Shape: (N_SECTIONS, 6)
        self._sos = np.tile(IDENTITY_SOS, (N_SECTIONS, 1))

        # Filter state: shape (channels, N_SECTIONS, 2)
        # NEVER reset on parameter changes to avoid pops/clicks
        self._zi = np.zeros((channels, N_SECTIONS, 2))

        # Flag to update SOS coefficients
        self._needs_update = True

        log("DSP", f"EqualizerToneIIR initialized (scipy.sosfilt, fixed {N_SECTIONS} sections)")

    def _update_sos(self):
        """Update SOS coefficients without resetting state"""
        # EQ bands (sections 0-9)
        for i, freq in enumerate(EQ_BANDS):
            if self.eq_enabled and self.eq_gains[freq] != 0:
                self._sos[i] = design_peaking_filter(
                    freq, self.eq_gains[freq], self.eq_q, self.sample_rate
                )
            else:
                self._sos[i] = IDENTITY_SOS.copy()

        # Low-Shelf (section 10)
        if self.spectral_enabled and self.bass_gain != 1.0:
            bass_db = self._gain_to_db(self.bass_gain)
            self._sos[10] = design_low_shelf(
                self.low_shelf_freq, bass_db, self.shelf_q, self.sample_rate
            )
        else:
            self._sos[10] = IDENTITY_SOS.copy()

        # High-Shelf (section 11)
        if self.spectral_enabled and self.treble_gain != 1.0:
            treble_db = self._gain_to_db(self.treble_gain)
            self._sos[11] = design_high_shelf(
                self.high_shelf_freq, treble_db, self.shelf_q, self.sample_rate
            )
        else:
            self._sos[11] = IDENTITY_SOS.copy()

        self._needs_update = False

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
                    self._needs_update = True

    def set_spectral_gains(self, bass_gain: float = None, treble_gain: float = None):
        """
        Set spectral gains

        Args:
            bass_gain: Low frequency gain (0.5-2.0, linear)
            treble_gain: High frequency gain (0.5-2.0, linear)
        """
        if bass_gain is not None and bass_gain != self.bass_gain:
            self.bass_gain = bass_gain
            self._needs_update = True

        if treble_gain is not None and treble_gain != self.treble_gain:
            self.treble_gain = treble_gain
            self._needs_update = True

    def _gain_to_db(self, gain: float) -> float:
        """Convert linear gain to dB"""
        if gain <= 0:
            return -60.0
        return 20.0 * np.log10(gain)

    def set_enabled(self, eq_enabled: bool = None, spectral_enabled: bool = None):
        """Set enable flags"""
        if eq_enabled is not None and eq_enabled != self.eq_enabled:
            self.eq_enabled = eq_enabled
            self._needs_update = True
        if spectral_enabled is not None and spectral_enabled != self.spectral_enabled:
            self.spectral_enabled = spectral_enabled
            self._needs_update = True

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Process audio through IIR filter chain

        Args:
            audio: Input audio of shape (n_samples, channels)

        Returns:
            Processed audio of same shape
        """
        # Update SOS coefficients if parameters changed (state preserved)
        if self._needs_update:
            self._update_sos()

        result = np.zeros_like(audio, dtype=np.float64)
        n_channels = min(audio.shape[1], self.channels)

        for ch in range(n_channels):
            # sosfilt returns (output, final_state)
            result[:, ch], self._zi[ch] = sosfilt(
                self._sos,
                audio[:, ch].astype(np.float64),
                zi=self._zi[ch]
            )

        return result.astype(np.float32)

    def reset(self):
        """Reset all filter states (use sparingly - causes click)"""
        self._zi.fill(0.0)
        self._needs_update = True

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
