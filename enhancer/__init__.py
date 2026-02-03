# Audio enhancer module
from .base import BaseEnhancer
from .dsp_numpy2 import NumpyEnhancer as ScipyEnhancer

# EQ+Tone processors (IIR/FFT/FIR modes)
from .dsp_equalizer_tone_iir import EqualizerToneIIR, EQ_BANDS
from .dsp_equalizer_tone_fft import EqualizerToneFTT
from .dsp_equalizer_tone_fir import EqualizerToneFIR
