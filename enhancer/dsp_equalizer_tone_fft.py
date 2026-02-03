"""
FFT Mode Equalizer & Tone Processor

FFT 模式均衡器与音调处理器

Features:
- 10-band Graphic EQ in frequency domain
- Spectral Enhancement (Low/High Freq Gain) in frequency domain
- Combined gain curve: G_total = G_EQ × G_Spectral
- Single FFT/IFFT pass for efficiency
- Overlap-Add (OLA) architecture for streaming

Architecture:
- FFT size: 4096 (configurable)
- Hop size: 50% overlap (Hann window COLA compliant)
- Smooth gain curves with cosine interpolation

"""
import numpy as np
from numpy.fft import rfft, irfft, rfftfreq

from core.utils import log
from config import SAMPLE_RATE

# 10-band equalizer frequencies (Hz)
EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]

# FFT Configuration
FFT_SIZE = 4096
HOP_SIZE = 2048  # 50% overlap


class EqualizerToneFTT:
    """
    FFT Mode Equalizer & Tone Processor

    Combines 10-band graphic EQ with spectral enhancement in frequency domain.
    Uses Overlap-Add (OLA) architecture for streaming audio.

    Processing:
    1. Build combined gain curve (EQ × Spectral)
    2. Apply gain curve in frequency domain
    3. Use OLA for continuous output

    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = 2,
                 fft_size: int = FFT_SIZE, hop_size: int = HOP_SIZE):
        """
        Initialize FFT processor

        Args:
            sample_rate: Audio sample rate
            channels: Number of audio channels
            fft_size: FFT window size
            hop_size: Hop size for OLA
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.fft_size = fft_size
        self.hop_size = hop_size
        self.nyquist = sample_rate / 2

        # Enable flags
        self.eq_enabled = True
        self.spectral_enabled = True

        # EQ parameters
        self.eq_gains = {freq: 0.0 for freq in EQ_BANDS}  # dB

        # Spectral parameters
        self.bass_gain = 1.0  # Linear gain (0.5-2.0)
        self.treble_gain = 1.0  # Linear gain (0.5-2.0)
        self.bass_freq = 200  # Hz (full bass region)
        self.bass_trans_end = 300  # Hz (transition end)
        self.treble_trans_start = 3500  # Hz (transition start)
        self.treble_freq = 4500  # Hz (full treble region)

        # FFT components
        self._window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(fft_size) / fft_size)  # Hann
        self._freqs = rfftfreq(fft_size, 1.0 / sample_rate)

        # OLA buffers
        self._input_buffer = [np.zeros(0) for _ in range(channels)]
        self._output_buffer = [np.zeros(0) for _ in range(channels)]
        self._overlap_buffer = [np.zeros(hop_size) for _ in range(channels)]

        # Combined gain curve
        self._gain_curve = None
        self._update_gain_curve()

        # Parameter smoothing
        self._smooth_alpha = 0.1
        self._current_bass_gain = 1.0
        self._current_treble_gain = 1.0

        log("DSP", f"EqualizerToneFFT initialized: FFT={fft_size}, Hop={hop_size}")

    def _build_eq_curve(self) -> np.ndarray:
        """
        Build EQ gain curve from 10-band settings

        Uses log-frequency interpolation for smooth curve.

        Returns:
            EQ gain curve (linear scale)
        """
        if not self.eq_enabled:
            return np.ones_like(self._freqs)

        # Check if all gains are zero
        if all(g == 0 for g in self.eq_gains.values()):
            return np.ones_like(self._freqs)

        freqs = self._freqs
        n_freqs = len(freqs)
        eq_curve = np.ones(n_freqs)

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

        # Linear interpolation in log-frequency domain
        eq_curve = np.interp(log_target_freqs, log_eq_freqs, eq_gains_ext)

        # Ensure DC is unity
        eq_curve[0] = 1.0

        return eq_curve

    def _build_spectral_curve(self) -> np.ndarray:
        """
        Build Spectral gain curve from bass/treble settings

        Uses smooth cosine transitions.

        Returns:
            Spectral gain curve (linear scale)
        """
        if not self.spectral_enabled:
            return np.ones_like(self._freqs)

        if self.bass_gain == 1.0 and self.treble_gain == 1.0:
            return np.ones_like(self._freqs)

        freqs = self._freqs
        spectral_curve = np.ones_like(freqs)

        # Bass region (0 to bass_freq)
        bass_mask = freqs < self.bass_freq
        spectral_curve[bass_mask] = self.bass_gain

        # Bass transition (bass_freq to bass_trans_end)
        bass_trans_mask = (freqs >= self.bass_freq) & (freqs < self.bass_trans_end)
        if np.any(bass_trans_mask):
            t = (freqs[bass_trans_mask] - self.bass_freq) / (self.bass_trans_end - self.bass_freq)
            smooth_t = (1 - np.cos(np.pi * t)) / 2
            spectral_curve[bass_trans_mask] = self.bass_gain + (1.0 - self.bass_gain) * smooth_t

        # Mid region: gain = 1.0 (already set)

        # Treble transition (treble_trans_start to treble_freq)
        treble_trans_mask = (freqs >= self.treble_trans_start) & (freqs < self.treble_freq)
        if np.any(treble_trans_mask):
            t = (freqs[treble_trans_mask] - self.treble_trans_start) / (self.treble_freq - self.treble_trans_start)
            smooth_t = (1 - np.cos(np.pi * t)) / 2
            spectral_curve[treble_trans_mask] = 1.0 + (self.treble_gain - 1.0) * smooth_t

        # Treble region (treble_freq to Nyquist)
        treble_mask = freqs >= self.treble_freq
        spectral_curve[treble_mask] = self.treble_gain

        return spectral_curve

    def _update_gain_curve(self):
        """Update combined gain curve (EQ × Spectral)"""
        eq_curve = self._build_eq_curve()
        spectral_curve = self._build_spectral_curve()
        self._gain_curve = eq_curve * spectral_curve

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
            self._update_gain_curve()

    def set_spectral_gains(self, bass_gain: float = None, treble_gain: float = None):
        """
        Set spectral gains

        Args:
            bass_gain: Low frequency gain (0.5-2.0, linear)
            treble_gain: High frequency gain (0.5-2.0, linear)
        """
        updated = False
        if bass_gain is not None and bass_gain != self.bass_gain:
            self.bass_gain = bass_gain
            updated = True
        if treble_gain is not None and treble_gain != self.treble_gain:
            self.treble_gain = treble_gain
            updated = True

        if updated:
            self._update_gain_curve()

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
            self._update_gain_curve()

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Process a single frame with FFT

        Args:
            frame: Input frame of shape (fft_size,)

        Returns:
            Processed frame of shape (fft_size,)
        """
        # Apply analysis window
        windowed = frame * self._window

        # FFT
        spectrum = rfft(windowed)

        # Apply combined gain curve
        spectrum = spectrum * self._gain_curve

        # IFFT
        processed = irfft(spectrum, n=self.fft_size)

        return processed

    def process(self, audio: np.ndarray) -> np.ndarray:
        """
        Process audio with FFT-based EQ and Spectral enhancement

        Args:
            audio: Input audio of shape (n_samples, channels)

        Returns:
            Processed audio of same shape
        """
        # Check if processing is needed
        if not self.eq_enabled and not self.spectral_enabled:
            return audio

        # Smooth parameter changes
        self._current_bass_gain += self._smooth_alpha * (self.bass_gain - self._current_bass_gain)
        self._current_treble_gain += self._smooth_alpha * (self.treble_gain - self._current_treble_gain)

        n_samples = audio.shape[0]
        n_channels = min(audio.shape[1], self.channels)
        output = np.zeros_like(audio)

        for ch in range(n_channels):
            # Add new samples to input buffer
            self._input_buffer[ch] = np.concatenate([
                self._input_buffer[ch], audio[:, ch]
            ])

            # Process complete frames
            while len(self._input_buffer[ch]) >= self.fft_size:
                # Extract frame
                frame = self._input_buffer[ch][:self.fft_size]

                # Process frame
                processed_frame = self._process_frame(frame)

                # Overlap-Add
                first_half = processed_frame[:self.hop_size] + self._overlap_buffer[ch]
                self._overlap_buffer[ch] = processed_frame[self.hop_size:].copy()

                # Add to output buffer
                self._output_buffer[ch] = np.concatenate([
                    self._output_buffer[ch], first_half
                ])

                # Advance input buffer
                self._input_buffer[ch] = self._input_buffer[ch][self.hop_size:]

            # Extract output samples
            if len(self._output_buffer[ch]) >= n_samples:
                output[:, ch] = self._output_buffer[ch][:n_samples]
                self._output_buffer[ch] = self._output_buffer[ch][n_samples:]
            else:
                # Not enough output (initial latency)
                available = len(self._output_buffer[ch])
                if available > 0:
                    output[:available, ch] = self._output_buffer[ch]
                    self._output_buffer[ch] = np.zeros(0)

        return output.astype(np.float32)

    def reset(self):
        """Reset all buffers"""
        for ch in range(self.channels):
            self._input_buffer[ch] = np.zeros(0)
            self._output_buffer[ch] = np.zeros(0)
            self._overlap_buffer[ch] = np.zeros(self.hop_size)
        self._current_bass_gain = 1.0
        self._current_treble_gain = 1.0

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
