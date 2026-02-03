"""
Pure numpy DSP Audio Enhancer (no scipy dependency)
"""
import numpy as np
from numpy.fft import rfft, irfft, rfftfreq

from core.utils import log
from config import DEFAULT_DSP_CONFIG, SAMPLE_RATE
from .base import BaseEnhancer

# 10-band equalizer frequencies (Hz)
EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def _design_peak_filter(freq, gain_db, q, sample_rate):
    """
    Design peaking EQ filter (2nd order IIR coefficients)

    Based on Robert Bristow-Johnson's Audio EQ Cookbook
    """
    if gain_db == 0:
        return None

    A = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * freq / sample_rate
    alpha = np.sin(w0) / (2 * q)

    b0 = 1 + alpha * A
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / A

    b = np.array([b0 / a0, b1 / a0, b2 / a0])
    a = np.array([1.0, a1 / a0, a2 / a0])

    return b, a


def _design_butterworth(cutoff, sample_rate, btype='low', order=2):
    """
    Design Butterworth filter coefficients (2nd order)

    Uses bilinear transform to design IIR filter

    Args:
        cutoff: Cutoff frequency (Hz)
        sample_rate: Sample rate
        btype: 'low' or 'high'
        order: Filter order (currently only supports 2)

    Returns:
        b, a: Filter coefficients
    """
    # Pre-warping
    nyquist = sample_rate / 2
    normalized_cutoff = cutoff / nyquist

    if normalized_cutoff >= 1.0:
        return None, None

    # Analog prototype frequency
    warped = np.tan(np.pi * normalized_cutoff / 2)

    # 2nd order Butterworth filter
    if btype == 'low':
        # Lowpass filter
        k = warped
        k2 = k * k
        sqrt2 = np.sqrt(2.0)

        a0 = 1 + sqrt2 * k + k2
        b0 = k2 / a0
        b1 = 2 * k2 / a0
        b2 = k2 / a0
        a1 = 2 * (k2 - 1) / a0
        a2 = (1 - sqrt2 * k + k2) / a0

    elif btype == 'high':
        # Highpass filter
        k = warped
        k2 = k * k
        sqrt2 = np.sqrt(2.0)

        a0 = 1 + sqrt2 * k + k2
        b0 = 1 / a0
        b1 = -2 / a0
        b2 = 1 / a0
        a1 = 2 * (k2 - 1) / a0
        a2 = (1 - sqrt2 * k + k2) / a0
    else:
        return None, None

    b = np.array([b0, b1, b2])
    a = np.array([1.0, a1, a2])

    return b, a


def _lfilter(b, a, x):
    """
    IIR filter implementation (replaces scipy.signal.lfilter)

    Uses Direct Form II Transposed structure

    Args:
        b: Numerator coefficients (feedforward)
        a: Denominator coefficients (feedback), a[0] should be 1.0
        x: Input signal

    Returns:
        y: Filtered signal
    """
    n = len(x)
    nb = len(b)
    na = len(a)

    # Ensure a[0] = 1
    if a[0] != 1.0:
        b = b / a[0]
        a = a / a[0]

    # Output array
    y = np.zeros(n)

    # State variables (delay line)
    z = np.zeros(max(nb, na))

    for i in range(n):
        # Compute output
        y[i] = b[0] * x[i] + z[0]

        # Update state
        for j in range(len(z) - 1):
            z[j] = z[j + 1]
            if j + 1 < nb:
                z[j] += b[j + 1] * x[i]
            if j + 1 < na:
                z[j] -= a[j + 1] * y[i]

        z[-1] = 0
        if nb > 1:
            z[nb - 2] = b[nb - 1] * x[i] if nb - 1 < len(z) else 0
        if na > 1 and na - 2 < len(z):
            z[na - 2] -= a[na - 1] * y[i]

    return y


def _lfilter_fast(b, a, x):
    """
    Fast IIR filter implementation (numpy vectorized)

    Optimized implementation for 2nd order filters
    """
    n = len(x)
    y = np.zeros(n)

    # 2nd order filter state
    z1, z2 = 0.0, 0.0

    b0, b1, b2 = b[0], b[1], b[2]
    a1, a2 = a[1], a[2]

    for i in range(n):
        xi = x[i]
        yi = b0 * xi + z1
        z1 = b1 * xi - a1 * yi + z2
        z2 = b2 * xi - a2 * yi
        y[i] = yi

    return y


def _filtfilt(b, a, x):
    """
    Zero-phase filtering (replaces scipy.signal.filtfilt)

    Eliminates phase delay by forward and backward filtering
    """
    # Edge padding to reduce edge effects
    pad_len = 3 * max(len(b), len(a))

    # Reflection padding
    if len(x) > pad_len:
        x_padded = np.concatenate([
            2 * x[0] - x[pad_len:0:-1],
            x,
            2 * x[-1] - x[-2:-pad_len-2:-1]
        ])
    else:
        x_padded = x

    # Forward filtering
    y = _lfilter_fast(b, a, x_padded)

    # Backward filtering
    y = _lfilter_fast(b, a, y[::-1])[::-1]

    # Remove padding
    if len(x) > pad_len:
        y = y[pad_len:-pad_len]

    return y


