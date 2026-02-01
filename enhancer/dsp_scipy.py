"""
基于 scipy 的 DSP 音频增强器
"""
import numpy as np
from scipy import signal
from scipy.fft import rfft, irfft, rfftfreq

from core.utils import log
from config import DEFAULT_DSP_CONFIG
from .base import BaseEnhancer

# 10 频段均衡器频率 (Hz)
EQ_BANDS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def _design_peak_filter(freq, gain_db, q, sample_rate):
    """
    设计峰值滤波器 (Peaking EQ) 的二阶 IIR 系数

    基于 Robert Bristow-Johnson 的 Audio EQ Cookbook
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


class ScipyEnhancer(BaseEnhancer):
    """
    基于 scipy 的数字信号处理增强器

    功能：
    - 10 频段图形均衡器
    - 高频增强（补偿压缩损失的高频）
    - 低频增强（增加低音厚度）
    - 动态范围压缩
    - 立体声增强
    - 频谱增强
    """

    def __init__(self, sample_rate: int = 44100):
        super().__init__(sample_rate)
        self.nyquist = sample_rate / 2

        # 设计滤波器
        self._design_highfreq_filter()
        self._design_lowfreq_filter()

        # 从 DEFAULT_DSP_CONFIG 加载默认参数
        self.highfreq_gain = DEFAULT_DSP_CONFIG["highfreq_gain"]
        self.lowfreq_gain = DEFAULT_DSP_CONFIG["lowfreq_gain"]
        self.use_spectral = DEFAULT_DSP_CONFIG["use_spectral"]
        self.use_compression = DEFAULT_DSP_CONFIG["use_compression"]
        self.use_stereo = DEFAULT_DSP_CONFIG["use_stereo"]

        # 动态范围压缩参数
        self.compressor_threshold = DEFAULT_DSP_CONFIG["compression_threshold"]
        self.compressor_ratio = DEFAULT_DSP_CONFIG["compression_ratio"]
        self.makeup_gain = DEFAULT_DSP_CONFIG["compression_makeup"]

        # 立体声增强参数
        self.stereo_width = DEFAULT_DSP_CONFIG["stereo_width"]

        # 10 频段均衡器
        self.eq_enabled = DEFAULT_DSP_CONFIG["eq_enabled"]
        self.eq_gains = {}
        for freq in EQ_BANDS:
            self.eq_gains[f'eq_{freq}'] = DEFAULT_DSP_CONFIG[f'eq_{freq}']

        # 构建 EQ 滤波器
        self._build_eq_filters()

        log("DSP", "scipy DSP 增强器已初始化")

    def _design_highfreq_filter(self):
        """设计高频增强滤波器"""
        cutoff = 8000 / self.nyquist
        if cutoff < 1.0:
            self.highfreq_b, self.highfreq_a = signal.butter(2, cutoff, btype='high')
        else:
            self.highfreq_b, self.highfreq_a = None, None

    def _design_lowfreq_filter(self):
        """设计低频增强滤波器"""
        cutoff = 200 / self.nyquist
        if cutoff < 1.0:
            self.lowfreq_b, self.lowfreq_a = signal.butter(2, cutoff, btype='low')
        else:
            self.lowfreq_b, self.lowfreq_a = None, None

    def _build_eq_filters(self):
        """构建 10 频段 EQ 的滤波器系数"""
        self.eq_filters = []
        for freq in EQ_BANDS:
            key = f'eq_{freq}'
            gain_db = self.eq_gains.get(key, 0.0)
            if gain_db != 0:
                result = _design_peak_filter(freq, gain_db, q=1.4, sample_rate=self.sample_rate)
                if result:
                    self.eq_filters.append(result)

    def apply_eq(self, audio: np.ndarray) -> np.ndarray:
        """应用 10 频段均衡器"""
        if not self.eq_enabled or not self.eq_filters:
            return audio

        result = audio.copy()
        for b, a in self.eq_filters:
            for ch in range(result.shape[1]):
                result[:, ch] = signal.lfilter(b, a, result[:, ch])

        return result

    def enhance_highfreq(self, audio: np.ndarray, gain: float) -> np.ndarray:
        """高频增强"""
        if self.highfreq_b is None or gain <= 1.0:
            return audio

        enhanced = audio.copy()
        for ch in range(audio.shape[1]):
            highfreq = signal.filtfilt(self.highfreq_b, self.highfreq_a, audio[:, ch])
            enhanced[:, ch] = audio[:, ch] + highfreq * (gain - 1.0)

        return enhanced

    def enhance_lowfreq(self, audio: np.ndarray, gain: float) -> np.ndarray:
        """低频增强"""
        if self.lowfreq_b is None or gain <= 1.0:
            return audio

        enhanced = audio.copy()
        for ch in range(audio.shape[1]):
            lowfreq = signal.filtfilt(self.lowfreq_b, self.lowfreq_a, audio[:, ch])
            enhanced[:, ch] = audio[:, ch] + lowfreq * (gain - 1.0)

        return enhanced

    def spectral_enhance(self, audio: np.ndarray, treble_gain: float, bass_gain: float) -> np.ndarray:
        """频谱增强 - 在频域进行精细调整"""
        enhanced = np.zeros_like(audio)

        for ch in range(audio.shape[1]):
            spectrum = rfft(audio[:, ch])
            freqs = rfftfreq(len(audio[:, ch]), 1.0 / self.sample_rate)

            gain_curve = np.ones_like(freqs)

            # 低频增强 (0-250Hz)
            bass_mask = freqs < 250
            gain_curve[bass_mask] = bass_gain

            # 中频保持 (250Hz-4kHz)
            mid_mask = (freqs >= 250) & (freqs < 4000)
            gain_curve[mid_mask] = 1.0

            # 高频增强 (4kHz+)
            treble_mask = freqs >= 4000
            treble_freqs = freqs[treble_mask]
            if len(treble_freqs) > 0:
                treble_gains = 1.0 + (treble_gain - 1.0) * (treble_freqs - 4000) / (self.nyquist - 4000)
                gain_curve[treble_mask] = treble_gains

            spectrum = spectrum * gain_curve
            enhanced[:, ch] = irfft(spectrum, n=len(audio[:, ch]))

        return enhanced

    def dynamic_range_compress(self, audio: np.ndarray) -> np.ndarray:
        """动态范围压缩"""
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
        """立体声增强 - Mid-Side 处理"""
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
        """完整的 DSP 增强流程"""
        result = audio.astype(np.float32)

        # 1. 10 频段均衡器
        result = self.apply_eq(result)

        # 2. 频谱/滤波器增强
        if self.use_spectral:
            result = self.spectral_enhance(result, self.highfreq_gain, self.lowfreq_gain)
        else:
            if self.highfreq_gain > 1.0:
                result = self.enhance_highfreq(result, self.highfreq_gain)
            if self.lowfreq_gain > 1.0:
                result = self.enhance_lowfreq(result, self.lowfreq_gain)

        # 3. 动态范围压缩
        if self.use_compression:
            result = self.dynamic_range_compress(result)

        # 4. 立体声增强
        if self.use_stereo and audio.shape[1] == 2:
            result = self.stereo_enhance(result)

        return result.astype(np.float32)

    def set_params(self, **kwargs):
        """设置增强参数"""
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

        # EQ 参数
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
        """获取当前参数"""
        params = {
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
