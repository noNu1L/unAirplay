"""
FIR Mode Equalizer & Tone Processor

FIR 模式均衡器与音调处理器

Features:
- 10-band Graphic EQ using FIR filter
- Spectral Enhancement (Low/High Freq Gain) using FIR filter
- Combined frequency response: H_total = H_EQ × H_Spectral
- Single FIR filter for efficiency
- Linear phase (no phase distortion)
- Stateful processing for streaming

Architecture:
- Frequency sampling method for FIR design
- Overlap-Save convolution for streaming
- Filter redesign on parameter change

"""
import numpy as np
from numpy.fft import rfft, irfft

from core.utils import log
from config import SAMPLE_RATE

# 10-band equalizer frequencies (Hz)
EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

# FIR Configuration
FIR_NUMTAPS = 1025  # Odd number for Type I linear phase


class EqualizerToneFIR:
    """
    FIR Mode Equalizer & Tone Processor

    Combines 10-band graphic EQ with spectral enhancement using a single FIR filter.
    Uses frequency sampling method to design the filter.

    Processing:
    1. Build combined frequency response (EQ × Spectral)
    2. Design FIR filter via IFFT
    3. Apply filter using overlap-save convolution

    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = 2,
                 numtaps: int = FIR_NUMTAPS):
        """
        Initialize FIR processor

        Args:
            sample_rate: Audio sample rate
            channels: Number of audio channels
            numtaps: FIR filter length (odd number for Type I)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.numtaps = numtaps if numtaps % 2 == 1 else numtaps + 1
        self.nyquist = sample_rate / 2

        # Enable flags
        self.eq_enabled = True
        self.spectral_enabled = True

        # EQ parameters
        self.eq_gains = {freq: 0.0 for freq in EQ_BANDS}  # dB

        # Spectral parameters
        self.bass_gain = 1.0  # Linear gain (0.5-2.0)
        self.treble_gain = 1.0  # Linear gain (0.5-2.0)
        self.bass_freq = 150  # Hz
        self.bass_trans_end = 300  # Hz
        self.treble_trans_start = 4000  # Hz
        self.treble_freq = 8000  # Hz

        # Parameter smoothing
        self._smooth_alpha = 0.3
        self._current_bass_gain = 1.0
        self._current_treble_gain = 1.0
        self._target_bass_gain = 1.0
        self._target_treble_gain = 1.0

        # FIR filter
        self._filter = None
        self._design_filter()

        # State buffers for overlap-save
        self._state = [np.zeros(self.numtaps - 1) for _ in range(channels)]

        log("DSP", f"EqualizerToneFIR initialized: {self.numtaps} taps")

    def _build_eq_response(self, n_freqs: int) -> np.ndarray:
        """
        Build EQ frequency response

        Args:
            n_freqs: Number of frequency points

        Returns:
            EQ response (linear scale)
        """
        if not self.eq_enabled:
            return np.ones(n_freqs)

        if all(g == 0 for g in self.eq_gains.values()):
            return np.ones(n_freqs)

        freqs = np.linspace(0, self.nyquist, n_freqs)
        eq_response = np.ones(n_freqs)

        # Convert EQ bands to arrays
        eq_freqs = np.array(EQ_BANDS)
        eq_gains_db = np.array([self.eq_gains[f] for f in EQ_BANDS])
        eq_gains_linear = 10 ** (eq_gains_db / 20.0)

        # Add DC and Nyquist points
        eq_freqs_ext = np.concatenate([[1], eq_freqs, [self.nyquist]])
        eq_gains_ext = np.concatenate([[1.0], eq_gains_linear, [eq_gains_linear[-1]]])

        # Log-frequency interpolation
        log_eq_freqs = np.log10(eq_freqs_ext)
        log_target_freqs = np.log10(np.maximum(freqs, 1))

        eq_response = np.interp(log_target_freqs, log_eq_freqs, eq_gains_ext)
        eq_response[0] = 1.0

        return eq_response

    def _build_spectral_response(self, n_freqs: int) -> np.ndarray:
        """
        Build Spectral frequency response

        Args:
            n_freqs: Number of frequency points

        Returns:
            Spectral response (linear scale)
        """
        if not self.spectral_enabled:
            return np.ones(n_freqs)

        if self._current_bass_gain == 1.0 and self._current_treble_gain == 1.0:
            return np.ones(n_freqs)

        freqs = np.linspace(0, self.nyquist, n_freqs)
        spectral_response = np.ones(n_freqs)

        bass_gain = self._current_bass_gain
        treble_gain = self._current_treble_gain

        # Bass region
        bass_mask = freqs < self.bass_freq
        spectral_response[bass_mask] = bass_gain

        # Bass transition
        bass_trans_mask = (freqs >= self.bass_freq) & (freqs < self.bass_trans_end)
        if np.any(bass_trans_mask):
            t = (freqs[bass_trans_mask] - self.bass_freq) / (self.bass_trans_end - self.bass_freq)
            smooth_t = (1 - np.cos(np.pi * t)) / 2
            spectral_response[bass_trans_mask] = bass_gain + (1.0 - bass_gain) * smooth_t

        # Treble transition
        treble_trans_mask = (freqs >= self.treble_trans_start) & (freqs < self.treble_freq)
        if np.any(treble_trans_mask):
            t = (freqs[treble_trans_mask] - self.treble_trans_start) / (self.treble_freq - self.treble_trans_start)
            smooth_t = (1 - np.cos(np.pi * t)) / 2
            spectral_response[treble_trans_mask] = 1.0 + (treble_gain - 1.0) * smooth_t

        # Treble region
        treble_mask = freqs >= self.treble_freq
        spectral_response[treble_mask] = treble_gain

        return spectral_response

    def _design_filter(self):
        """Design FIR filter using frequency sampling method"""
        n_freqs = self.numtaps // 2 + 1

        # Build combined response
        eq_response = self._build_eq_response(n_freqs)
        spectral_response = self._build_spectral_response(n_freqs)
        combined_response = eq_response * spectral_response

        # Convert to time domain via IFFT
        h = irfft(combined_response, n=self.numtaps)

        # Shift to make causal
        h = np.roll(h, self.numtaps // 2)

        # Apply window (Hamming)
        window = 0.54 - 0.46 * np.cos(2 * np.pi * np.arange(self.numtaps) / (self.numtaps - 1))
        h = h * window

        self._filter = h

    def set_eq_gains(self, **kwargs):
        """
        Set EQ band gains

        Args:
            eq_31, eq_62, ..., eq_16000: Gain in dB for each band
        """
        updated = False
        for freq in EQ_BANDS:
            key = f'eq_{freq}'
            if key in kwargs:
                if kwargs[key] != self.eq_gains[freq]:
                    self.eq_gains[freq] = kwargs[key]
                    updated = True

        if updated:
            self._design_filter()

    def set_spectral_gains(self, bass_gain: float = None, treble_gain: float = None):
        """
        Set spectral gains

        Args:
            bass_gain: Low frequency gain (0.5-2.0, linear)
            treble_gain: High frequency gain (0.5-2.0, linear)
        """
        if bass_gain is not None:
            self._target_bass_gain = bass_gain
            self.bass_gain = bass_gain
        if treble_gain is not None:
            self._target_treble_gain = treble_gain
            self.treble_gain = treble_gain

    def set_enabled(self, eq_enabled: bool = None, spectral_enabled: bool = None):
        """Set enable flags"""
        updated = False
        if eq_enabled is not None and eq_enabled != self.eq_enabled:
            self.eq_enabled = eq_enabled
            updated = True
        if spectral_enabled is not None and spectral_enabled != self.spectral_enabled:
            self.spectral_enabled = spectral_enabled
            updated = True

        if updated:
            self._design_filter()

    def _filter_channel(self, x: np.ndarray, ch: int) -> np.ndarray:
        """
        Apply FIR filter to single channel using overlap-save

        Args:
            x: Input signal
            ch: Channel index

        Returns:
            Filtered signal
        """
        M = len(self._filter)
        N = len(x)

        # Prepend state
        x_extended = np.concatenate([self._state[ch], x])

        # FFT convolution
        fft_size = 2 ** int(np.ceil(np.log2(len(x_extended) + M - 1)))
        X = rfft(x_extended, n=fft_size)
        H = rfft(self._filter, n=fft_size)
        Y = X * H
        y_full = irfft(Y, n=fft_size)

        # Overlap-save: discard transient
        y = y_full[M-1:M-1+N]

        # Update state
        if N >= M - 1:
            self._state[ch] = x[-(M-1):].copy()
        else:
            self._state[ch] = np.concatenate([self._state[ch][-(M-1-N):], x])

        return y

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Process audio with FIR-based EQ and Spectral enhancement

        Args:
            audio: Input audio of shape (n_samples, channels)

        Returns:
            Processed audio of same shape
        """
        # Check if processing is needed
        if not self.eq_enabled and not self.spectral_enabled:
            return audio

        # Smooth parameter changes and redesign filter if needed
        bass_changed = abs(self._current_bass_gain - self._target_bass_gain) > 0.02
        treble_changed = abs(self._current_treble_gain - self._target_treble_gain) > 0.02

        if bass_changed or treble_changed:
            self._current_bass_gain += self._smooth_alpha * (self._target_bass_gain - self._current_bass_gain)
            self._current_treble_gain += self._smooth_alpha * (self._target_treble_gain - self._current_treble_gain)
            self._design_filter()

        n_channels = min(audio.shape[1], self.channels)
        result = np.zeros_like(audio)

        for ch in range(n_channels):
            result[:, ch] = self._filter_channel(audio[:, ch], ch)

        return result.astype(np.float32)

    def reset(self):
        """Reset filter states"""
        for ch in range(self.channels):
            self._state[ch] = np.zeros(self.numtaps - 1)
        self._current_bass_gain = 1.0
        self._current_treble_gain = 1.0
        self._target_bass_gain = 1.0
        self._target_treble_gain = 1.0
        self._design_filter()

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
