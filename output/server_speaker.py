"""
ServerSpeakerOutput - System speaker audio output using sounddevice

Outputs audio to the server's local speakers via sounddevice library.
Supports DSP processing and volume/mute control.

Architecture (Decoupled Download & Playback):
- Download thread: FFmpegDownloader (fast, no re-encoding)
- Playback thread: FFmpegDecoder from cache file to PCM
- Benefits: Network interruption won't affect playback if cache is ahead
"""
import queue
import threading
import time
import asyncio
import os
from typing import Optional, TYPE_CHECKING

import numpy as np
import sounddevice as sd

from core.utils import log_info, log_debug, log_warning, log_error
from core.event_bus import event_bus
from core.events import state_changed
from core.ffmpeg_downloader import FFmpegDownloader, DownloaderConfig
from core.ffmpeg_decoder import FFmpegDecoder, DecoderConfig
from core.ffmpeg_utils import PCMFormat
from output.system_volume_controller import create_system_volume_controller
from config import SAMPLE_RATE, CHANNELS, CHUNK_DURATION_MS, BUFFER_SIZE, MIN_CACHE_SIZE

if TYPE_CHECKING:
    from device.virtual_device import VirtualDevice
    from enhancer.base import BaseEnhancer

# Cache directory for audio files
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

# Convert MIN_CACHE_SIZE from KB to bytes
MIN_CACHE_BYTES = MIN_CACHE_SIZE * 1024


