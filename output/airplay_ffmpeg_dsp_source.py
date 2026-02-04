"""
AirPlay FFmpeg DSP Audio Source - Lossless audio source for pyatv

Implements pyatv's AudioSource interface to provide DSP-processed PCM directly.
This bypasses the need for intermediate encoding (MP3), achieving lossless quality.

Architecture (Decoupled Download & Playback):
- Download thread: FFmpegDownloader (fast, no re-encoding)
- Playback: FFmpegDecoder from cache file to PCM
- Benefits: Network interruption won't affect playback if cache is ahead

Audio chain:
    URL -> FFmpegDownloader -> cache file -> FFmpegDecoder -> DSP -> AudioSource -> pyatv (ALAC) -> AirPlay
"""
import array
import asyncio
import os
import sys
import time
from typing import Optional, TYPE_CHECKING

import numpy as np

from pyatv.protocols.raop.audio_source import AudioSource
from pyatv.interface import MediaMetadata

from core.utils import log_info, log_debug, log_warning, log_error
from core.event_bus import event_bus
from core.events import state_changed
from core.ffmpeg_downloader import FFmpegDownloader, DownloaderConfig
from core.ffmpeg_decoder import FFmpegDecoder, DecoderConfig
from core.ffmpeg_utils import PCMFormat
from config import SAMPLE_RATE, CHANNELS, MIN_CACHE_SIZE

if TYPE_CHECKING:
    from enhancer.base import BaseEnhancer
    from device.virtual_device import VirtualDevice

# Cache directory for audio files
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

# Convert MIN_CACHE_SIZE from KB to bytes
MIN_CACHE_BYTES = MIN_CACHE_SIZE * 1024


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

        # FFmpeg downloader and decoder
        cache_filename = f"{device.device_id}_airplay_cache" if device else "airplay_cache"
        self._downloader = FFmpegDownloader(
            DownloaderConfig(
                cache_dir=CACHE_DIR,
                cache_filename=cache_filename
            ),
            tag="AirPlaySource"
        )
        self._decoder: Optional[FFmpegDecoder] = None

        # State
        self._started = False
        self._closed = False
        self._eof = False
        self._first_data_received = False

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

    def _start_download_and_decoder(self):
        """Start download and wait for cache buffer, then start decoder."""
        if self._started:
            return

        # Start download (from seek position if specified)
        self._downloader.start(self._url, seek_position=self._seek_position)

        # Wait for cache buffer (blocking)
        log_info("AirPlaySource", f"Waiting for cache buffer ({MIN_CACHE_SIZE}KB)" +
                 (f" (seek: {self._seek_position:.1f}s)" if self._seek_position > 0 else ""))
        wait_start = time.time()
        max_wait = 30  # seconds

        while True:
            file_size = self._downloader.get_file_size()
            if file_size >= MIN_CACHE_BYTES:
                log_info("AirPlaySource", f"Cache buffer ready ({file_size // 1024}KB)")
                break

            if self._downloader.error:
                log_error("AirPlaySource", f"Download failed: {self._downloader.error}")
                self._closed = True
                self._eof = True
                return

            if time.time() - wait_start > max_wait:
                log_error("AirPlaySource", "Cache buffer timeout")
                self._closed = True
                self._eof = True
                return

            time.sleep(0.1)

        # Start decoder from cache file (no seek needed, cache already starts from seek position)
        self._decoder = FFmpegDecoder(
            DecoderConfig(
                sample_rate=self._sample_rate,
                channels=self._channels,
                pcm_format=PCMFormat.S16LE,
                seek_position=0.0,  # No seek needed, cache file already starts from seek position
                buffer_size=65536,
                quiet=True
            ),
            tag="AirPlaySource"
        )
        self._decoder.start(self._downloader.file_path)

        if not self._decoder.is_running:
            log_error("AirPlaySource", "Failed to start decoder")
            self._closed = True
            self._eof = True
            return

        self._started = True

        # Update enhancer params once
        if self._dsp_config and self._enhancer:
            try:
                self._enhancer.set_params(**self._dsp_config)
            except Exception as e:
                log_warning("AirPlaySource", f"Failed to set DSP params: {e}")

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

    async def readframes(self, nframes: int) -> str | bytes:
        """
        Read audio frames (called by pyatv).

        Args:
            nframes: Number of frames to read

        Returns:
            Raw PCM bytes (16-bit signed, little endian)
        """
        device_name = self._device.device_name if self._device else "Unknown"

        if not self._started:
            # Run blocking download/decoder start in executor
            await asyncio.get_event_loop().run_in_executor(
                None, self._start_download_and_decoder
            )

        if self._closed or self._eof:
            return AudioSource.NO_FRAMES

        if not self._decoder or not self._decoder.is_running:
            return AudioSource.NO_FRAMES

        # Calculate bytes needed
        bytes_per_frame = self._channels * self.SAMPLE_SIZE
        bytes_needed = nframes * bytes_per_frame

        # Read from decoder (in executor to not block event loop)
        try:
            def read_data():
                return self._decoder.read(bytes_needed)

            pcm_data = await asyncio.get_event_loop().run_in_executor(None, read_data)

            if not pcm_data:
                self._eof = True
                log_debug("AirPlaySource", "EOF from decoder")
                return AudioSource.NO_FRAMES

            if not self._first_data_received:
                self._first_data_received = True
                log_info("AirPlaySource", f"First audio data received: {device_name}")

                try:
                    await event_bus.publish_async(
                        state_changed(self._device.device_id, state=self._device.play_state)
                    )
                except Exception as e:
                    log_error("AirPlaySource", f"Failed to notify state change: {e}")

            # Apply DSP if enhancer is available and DSP is enabled
            if self._enhancer and (not self._device or self._device.dsp_enabled):
                try:
                    pcm_data = self._apply_dsp(pcm_data)
                except Exception as e:
                    log_warning("AirPlaySource", f"DSP error: {e}")

            # Convert to format expected by pyatv (byteswap on little-endian systems)
            return _to_audio_samples(pcm_data)

        except Exception as e:
            log_warning("AirPlaySource", f"Read error: {e}")
            self._eof = True
            return AudioSource.NO_FRAMES

    async def close(self) -> None:
        """Close underlying resources."""
        if self._closed:
            return

        self._closed = True

        # Stop decoder
        if self._decoder:
            self._decoder.stop()
            self._decoder = None

        # Stop downloader and cleanup
        self._downloader.cleanup()

        log_debug("AirPlaySource", "Closed")