class NumpyEnhancer(BaseEnhancer):
    """
    Pure numpy DSP enhancer (no scipy dependency)

    Features:
    - 10-band graphic equalizer
    - High frequency enhancement (compensate compression loss)
    - Low frequency enhancement (add bass thickness)
    - Dynamic range compression
    - Stereo enhancement
    - Spectral enhancement
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        super().__init__(sample_rate)
        self.nyquist = sample_rate / 2

        # Design filters
        self._design_highfreq_filter()
        self._design_lowfreq_filter()

        # Load default parameters from DEFAULT_DSP_CONFIG
        self.spectral_enabled = DEFAULT_DSP_CONFIG["spectral_enabled"]
        self.highfreq_gain = DEFAULT_DSP_CONFIG["highfreq_gain"]
        self.lowfreq_gain = DEFAULT_DSP_CONFIG["lowfreq_gain"]
        self.use_spectral = DEFAULT_DSP_CONFIG["use_spectral"]
        self.use_compression = DEFAULT_DSP_CONFIG["use_compression"]
        self.use_stereo = DEFAULT_DSP_CONFIG["use_stereo"]

        # Dynamic range compression parameters
        self.compressor_threshold = DEFAULT_DSP_CONFIG["compression_threshold"]
        self.compressor_ratio = DEFAULT_DSP_CONFIG["compression_ratio"]
        self.makeup_gain = DEFAULT_DSP_CONFIG["compression_makeup"]

        # Stereo enhancement parameters
        self.stereo_width = DEFAULT_DSP_CONFIG["stereo_width"]

        # 10-band equalizer
        self.eq_enabled = DEFAULT_DSP_CONFIG["eq_enabled"]
        self.eq_gains = {}
        for freq in EQ_BANDS:
            self.eq_gains[f'eq_{freq}'] = DEFAULT_DSP_CONFIG[f'eq_{freq}']

        # Build EQ filters
        self._build_eq_filters()

        log("DSP", "numpy DSP enhancer initialized (no scipy dependency)")

    def _design_highfreq_filter(self):
        """Design high frequency enhancement filter"""
        self.highfreq_b, self.highfreq_a = _design_butterworth(
            8000, self.sample_rate, btype='high', order=2
        )

    def _design_lowfreq_filter(self):
        """Design low frequency enhancement filter"""
        self.lowfreq_b, self.lowfreq_a = _design_butterworth(
            200, self.sample_rate, btype='low', order=2
        )

    def _build_eq_filters(self):
        """Build 10-band EQ filter coefficients"""
        self.eq_filters = []
        for freq in EQ_BANDS:
            key = f'eq_{freq}'
            gain_db = self.eq_gains.get(key, 0.0)
            if gain_db != 0:
                result = _design_peak_filter(freq, gain_db, q=1.4, sample_rate=self.sample_rate)
                if result:
                    self.eq_filters.append(result)

    def apply_eq(self, audio: np.ndarray) -> np.ndarray:
        """Apply 10-band equalizer"""
        if not self.eq_enabled or not self.eq_filters:
            return audio

        result = audio.copy()
        for b, a in self.eq_filters:
            for ch in range(result.shape[1]):
                result[:, ch] = _lfilter_fast(b, a, result[:, ch])

        return result

    def enhance_highfreq(self, audio: np.ndarray, gain: float) -> np.ndarray:
        """High frequency enhancement/attenuation (0.5-2.0)"""
        if self.highfreq_b is None or gain == 1.0:
            return audio

        enhanced = audio.copy()
        for ch in range(audio.shape[1]):
            highfreq = _filtfilt(self.highfreq_b, self.highfreq_a, audio[:, ch])
            enhanced[:, ch] = audio[:, ch] + highfreq * (gain - 1.0)

        return enhanced

    def enhance_lowfreq(self, audio: np.ndarray, gain: float) -> np.ndarray:
        """Low frequency enhancement/attenuation (0.5-2.0)"""
        if self.lowfreq_b is None or gain == 1.0:
            return audio

        enhanced = audio.copy()
        for ch in range(audio.shape[1]):
            lowfreq = _filtfilt(self.lowfreq_b, self.lowfreq_a, audio[:, ch])
            enhanced[:, ch] = audio[:, ch] + lowfreq * (gain - 1.0)

        return enhanced

    def spectral_enhance(self, audio: np.ndarray, treble_gain: float, bass_gain: float) -> np.ndarray:
        """Spectral enhancement - fine adjustment in frequency domain"""
        enhanced = np.zeros_like(audio)

        for ch in range(audio.shape[1]):
            spectrum = rfft(audio[:, ch])
            freqs = rfftfreq(len(audio[:, ch]), 1.0 / self.sample_rate)

            gain_curve = np.ones_like(freqs)

            # Low frequency enhancement (0-250Hz)
            bass_mask = freqs < 250
            gain_curve[bass_mask] = bass_gain

            # Mid frequency preservation (250Hz-4kHz)
            mid_mask = (freqs >= 250) & (freqs < 4000)
            gain_curve[mid_mask] = 1.0

            # High frequency enhancement (4kHz+)
            treble_mask = freqs >= 4000
            treble_freqs = freqs[treble_mask]
            if len(treble_freqs) > 0:
                treble_gains = 1.0 + (treble_gain - 1.0) * (treble_freqs - 4000) / (self.nyquist - 4000)
                gain_curve[treble_mask] = treble_gains

            spectrum = spectrum * gain_curve
            enhanced[:, ch] = irfft(spectrum, n=len(audio[:, ch]))

        return enhanced

    def dynamic_range_compress(self, audio: np.ndarray) -> np.ndarray:
        """Dynamic range compression"""
        threshold = self.compressor_threshold
        ratio = self.compressor_ratio
        makeup = self.makeup_gain

        abs_audio = np.abs(audio)
        compressed = np.where(
            abs_audio > threshold,
            threshold + (abs_audio - threshold) / ratio,
            abs_audio
        )

        result = np.sign(audio) * compressed * makeup
        result = np.clip(result, -1.0, 1.0)

        return result

    def stereo_enhance(self, audio: np.ndarray) -> np.ndarray:
        """Stereo enhancement - Mid-Side processing"""
        if audio.shape[1] != 2:
            return audio

        width = self.stereo_width

        mid = (audio[:, 0] + audio[:, 1]) / 2
        side = (audio[:, 0] - audio[:, 1]) / 2
        side = side * width

        enhanced = np.zeros_like(audio)
        enhanced[:, 0] = mid + side
        enhanced[:, 1] = mid - side
        enhanced = np.clip(enhanced, -1.0, 1.0)

        return enhanced

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        """Complete DSP enhancement pipeline"""
        result = audio.astype(np.float32)

        # 1. 10-band equalizer
        result = self.apply_eq(result)

        # 2. Spectral/filter enhancement
        if self.spectral_enabled:
            if self.use_spectral:
                # FFT-based spectral enhancement (more precise, no phase distortion)
                result = self.spectral_enhance(result, self.highfreq_gain, self.lowfreq_gain)
            else:
                # IIR filter-based enhancement (faster, more dynamic)
                if self.highfreq_gain != 1.0:
                    result = self.enhance_highfreq(result, self.highfreq_gain)
                if self.lowfreq_gain != 1.0:
                    result = self.enhance_lowfreq(result, self.lowfreq_gain)


        # 3. Dynamic range compression
        if self.use_compression:
            result = self.dynamic_range_compress(result)

        # 4. Stereo enhancement
        if self.use_stereo and audio.shape[1] == 2:
            result = self.stereo_enhance(result)

        return result.astype(np.float32)

    def set_params(self, **kwargs):
        """Set enhancement parameters"""
        if 'spectral_enabled' in kwargs:
            self.spectral_enabled = kwargs['spectral_enabled']
        if 'highfreq_gain' in kwargs:
            self.highfreq_gain = kwargs['highfreq_gain']
        if 'lowfreq_gain' in kwargs:
            self.lowfreq_gain = kwargs['lowfreq_gain']
        if 'use_spectral' in kwargs:
            self.use_spectral = kwargs['use_spectral']
        if 'use_compression' in kwargs:
            self.use_compression = kwargs['use_compression']
        if 'use_stereo' in kwargs:
            self.use_stereo = kwargs['use_stereo']
        if 'stereo_width' in kwargs:
            self.stereo_width = kwargs['stereo_width']
        if 'compression_threshold' in kwargs:
            self.compressor_threshold = kwargs['compression_threshold']
        if 'compression_ratio' in kwargs:
            self.compressor_ratio = kwargs['compression_ratio']
        if 'compression_makeup' in kwargs:
            self.makeup_gain = kwargs['compression_makeup']

        # EQ parameters
        if 'eq_enabled' in kwargs:
            self.eq_enabled = kwargs['eq_enabled']

        rebuild_eq = False
        for freq in EQ_BANDS:
            key = f'eq_{freq}'
            if key in kwargs:
                self.eq_gains[key] = kwargs[key]
                rebuild_eq = True

        if rebuild_eq:
            self._build_eq_filters()

    def get_params(self) -> dict:
        """Get current parameters"""
        params = {
            'spectral_enabled': self.spectral_enabled,
            'highfreq_gain': self.highfreq_gain,
            'lowfreq_gain': self.lowfreq_gain,
            'use_spectral': self.use_spectral,
            'use_compression': self.use_compression,
            'use_stereo': self.use_stereo,
            'stereo_width': self.stereo_width,
            'compression_threshold': self.compressor_threshold,
            'compression_ratio': self.compressor_ratio,
            'compression_makeup': self.makeup_gain,
            'eq_enabled': self.eq_enabled,
        }
        params.update(self.eq_gains)
        return params


# Alias for compatibility
ScipyEnhancer = NumpyEnhancer