class ServerSpeakerOutput:
    """
    Server Speaker output using sounddevice.

    Decodes audio from URL using FFmpeg and outputs to system speakers.
    Supports DSP processing, volume control, and mute.
    """

    def __init__(self, device: "VirtualDevice", enhancer: Optional["BaseEnhancer"] = None):
        """
        Initialize Server Speaker output.

        Args:
            device: Virtual device instance
            enhancer: Optional DSP enhancer
        """
        self._device = device
        self._enhancer = enhancer

        # Audio parameters
        self._sample_rate = SAMPLE_RATE
        self._channels = CHANNELS
        self._chunk_samples = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)
        self._bytes_per_sample = PCMFormat.F32LE.bytes_per_sample
        self._chunk_bytes = self._chunk_samples * self._channels * self._bytes_per_sample

        # Audio queue (PCM chunks from decoder)
        self._audio_queue: queue.Queue = queue.Queue(maxsize=BUFFER_SIZE)

        # sounddevice stream
        self._stream: Optional[sd.OutputStream] = None
        self._buffer = np.zeros((0, self._channels), dtype=np.float32)

        # FFmpeg downloader and decoder
        self._downloader = FFmpegDownloader(
            DownloaderConfig(
                cache_dir=CACHE_DIR,
                cache_filename=f"{device.device_id}_play_cache"
            ),
            tag="ServerSpeaker"
        )
        self._decoder: Optional[FFmpegDecoder] = None
        self._decoder_thread: Optional[threading.Thread] = None

        # State
        self._running = False
        self._is_playing = False
        self._current_url: Optional[str] = None
        self._current_position = 0.0
        self._playback_start_time = 0.0

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        # System volume controller
        self._volume_controller = create_system_volume_controller()
        if self._volume_controller and self._volume_controller.is_available():
            log_info("ServerSpeaker",
                    f"System volume controller initialized: {type(self._volume_controller).__name__}")
        else:
            log_warning("ServerSpeaker", "System volume control not available - volume control disabled")

    def set_enhancer(self, enhancer: "BaseEnhancer"):
        """Set DSP enhancer"""
        self._enhancer = enhancer

    def _apply_dsp(self, audio: np.ndarray) -> np.ndarray:
        """Apply DSP enhancement if enabled"""
        if self._device.dsp_enabled and self._enhancer:
            try:
                # Update enhancer params from device config
                self._enhancer.set_params(**self._device.dsp_config)
                return self._enhancer.enhance(audio)
            except Exception as e:
                log_warning("ServerSpeaker", f"DSP error: {e}")
        return audio

    def _audio_callback(self, outdata, frames, time_info, status):
        """sounddevice callback function"""
        if status:
            log_debug("ServerSpeaker", f"Output status: {status}")

        needed = frames

        # First use any buffered data
        if len(self._buffer) >= needed:
            outdata[:] = self._buffer[:needed]
            self._buffer = self._buffer[needed:]
        else:
            output = []
            if len(self._buffer) > 0:
                output.append(self._buffer)
                needed -= len(self._buffer)
                self._buffer = np.zeros((0, self._channels), dtype=np.float32)

            # Get data from queue
            while needed > 0:
                try:
                    chunk = self._audio_queue.get_nowait()
                    if len(chunk) <= needed:
                        output.append(chunk)
                        needed -= len(chunk)
                    else:
                        output.append(chunk[:needed])
                        self._buffer = chunk[needed:]
                        needed = 0
                except queue.Empty:
                    # No data available, output silence
                    output.append(np.zeros((needed, self._channels), dtype=np.float32))
                    needed = 0

            if output:
                combined = np.vstack(output)
                outdata[:len(combined)] = combined[:frames]
                if len(combined) < frames:
                    outdata[len(combined):] = 0
            else:
                outdata.fill(0)

    def _decoder_loop(self):
        """Decoder thread: waits for cache, reads decoded PCM from cache file, applies DSP, pushes to audio queue"""
        device_name = self._device.device_name
        cache_file = self._downloader.file_path
        log_debug("ServerSpeaker", f"Decoder thread started: {device_name}")

        # Wait for cache file to reach minimum size
        log_info("ServerSpeaker", f"Waiting for cache buffer ({MIN_CACHE_SIZE}KB): {device_name}")
        wait_start = time.time()
        max_wait = 30  # Maximum wait time in seconds

        while self._is_playing:
            file_size = self._downloader.get_file_size()
            if file_size >= MIN_CACHE_BYTES:
                log_info("ServerSpeaker", f"Cache buffer ready ({file_size // 1024}KB): {device_name}")
                break

            # Check for download error
            if self._downloader.error:
                log_error("ServerSpeaker", f"Download failed, stopping decoder: {device_name}")
                self._is_playing = False
                return

            # Check timeout
            if time.time() - wait_start > max_wait:
                log_error("ServerSpeaker", f"Cache buffer timeout: {device_name}")
                self._is_playing = False
                return

            time.sleep(0.1)

        if not self._is_playing:
            return

        # Start FFmpeg decoder from cache file
        self._decoder = FFmpegDecoder(
            DecoderConfig(
                sample_rate=self._sample_rate,
                channels=self._channels,
                pcm_format=PCMFormat.F32LE,
                realtime=True,
                quiet=True
            ),
            tag="ServerSpeaker"
        )
        self._decoder.start(cache_file)

        if not self._decoder.is_running:
            log_error("ServerSpeaker", f"Failed to start decoder: {device_name}")
            self._is_playing = False
            return

        buffer = b""
        first_data_received = False

        while self._is_playing and self._decoder.is_running:
            try:
                data = self._decoder.read(self._chunk_bytes)
                if not data:
                    log_info("ServerSpeaker", f"Decoder stream ended: {device_name}")
                    # Notify playback completed
                    try:
                        if self._event_loop and self._event_loop.is_running():
                            self._device.play_state = "STOPPED"
                            asyncio.run_coroutine_threadsafe(
                                event_bus.publish_async(state_changed(self._device.device_id, state="STOPPED")),
                                self._event_loop
                            )
                    except Exception as e:
                        log_error("ServerSpeaker", f"Failed to notify playback completed: {e}")
                    break

                if not first_data_received:
                    first_data_received = True
                    log_debug("ServerSpeaker", f"First audio data received from FFmpeg: {device_name}")

                    try:
                        if self._event_loop and self._event_loop.is_running():
                            asyncio.run_coroutine_threadsafe(
                                event_bus.publish_async(state_changed(self._device.device_id, state=self._device.play_state)),
                                self._event_loop
                            )
                    except Exception as e:
                        log_error("ServerSpeaker", f"Failed to notify DLNA client of state change: {e}")

                buffer += data

                while len(buffer) >= self._chunk_bytes:
                    chunk_data = buffer[:self._chunk_bytes]
                    buffer = buffer[self._chunk_bytes:]

                    # Convert to numpy array
                    audio = np.frombuffer(chunk_data, dtype=np.float32).copy()
                    audio = audio.reshape(-1, self._channels)

                    # Apply DSP
                    enhanced = self._apply_dsp(audio)

                    # Put in output queue
                    try:
                        self._audio_queue.put_nowait(enhanced)
                    except queue.Full:
                        # Queue full, drop oldest
                        try:
                            self._audio_queue.get_nowait()
                            self._audio_queue.put_nowait(enhanced)
                        except queue.Empty:
                            pass

            except Exception as e:
                if self._is_playing:
                    log_error("ServerSpeaker", f"Decoder read error: {e}")
                break

        self._is_playing = False
        log_debug("ServerSpeaker", f"Decoder thread ended: {device_name}")

    def _start_playback(self, url: str, seek_position: float = 0.0):
        """Start playback: download thread + decoder thread"""
        self._stop_playback_internal()

        self._current_url = url
        self._current_position = seek_position
        self._playback_start_time = time.time()
        self._is_playing = True

        log_info("ServerSpeaker", f"Starting playback: {self._device.device_name}" +
                 (f" (seek: {seek_position:.1f}s)" if seek_position > 0 else ""))

        # Start download (from seek position if specified)
        self._downloader.start(url, seek_position=seek_position)

        # Start decoder thread (will wait for cache buffer)
        self._decoder_thread = threading.Thread(
            target=self._decoder_loop,
            daemon=True
        )
        self._decoder_thread.start()

    def _stop_playback_internal(self):
        """Stop both download and decoder processes"""
        self._is_playing = False

        # Stop downloader
        self._downloader.stop()

        # Stop decoder
        if self._decoder:
            self._decoder.stop()
            self._decoder = None

        # Wait for decoder thread to finish
        if self._decoder_thread and self._decoder_thread.is_alive():
            self._decoder_thread.join(timeout=1)
        self._decoder_thread = None

    def start(self):
        """Start audio output stream"""
        if self._running:
            return

        self._running = True

        try:
            self._stream = sd.OutputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype=np.float32,
                blocksize=self._chunk_samples,
                callback=self._audio_callback,
                latency="low"
            )
            self._stream.start()
            log_info("ServerSpeaker", f"Audio output started: {self._device.device_name} "
                     f"(rate: {self._sample_rate}, channels: {self._channels})")
        except Exception as e:
            log_error("ServerSpeaker", f"Failed to start audio output: {e}")
            self._running = False
            raise

    def stop(self):
        """Stop audio output completely"""
        self._running = False
        self._stop_playback_internal()

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except:
                pass
            self._stream = None

        # Clear buffer and queue
        self._buffer = np.zeros((0, self._channels), dtype=np.float32)
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        # Clean up cache file
        self._downloader.cleanup_file()

        log_info("ServerSpeaker", f"Audio output stopped: {self._device.device_name}")

    def play(self, url: str, position: float = 0.0):
        """
        Start playing audio from URL.

        Args:
            url: Audio URL to play
            position: Start position in seconds (default: 0.0)
        """
        if not self._running:
            self.start()
        self._start_playback(url, seek_position=position)
        log_info("ServerSpeaker", f"Playing: {self._device.device_name}")

    def stop_playback(self):
        """Stop current playback and clean up cache"""
        self._stop_playback_internal()

        # Clear audio queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        # Clean up cache file
        self._downloader.cleanup_file()

        log_info("ServerSpeaker", f"Playback stopped: {self._device.device_name}")

    def pause(self):
        """Pause playback - record position and stop (keep cache for resume)"""
        if self._is_playing:
            elapsed = time.time() - self._playback_start_time
            self._current_position += elapsed
        self._stop_playback_internal()
        # Note: Don't clean up cache file here, so we can resume later
        log_info("ServerSpeaker", f"Paused: {self._device.device_name}")

    def seek(self, position: float):
        """
        Seek to position (restarts playback from position).

        Args:
            position: Position in seconds
        """
        if self._current_url:
            log_info("ServerSpeaker", f"Seek to {position:.1f}s: {self._device.device_name}")
            # Clear queue
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break
            # Restart playback from new position
            self._start_playback(self._current_url, position)
        else:
            log_warning("ServerSpeaker", f"Cannot seek: no URL: {self._device.device_name}")

    def set_volume(self, volume: int):
        """
        Set volume (0-100).

        Args:
            volume: Volume level 0-100
        """
        if self._volume_controller and self._volume_controller.is_available():
            if self._volume_controller.set_volume(volume):
                log_debug("ServerSpeaker", f"System volume set to {volume}%")
            else:
                log_warning("ServerSpeaker", f"Failed to set system volume to {volume}%")
        else:
            log_debug("ServerSpeaker", "System volume control not available")

    def set_mute(self, muted: bool):
        """
        Set mute state.

        Args:
            muted: True to mute
        """
        if self._volume_controller and self._volume_controller.is_available():
            if self._volume_controller.set_mute(muted):
                log_debug("ServerSpeaker", f"System mute set to {muted}")
            else:
                log_warning("ServerSpeaker", f"Failed to set system mute to {muted}")
        else:
            log_debug("ServerSpeaker", "System mute control not available")

    def get_volume(self) -> int:
        """
        Get current system volume.

        Returns:
            Volume level 0-100, or 0 if not available
        """
        if self._volume_controller and self._volume_controller.is_available():
            return self._volume_controller.get_volume()
        return 0

    def get_mute(self) -> bool:
        """
        Get current system mute state.

        Returns:
            True if muted, False otherwise
        """
        if self._volume_controller and self._volume_controller.is_available():
            return self._volume_controller.get_mute()
        return False

    def get_current_position(self) -> float:
        """Get current playback position in seconds"""
        if self._is_playing:
            elapsed = time.time() - self._playback_start_time
            return self._current_position + elapsed
        return self._current_position

    def get_current_url(self) -> str:
        """Get current playback URL"""
        return self._current_url

    def is_playing(self) -> bool:
        """Check if currently playing"""
        return self._is_playing

    def is_running(self) -> bool:
        """Check if output stream is running"""
        return self._running

    def cleanup(self):
        """Clean up resources"""
        self.stop()

    def handle_action(self, action: str, **kwargs):
        """
        Handle playback action.

        Args:
            action: Action name (play, stop, pause, seek, set_volume, set_mute)
            **kwargs: Action parameters
        """
        if action == "play":
            uri = kwargs.get("uri") or self._device.play_url
            position = kwargs.get("position", 0.0)
            if uri:
                self.play(uri, position)

        elif action == "stop":
            self.stop_playback()

        elif action == "pause":
            self.pause()

        elif action == "seek":
            position = kwargs.get("position", 0)
            self.seek(position)

        elif action == "set_volume":
            volume = kwargs.get("volume", 50)
            self.set_volume(volume)

        elif action == "set_mute":
            muted = kwargs.get("muted", False)
            self.set_mute(muted)



