"""
Pure numpy DSP Audio Enhancer (no scipy dependency)

Modular DSP processing pipeline:
- Equalizer & Tone: Combined EQ + Spectral (IIR/FFT/FIR modes)
- Dynamic Compression: Time-domain compression
- Stereo Enhancement: Mid-Side processing

"""
import numpy as np

from core.utils import log
from config import DEFAULT_DSP_CONFIG, SAMPLE_RATE
from .base import BaseEnhancer
from .dsp_equalizer_tone_iir import EqualizerToneIIR, EQ_BANDS
from .dsp_equalizer_tone_fft import EqualizerToneFTT
from .dsp_equalizer_tone_fir import EqualizerToneFIR
from .dsp_compression import DynamicCompressor
from .dsp_stereo import StereoEnhancer


class NumpyEnhancer(BaseEnhancer):
    """
    Pure numpy DSP enhancer (no scipy dependency)

    Features:
    - Equalizer & Tone (IIR/FFT/FIR modes)
    - Dynamic range compression
    - Stereo enhancement (Mid-Side)
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE):
        super().__init__(sample_rate)

        # Initialize DSP modules
        self.spectral_mode = None
        self.lowfreq_gain = None
        self.highfreq_gain = None
        self.eq_enabled = None

        # Three EQ+Tone processors (one for each mode)
        self._eq_tone_iir = EqualizerToneIIR(sample_rate=sample_rate)
        self._eq_tone_fft = EqualizerToneFTT(sample_rate=sample_rate)
        self._eq_tone_fir = EqualizerToneFIR(sample_rate=sample_rate)

        # Other processors
        self._compressor = DynamicCompressor()
        self._stereo = StereoEnhancer()

        # Load default parameters
        self._load_defaults()

    def _load_defaults(self):
        """Load default parameters from config"""
        # Mode and enable flags
        self.spectral_mode = DEFAULT_DSP_CONFIG.get("spectral_mode", "fft")
        self.eq_enabled = DEFAULT_DSP_CONFIG.get("eq_enabled", True)
        self.highfreq_gain = DEFAULT_DSP_CONFIG.get("highfreq_gain", 1.0)
        self.lowfreq_gain = DEFAULT_DSP_CONFIG.get("lowfreq_gain", 1.0)

        # EQ gains
        eq_gains = {f'eq_{freq}': DEFAULT_DSP_CONFIG.get(f'eq_{freq}', 0.0) for freq in EQ_BANDS}

        # Apply to all three processors
        for processor in [self._eq_tone_iir, self._eq_tone_fft, self._eq_tone_fir]:
            processor.set_enabled(eq_enabled=self.eq_enabled, spectral_enabled=self.eq_enabled)
            processor.set_eq_gains(**eq_gains)
            processor.set_spectral_gains(bass_gain=self.lowfreq_gain, treble_gain=self.highfreq_gain)

        # Compressor
        self._compressor.set_enabled(DEFAULT_DSP_CONFIG.get("use_compression", False))
        self._compressor.set_params(
            threshold=DEFAULT_DSP_CONFIG.get("compression_threshold", 0.7),
            ratio=DEFAULT_DSP_CONFIG.get("compression_ratio", 3.0),
            makeup_gain=DEFAULT_DSP_CONFIG.get("compression_makeup", 1.2)
        )

        # Stereo
        self._stereo.set_enabled(DEFAULT_DSP_CONFIG.get("use_stereo", False))
        self._stereo.set_width(DEFAULT_DSP_CONFIG.get("stereo_width", 1.2))

    def _get_current_processor(self):
        """Get the current EQ+Tone processor based on mode"""
        if self.spectral_mode == "iir":
            return self._eq_tone_iir
        elif self.spectral_mode == "fir":
            return self._eq_tone_fir
        elif self.spectral_mode == "fft":
            return self._eq_tone_fft
        else:
            return None

    def enhance(self, audio: np.ndarray) -> np.ndarray:
        """
        Complete DSP enhancement pipeline

        Processing order:
        1. Equalizer & Tone (IIR/FFT/FIR based on mode)
        2. Dynamic Compression
        3. Stereo Enhancement
        """
        result = audio.astype(np.float32)

        # 1. Equalizer & Tone (mode-specific)
        if self.eq_enabled:
            processor = self._get_current_processor()
            result = processor.process(result)

        # 2. Dynamic range compression
        result = self._compressor.process(result)

        # 3. Stereo enhancement
        if audio.shape[1] == 2:
            result = self._stereo.process(result)

        return result.astype(np.float32)

    def set_params(self, **kwargs):
        """Set enhancement parameters"""
        # Mode selection
        if 'spectral_mode' in kwargs:
            self.spectral_mode = kwargs['spectral_mode']

        # EQ enable (controls both EQ and Spectral)
        if 'eq_enabled' in kwargs:
            self.eq_enabled = kwargs['eq_enabled']
            for processor in [self._eq_tone_iir, self._eq_tone_fft, self._eq_tone_fir]:
                processor.set_enabled(eq_enabled=self.eq_enabled, spectral_enabled=self.eq_enabled)

        # Spectral gains
        if 'highfreq_gain' in kwargs:
            self.highfreq_gain = kwargs['highfreq_gain']
            for processor in [self._eq_tone_iir, self._eq_tone_fft, self._eq_tone_fir]:
                processor.set_spectral_gains(treble_gain=self.highfreq_gain)

        if 'lowfreq_gain' in kwargs:
            self.lowfreq_gain = kwargs['lowfreq_gain']
            for processor in [self._eq_tone_iir, self._eq_tone_fft, self._eq_tone_fir]:
                processor.set_spectral_gains(bass_gain=self.lowfreq_gain)

        # EQ gains (apply to all processors)
        eq_gains = {}
        for freq in EQ_BANDS:
            key = f'eq_{freq}'
            if key in kwargs:
                eq_gains[key] = kwargs[key]
        if eq_gains:
            for processor in [self._eq_tone_iir, self._eq_tone_fft, self._eq_tone_fir]:
                processor.set_eq_gains(**eq_gains)

        # Legacy: spectral_enabled (map to eq_enabled)
        if 'spectral_enabled' in kwargs and 'eq_enabled' not in kwargs:
            # Only apply if eq_enabled wasn't also set
            enabled = kwargs['spectral_enabled']
            for processor in [self._eq_tone_iir, self._eq_tone_fft, self._eq_tone_fir]:
                processor.set_enabled(spectral_enabled=enabled)

        # Compressor parameters
        if 'use_compression' in kwargs:
            self._compressor.set_enabled(kwargs['use_compression'])
        if 'compression_threshold' in kwargs:
            self._compressor.set_params(threshold=kwargs['compression_threshold'])
        if 'compression_ratio' in kwargs:
            self._compressor.set_params(ratio=kwargs['compression_ratio'])
        if 'compression_makeup' in kwargs:
            self._compressor.set_params(makeup_gain=kwargs['compression_makeup'])

        # Stereo parameters
        if 'use_stereo' in kwargs:
            self._stereo.set_enabled(kwargs['use_stereo'])
        if 'stereo_width' in kwargs:
            self._stereo.set_width(kwargs['stereo_width'])

    def get_params(self) -> dict:
        """Get current parameters"""
        processor = self._get_current_processor()
        params = {
            'spectral_mode': self.spectral_mode,
            'eq_enabled': self.eq_enabled,
            'spectral_enabled': self.eq_enabled,  # Legacy compatibility
        }
        params.update(processor.get_params())
        params.update(self._compressor.get_params())
        params.update(self._stereo.get_params())
        return params

    def reset_spectral_processor(self):
        """Reset current EQ+Tone processor buffers"""
        self._get_current_processor().reset()

    def reset_eq_filters(self):
        """Reset EQ filter states"""
        self._get_current_processor().reset()

    def reset_all(self):
        """Reset all DSP processor states"""
        self._eq_tone_iir.reset()
        self._eq_tone_fft.reset()
        self._eq_tone_fir.reset()


# Alias for compatibility
ScipyEnhancer = NumpyEnhancer
