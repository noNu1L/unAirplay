"""
AirPlay Audio Output - Unified implementation using pyatv and FFmpeg

All playback modes use lossless audio chain:
    URL -> FFmpeg (decode to PCM) -> [Optional DSP] -> pyatv (ALAC encode) -> AirPlay
"""
import asyncio
import queue
import threading
import sys
from typing import Optional, TYPE_CHECKING

import pyatv
from pyatv.const import Protocol
from pyatv.interface import MediaMetadata

from core.utils import log_info, log_debug, log_warning, log_error
from core.event_bus import event_bus
from core.events import state_changed
from config import SAMPLE_RATE, CHANNELS, AIRPLAY_SCAN_TIMEOUT
from .base import BaseOutput
from .airplay_ffmpeg_dsp_source import AirPlayFFmpegDspAudioSource

if TYPE_CHECKING:
    from device.virtual_device import VirtualDevice
    from enhancer.base import BaseEnhancer


class AirPlayOutput(BaseOutput):
    """
    AirPlay audio output bound to a specific virtual device.

    Unified lossless playback:
        URL -> FFmpeg (decode to PCM) -> [Optional DSP] -> pyatv (ALAC encode) -> AirPlay

    Features:
    - Seek support via FFmpeg -ss parameter
    - Optional DSP processing in PCM domain
    - Lossless quality (no intermediate lossy encoding)
    """

    def __init__(self, device: "VirtualDevice", enhancer: Optional["BaseEnhancer"] = None):
        """
        Initialize AirPlay output for a specific device.

        Args:
            device: Virtual device instance
            enhancer: Optional DSP enhancer instance
        """
        super().__init__()
        self._device = device
        self._enhancer = enhancer
        self.audio_queue = queue.Queue(maxsize=10)

        self._running = False
        self._is_playing = False
        self._volume = 100
        self._muted = False

        # AirPlay connection
        self._atv = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._playback_thread: Optional[threading.Thread] = None

        # Current audio source
        self._stream_task: Optional[asyncio.Task] = None
        self._current_source: Optional[AirPlayFFmpegDspAudioSource] = None

        # Lock to prevent concurrent stream operations
        self._stream_lock = asyncio.Lock()

        # Audio settings
        self._sample_rate = SAMPLE_RATE
        self._channels = CHANNELS

    def set_enhancer(self, enhancer: "BaseEnhancer"):
        """Set DSP enhancer."""
        self._enhancer = enhancer

    async def connect(self) -> bool:
        """
        Connect to the AirPlay device.

        Returns:
            True if connected successfully
        """
        if not self._device.airplay_id:
            log_warning("AirPlayOutput", f"No AirPlay ID for: {self._device.device_name}")
            return False

        try:
            log_info("AirPlayOutput", f"Connecting to: {self._device.device_name} ({self._device.airplay_address})")

            # Scan for target device
            atvs = await pyatv.scan(
                loop=self._loop or asyncio.get_event_loop(),
                timeout=AIRPLAY_SCAN_TIMEOUT,
                protocol=Protocol.AirPlay,
            )

            # Find target device
            target_atv = None
            for atv in atvs:
                if str(atv.identifier) == str(self._device.airplay_id):
                    target_atv = atv
                    break

            if not target_atv:
                log_warning("AirPlayOutput", f"Device not found: {self._device.device_name}")
                return False

            self._atv = await pyatv.connect(target_atv, loop=self._loop)
            self._device.connected = True

            log_info("AirPlayOutput", f"Connected to: {self._device.device_name}")
            return True

        except Exception as e:
            log_error("AirPlayOutput", f"Connection failed: {e}")
            return False

    async def play_url(
        self,
        url: str,
        seek_position: float = 0.0,
        dsp_enabled: bool = False,
        dsp_config: Optional[dict] = None
    ) -> bool:
        """
        Unified playback method - lossless audio chain.

        Audio chain:
            URL -> FFmpeg (decode to PCM) -> [Optional DSP] -> pyatv (ALAC encode) -> AirPlay

        Args:
            url: Audio URL to play
            seek_position: Start position in seconds (0 = from beginning)
            dsp_enabled: Whether to apply DSP processing
            dsp_config: DSP configuration parameters

        Returns:
            True if started successfully
        """
        if not self._atv:
            log_warning("AirPlayOutput", "Not connected")
            return False

        # Use lock to prevent concurrent stream operations
        async with self._stream_lock:
            await self._stop_current_stream()

            # Build mode description for logging
            mode_parts = []
            if seek_position > 0:
                mode_parts.append(f"seek={seek_position}s")
            if dsp_enabled:
                mode_parts.append("DSP")
            mode_info = f" ({', '.join(mode_parts)})" if mode_parts else ""

            log_info("AirPlayOutput", f"Playing to: {self._device.device_name}{mode_info}")
            log_debug("AirPlayOutput", f"URL: {url[:80]}...")

            self._is_playing = True

            # Unified lossless playback
            self._stream_task = asyncio.create_task(
                self._stream_url_unified(url, seek_position, dsp_enabled, dsp_config)
            )

        return True

    async def _stream_url_unified(
        self,
        url: str,
        seek_position: float,
        dsp_enabled: bool,
        dsp_config: Optional[dict]
    ):
        """
        Unified lossless streaming via pyatv AudioSource interface.

        Audio chain: URL -> FFmpeg PCM -> [Optional DSP] -> pyatv ALAC encode -> AirPlay
        """
        playback_manager = None
        takeover_release = None

        try:
            # Access pyatv internal components
            # FacadeStream wraps the actual RaopStream, we need to get the underlying instance
            facade_stream = self._atv.stream

            # Get the actual RaopStream instance from the facade
            raop_stream = None
            for instance in facade_stream.instances:
                if hasattr(instance, 'playback_manager'):
                    raop_stream = instance
                    break

            if not raop_stream:
                raise RuntimeError("Could not find RaopStream instance")

            playback_manager = raop_stream.playback_manager
            core = raop_stream.core

            playback_manager.acquire()

            # Import internal components
            from pyatv.interface import Audio, Metadata, PushUpdater, RemoteControl
            from pyatv.protocols.airplay.auth import extract_credentials

            takeover_release = core.takeover(Audio, Metadata, PushUpdater, RemoteControl)

            client, context = await playback_manager.setup(core.service)
            context.credentials = extract_credentials(core.service)
            context.password = core.service.password

            client.listener = raop_stream.listener
            await client.initialize(core.service.properties)

            # Log pyatv context info
            log_info("AirPlayOutput", f"pyatv context: sample_rate={context.sample_rate}, channels={context.channels}")

            # Create AudioSource (with or without DSP)
            # Pass device for live DSP config updates
            self._current_source = AirPlayFFmpegDspAudioSource(
                url=url,
                seek_position=seek_position,
                sample_rate=context.sample_rate,
                channels=context.channels,
                enhancer=self._enhancer,  # Always pass enhancer for live DSP toggle
                dsp_config=dsp_config if dsp_enabled else None,
                device=self._device,  # For live DSP config updates
            )

            log_debug("AirPlayOutput", f"Streaming (sample_rate={context.sample_rate}, channels={context.channels}, dsp={dsp_enabled})")

            # Get metadata
            file_metadata = await self._current_source.get_metadata()

            # Handle volume
            volume = None
            if not raop_stream.audio.has_changed_volume and "initialVolume" in client.info:
                initial_volume = client.info["initialVolume"]
                if isinstance(initial_volume, float):
                    context.volume = initial_volume
            else:
                try:
                    await raop_stream.audio.set_volume(raop_stream.audio.volume)
                except Exception:
                    volume = raop_stream.audio.volume

            # Send audio using our custom source
            await client.send_audio(self._current_source, file_metadata, volume=volume)

            log_info("AirPlayOutput", f"Stream completed: {self._device.device_name}")

            # Notify playback completed
            self._device.play_state = "STOPPED"
            await event_bus.publish_async(state_changed(self._device.device_id, state="STOPPED"))

        except asyncio.CancelledError:
            log_debug("AirPlayOutput", "Stream cancelled")
        except Exception as e:
            log_error("AirPlayOutput", f"Stream error: {e}")
            import traceback
            log_debug("AirPlayOutput", traceback.format_exc())
        finally:
            # Always cleanup resources
            if takeover_release:
                takeover_release()
            if self._current_source:
                await self._current_source.close()
                self._current_source = None
            if playback_manager:
                try:
                    await playback_manager.teardown()
                except Exception:
                    pass
            self._is_playing = False

    async def _stop_current_stream(self):
        """Stop current streaming task and wait for cleanup."""
        self._is_playing = False

        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._stream_task = None

        if self._current_source:
            await self._current_source.close()
            self._current_source = None

        # Small delay to ensure pyatv resources are fully released
        await asyncio.sleep(0.1)

    async def stop(self):
        """Stop playback."""
        await self._stop_current_stream()

        # Clear queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        log_info("AirPlayOutput", f"Stopped: {self._device.device_name}")

    async def disconnect(self):
        """Disconnect from AirPlay device."""
        await self.stop()

        if self._atv:
            self._atv.close()
            self._atv = None

        self._device.connected = False
        log_info("AirPlayOutput", f"Disconnected: {self._device.device_name}")

    def start_background_loop(self):
        """Start async event loop in background thread."""
        if self._running:
            return

        self._running = True

        started_event = threading.Event()

        def run_loop():
            if sys.platform == 'win32':
                self._loop = asyncio.ProactorEventLoop()
            else:
                self._loop = asyncio.new_event_loop()

            asyncio.set_event_loop(self._loop)
            started_event.set()
            self._loop.run_forever()

        self._playback_thread = threading.Thread(target=run_loop, daemon=True)
        self._playback_thread.start()

        started_event.wait(timeout=5.0)
        log_debug("AirPlayOutput", "Background loop started")

    def start(self):
        """Start the output (alias for start_background_loop)."""
        self.start_background_loop()

    def stop_background_loop(self):
        """Stop background event loop."""
        if not self._running:
            return

        self._running = False

        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

        log_debug("AirPlayOutput", "Background loop stopped")

    def run_coroutine(self, coro):
        """
        Run coroutine in background loop.

        Args:
            coro: Coroutine to run

        Returns:
            Future for the result
        """
        if not self._loop:
            raise RuntimeError("Background loop not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def get_queue(self) -> queue.Queue:
        """Get audio queue (for compatibility)."""
        return self.audio_queue

    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._is_playing

    def is_running(self) -> bool:
        """Check if output is running (background loop active)."""
        return self._running

    def is_connected(self) -> bool:
        """Check if connected to device."""
        return self._atv is not None

    def set_volume(self, volume: int):
        """
        Set AirPlay device volume (0-100).

        Args:
            volume: Volume level 0-100
        """
        self._volume = max(0, min(100, volume))
        log_debug("AirPlayOutput", f"Volume set to {self._volume}%")

        # Apply to connected AirPlay device
        if self._atv and self.is_connected():
            self.run_coroutine(self._set_volume_async(self._volume))

    async def _set_volume_async(self, volume: int):
        """
        Async implementation of volume control via pyatv.

        Args:
            volume: Volume level 0-100
        """
        try:
            # pyatv expects volume as float 0.0-100.0
            await self._atv.audio.set_volume(float(volume))
            log_debug("AirPlayOutput", f"AirPlay volume set to {volume}%")
        except Exception as e:
            log_warning("AirPlayOutput", f"Failed to set AirPlay volume: {e}")

    def get_volume(self) -> int:
        """
        Get current AirPlay device volume.

        Returns:
            Volume level 0-100, or cached value if not connected
        """
        if self._atv and self.is_connected():
            try:
                # Get volume from pyatv (returns float)
                volume = self._atv.audio.volume
                if volume is not None:
                    self._volume = int(volume)
                    return self._volume
            except Exception as e:
                log_debug("AirPlayOutput", f"Failed to get AirPlay volume: {e}")
        return self._volume

    def set_mute(self, muted: bool):
        """
        Set AirPlay device mute state.

        Note: AirPlay doesn't have native mute, implemented via volume control.

        Args:
            muted: True to mute, False to unmute
        """
        self._muted = muted
        log_debug("AirPlayOutput", f"Mute set to {muted}")

        # Implement mute via volume control
        if self._atv and self.is_connected():
            if muted:
                # Save current volume and set to 0
                self.run_coroutine(self._set_volume_async(0))
            else:
                # Restore previous volume
                self.run_coroutine(self._set_volume_async(self._volume))

    def get_mute(self) -> bool:
        """
        Get current mute state.

        Returns:
            True if muted, False otherwise
        """
        return self._muted

    def handle_action(self, action: str, **kwargs):
        """
        Handle playback action.

        Args:
            action: Action name (play, stop, pause, seek, set_volume, set_mute)
            **kwargs: Action parameters
        """
        if action == "set_uri":
            # URI is stored in device by DLNAService
            pass

        elif action == "play":
            uri = kwargs.get("uri") or self._device.play_url
            position = kwargs.get("position", 0.0)
            if not uri:
                log_warning("AirPlayOutput", "No URI to play")
                return

            # Use unified play_url with device DSP settings
            self.run_coroutine(self.play_url(
                url=uri,
                seek_position=position,
                dsp_enabled=self._device.dsp_enabled,
                dsp_config=self._device.dsp_config if self._device.dsp_enabled else None
            ))

        elif action == "stop":
            self.run_coroutine(self.stop())

        elif action == "pause":
            # AirPlay doesn't have true pause, stop instead
            self.run_coroutine(self.stop())

        elif action == "seek":
            position = kwargs.get("position", 0)
            uri = self._device.play_url
            if uri:
                log_info("AirPlayOutput", f"Seeking to {position}s")
                self.run_coroutine(self.stop())
                self.run_coroutine(self.play_url(
                    url=uri,
                    seek_position=float(position),
                    dsp_enabled=self._device.dsp_enabled,
                    dsp_config=self._device.dsp_config if self._device.dsp_enabled else None
                ))

        elif action == "set_volume":
            volume = kwargs.get("volume", 50)
            self.set_volume(volume)

        elif action == "set_mute":
            muted = kwargs.get("muted", False)
            self.set_mute(muted)

    @property
    def loop(self):
        return self._loop


class AirPlayOutputManager:
    """
    Manager for multiple AirPlay outputs.
    """

    def __init__(self):
        """Initialize manager."""
        self._outputs: dict[str, AirPlayOutput] = {}

    def create_output(self, device: "VirtualDevice", enhancer: Optional["BaseEnhancer"] = None) -> AirPlayOutput:
        """
        Create AirPlay output for a device.

        Args:
            device: Virtual device
            enhancer: Optional DSP enhancer

        Returns:
            AirPlayOutput instance
        """
        if device.device_id in self._outputs:
            return self._outputs[device.device_id]

        output = AirPlayOutput(device, enhancer)
        self._outputs[device.device_id] = output
        log_info("AirPlayOutputManager", f"Created output: {device.device_name}")
        return output

    def get_output(self, device_id: str) -> Optional[AirPlayOutput]:
        """Get output by device ID."""
        return self._outputs.get(device_id)

    def remove_output(self, device_id: str):
        """Remove output."""
        output = self._outputs.pop(device_id, None)
        if output:
            output.run_coroutine(output.disconnect())
            output.stop_background_loop()
            log_info("AirPlayOutputManager", f"Removed output: {device_id[:8]}...")

    async def stop_all(self):
        """Stop all outputs."""
        for output in self._outputs.values():
            await output.stop()

    def cleanup_all(self):
        """Cleanup all outputs."""
        for output in self._outputs.values():
            if output.loop:
                output.run_coroutine(output.disconnect())
                output.stop_background_loop()
        self._outputs.clear()
