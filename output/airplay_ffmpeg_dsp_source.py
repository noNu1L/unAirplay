"""
AirPlay FFmpeg DSP Audio Source - Lossless audio source for pyatv

Implements pyatv's AudioSource interface to provide DSP-processed PCM directly.
This bypasses the need for intermediate encoding (MP3), achieving lossless quality.

Audio chain:
    URL -> FFmpeg (decode to PCM) -> DSP processing -> AudioSource -> pyatv (ALAC encode) -> AirPlay
"""
import array
import asyncio
import subprocess
import sys
from typing import Optional, TYPE_CHECKING

import numpy as np

from pyatv.protocols.raop.audio_source import AudioSource
from pyatv.interface import MediaMetadata

from core.utils import log_info, log_debug, log_warning, log_error
from config import SAMPLE_RATE, CHANNELS

if TYPE_CHECKING:
    from enhancer.base import BaseEnhancer
    from device.virtual_device import VirtualDevice


def _to_audio_samples(data: bytes) -> bytes:
    """Convert PCM bytes to the format expected by pyatv (with byteswap on little-endian systems)."""
    output = array.array("h", data)
    if sys.byteorder == "little":
        output.byteswap()
    return output.tobytes()


class AirPlayFFmpegDspAudioSource(AudioSource):
    """
    Custom AudioSource that provides DSP-processed PCM to pyatv.

    This allows lossless DSP processing:
    - FFmpeg decodes source to PCM (s16le)
    - DSP processing in PCM domain
    - pyatv encodes to ALAC for AirPlay transmission

    No intermediate lossy encoding (like MP3) is needed.
    """

    # pyatv expects 16-bit signed PCM, little endian
    SAMPLE_SIZE = 2  # bytes per sample

    def __init__(
        self,
        url: str,
        seek_position: float = 0.0,
        sample_rate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        enhancer: Optional["BaseEnhancer"] = None,
        dsp_config: Optional[dict] = None,
        duration: float = 0.0,
        device: Optional["VirtualDevice"] = None,
    ):
        """
        Initialize FFmpeg DSP audio source.

        Args:
            url: Audio URL to decode
            seek_position: Start position in seconds
            sample_rate: Output sample rate
            channels: Number of channels
            enhancer: DSP enhancer instance
            dsp_config: DSP configuration parameters (initial)
            duration: Total duration in seconds (0 = unknown)
            device: VirtualDevice for live DSP config updates
        """
        self._url = url
        self._seek_position = seek_position
        self._sample_rate = sample_rate
        self._channels = channels
        self._enhancer = enhancer
        self._dsp_config = dsp_config or {}
        self._duration = duration
        self._device = device  # For live DSP config updates

        # FFmpeg process
        self._process: Optional[subprocess.Popen] = None
        self._started = False
        self._closed = False
        self._eof = False

        # Internal buffer for partial reads
        self._buffer = b""

    @property
    def sample_rate(self) -> int:
        """Return sample rate."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Return number of audio channels."""
        return self._channels

    @property
    def sample_size(self) -> int:
        """Return number of bytes per sample."""
        return self.SAMPLE_SIZE

    @property
    def duration(self) -> int:
        """Return duration in seconds."""
        return int(self._duration)

    async def get_metadata(self) -> MediaMetadata:
        """Return media metadata."""
        return MediaMetadata(duration=self._duration if self._duration > 0 else None)

    def _start_ffmpeg(self):
        """Start FFmpeg decoder process."""
        if self._started:
            return

        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]

        # Add seek position
        if self._seek_position > 0:
            cmd.extend(["-ss", str(self._seek_position)])
            log_debug("AirPlayFFmpegDspAudioSource", f"Seeking to {self._seek_position}s")

        # Input and output settings - output s16le PCM
        cmd.extend([
            "-i", self._url,
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # 16-bit signed PCM little endian
            "-ar", str(self._sample_rate),
            "-ac", str(self._channels),
            "-f", "s16le",  # Raw PCM output
            "-"  # Output to stdout
        ])

        log_info("AirPlayFFmpegDspAudioSource", f"Starting decoder: sample_rate={self._sample_rate}, channels={self._channels}" +
                 (f", seek={self._seek_position}s" if self._seek_position > 0 else ""))

        try:
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=65536,  # Larger buffer for smoother reading
                **kwargs
            )
            self._started = True

            # Update enhancer params once
            if self._dsp_config and self._enhancer:
                try:
                    self._enhancer.set_params(**self._dsp_config)
                except Exception as e:
                    log_warning("AirPlayFFmpegDspAudioSource", f"Failed to set DSP params: {e}")

        except Exception as e:
            log_error("AirPlayFFmpegDspAudioSource", f"Failed to start FFmpeg: {e}")
            self._closed = True
            self._eof = True

    def _apply_dsp(self, pcm_data: bytes) -> bytes:
        """Apply DSP processing to PCM data."""
        # Check if DSP is enabled (read from device for live updates)
        if self._device and not self._device.dsp_enabled:
            return pcm_data

        if not self._enhancer:
            return pcm_data

        # Update enhancer params from device config (for live updates)
        if self._device and self._device.dsp_config:
            try:
                self._enhancer.set_params(**self._device.dsp_config)
            except Exception:
                pass

        # Convert s16le bytes to numpy float32 array
        samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
        samples = samples / 32768.0  # Normalize to [-1, 1]
        samples = samples.reshape(-1, self._channels)

        # Apply enhancement
        enhanced = self._enhancer.enhance(samples)

        # Convert back to s16le
        enhanced = np.clip(enhanced, -1.0, 1.0)
        enhanced = (enhanced * 32767).astype(np.int16)
        return enhanced.tobytes()

    async def readframes(self, nframes: int) -> bytes:
        """
        Read audio frames (called by pyatv).

        Args:
            nframes: Number of frames to read

        Returns:
            Raw PCM bytes (16-bit signed, little endian)
        """
        if not self._started:
            self._start_ffmpeg()

        if self._closed or self._eof:
            return AudioSource.NO_FRAMES

        if not self._process or not self._process.stdout:
            return AudioSource.NO_FRAMES

        # Calculate bytes needed
        bytes_per_frame = self._channels * self.SAMPLE_SIZE
        bytes_needed = nframes * bytes_per_frame

        # Read from FFmpeg stdout directly (in executor to not block event loop)
        try:
            # Read data in executor
            def read_data():
                return self._process.stdout.read(bytes_needed)

            pcm_data = await asyncio.get_event_loop().run_in_executor(None, read_data)

            if not pcm_data:
                self._eof = True
                log_debug("AirPlayFFmpegDspAudioSource", "EOF from FFmpeg")
                return AudioSource.NO_FRAMES

            # Apply DSP if enhancer is available and DSP is enabled
            if self._enhancer and (not self._device or self._device.dsp_enabled):
                try:
                    pcm_data = self._apply_dsp(pcm_data)
                except Exception as e:
                    log_warning("AirPlayFFmpegDspAudioSource", f"DSP error: {e}")

            # Convert to format expected by pyatv (byteswap on little-endian systems)
            return _to_audio_samples(pcm_data)

        except Exception as e:
            log_warning("AirPlayFFmpegDspAudioSource", f"Read error: {e}")
            self._eof = True
            return AudioSource.NO_FRAMES

    async def close(self) -> None:
        """Close underlying resources."""
        if self._closed:
            return

        self._closed = True

        # Close FFmpeg process
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2.0)
            except:
                try:
                    self._process.kill()
                except:
                    pass
            self._process = None

        log_debug("AirPlayFFmpegDspAudioSource", "Closed")
