"""
VirtualDevice - Core virtual device entity (Container/Executor)

This is the central component of the system. Each VirtualDevice:
- Holds device state (playback, DSP, volume, etc.)
- Owns and manages its Output instance
- Owns and manages its DSP Enhancer
- Subscribes to command events and executes them
- Publishes state change events
"""
import hashlib
import uuid
import time
import copy
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, TYPE_CHECKING

from core.event_bus import event_bus
from core.events import (
    EventType, Event,
    state_changed, dsp_changed, volume_changed, metadata_updated
)
from core.utils import log_info, log_debug, log_warning, log_error
from config import DEFAULT_DSP_CONFIG, DEVICE_SUFFIX, SERVER_SPEAKER_NAME

if TYPE_CHECKING:
    from output.base import BaseOutput
    from enhancer.base import BaseEnhancer


def generate_device_id(airplay_id: Optional[str] = None, device_type: str = "airplay") -> str:
    """
    Generate deterministic device ID.

    Args:
        airplay_id: AirPlay device identifier (for AirPlay devices)
        device_type: Device type ("airplay" or "server_speaker")

    Returns:
        Deterministic device ID
    """
    if device_type == "server_speaker":
        return "server_speaker"
    elif airplay_id:
        return hashlib.md5(airplay_id.encode()).hexdigest()[:16]
    else:
        return str(uuid.uuid4())[:16]


@dataclass
class VirtualDevice:
    """
    Virtual DLNA device - Core executor component.

    Each virtual device represents a DLNA renderer that bridges to either
    an AirPlay device or a Server Speaker output.

    This is an active component that:
    - Subscribes to command events (CMD_PLAY, CMD_STOP, etc.)
    - Executes commands via its Output instance
    - Publishes state change events (STATE_CHANGED, DSP_CHANGED, etc.)
    """

    # Device identification
    device_id: str = ""
    device_name: str = ""
    device_type: str = "airplay"  # "airplay" | "server_speaker"

    # AirPlay device info (None for server_speaker)
    airplay_id: Optional[str] = None
    airplay_address: Optional[str] = None
    airplay_model: Optional[str] = None

    # Channel configuration
    channel_mode: str = "stereo"
    group_id: Optional[str] = None

    # Playback state
    play_state: str = "STOPPED"
    play_url: str = ""
    play_title: str = ""
    play_artist: str = ""
    play_album: str = ""
    play_cover_url: str = ""
    play_duration: float = 0.0
    play_position: float = 0.0
    play_start_time: float = 0.0

    # Audio info
    audio_format: str = ""
    audio_bitrate: str = ""
    audio_sample_rate: int = 0
    audio_channels: int = 0
    is_streaming: bool = False  # Whether the source is a streaming source (no caching needed)

    # DSP configuration
    dsp_enabled: bool = False
    dsp_config: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_DSP_CONFIG))

    # Volume
    volume: int = 100
    muted: bool = False

    # Connection state
    connected: bool = False
    last_seen: float = field(default_factory=time.time)

    # DLNA service info
    dlna_uuid: str = field(default_factory=lambda: f"uuid:dlna-bridge-{uuid.uuid4().hex[:8]}")

    # Active DLNA clients (IP and SID tracking)
    # Records clients that have performed control actions (Play, Stop, Pause, Seek, SetAVTransportURI)
    active_client_ip: Optional[str] = None
    active_client_sid: Optional[str] = None

    # Internal components (not serialized)
    _output: Optional["BaseOutput"] = field(default=None, repr=False)
    _enhancer: Optional["BaseEnhancer"] = field(default=None, repr=False)
    _subscribed: bool = field(default=False, repr=False)

    def __post_init__(self):
        """Post initialization processing"""
        if not self.device_id:
            self.device_id = generate_device_id(self.airplay_id, self.device_type)

        if not self.device_name:
            if self.device_type == "server_speaker":
                self.device_name = f"{SERVER_SPEAKER_NAME} {DEVICE_SUFFIX}"
            else:
                self.device_name = f"Unknown {DEVICE_SUFFIX}"

    # ===== Factory Methods =====

    @classmethod
    def create_airplay_device(cls, airplay_info: Dict[str, Any]) -> "VirtualDevice":
        """Create a virtual device from AirPlay device info."""
        name = airplay_info.get("name", "Unknown")
        airplay_id = airplay_info.get("identifier")
        return cls(
            device_id=generate_device_id(airplay_id, "airplay"),
            device_name=f"{name} {DEVICE_SUFFIX}",
            device_type="airplay",
            airplay_id=airplay_id,
            airplay_address=airplay_info.get("address"),
            airplay_model=airplay_info.get("model"),
        )

    @classmethod
    def create_server_speaker(cls) -> "VirtualDevice":
        """Create a Server Speaker virtual device."""
        return cls(
            device_id=generate_device_id(None, "server_speaker"),
            device_name=f"{SERVER_SPEAKER_NAME} {DEVICE_SUFFIX}",
            device_type="server_speaker",
        )

    # ===== Event Subscription =====

    def subscribe_events(self):
        """Subscribe to command events for this device"""
        if self._subscribed:
            return

        event_bus.subscribe(EventType.CMD_PLAY, self._on_cmd_play, device_id=self.device_id)
        event_bus.subscribe(EventType.CMD_STOP, self._on_cmd_stop, device_id=self.device_id)
        event_bus.subscribe(EventType.CMD_PAUSE, self._on_cmd_pause, device_id=self.device_id)
        event_bus.subscribe(EventType.CMD_SEEK, self._on_cmd_seek, device_id=self.device_id)
        event_bus.subscribe(EventType.CMD_SET_VOLUME, self._on_cmd_volume, device_id=self.device_id)
        event_bus.subscribe(EventType.CMD_SET_MUTE, self._on_cmd_mute, device_id=self.device_id)
        event_bus.subscribe(EventType.CMD_SET_DSP, self._on_cmd_dsp, device_id=self.device_id)
        event_bus.subscribe(EventType.CMD_RESET_DSP, self._on_cmd_reset_dsp, device_id=self.device_id)

        self._subscribed = True
        log_debug("VirtualDevice", f"Subscribed to events: {self.device_name}")

    def unsubscribe_events(self):
        """Unsubscribe from all events"""
        if not self._subscribed:
            return

        event_bus.unsubscribe_device(self.device_id)
        self._subscribed = False
        log_debug("VirtualDevice", f"Unsubscribed from events: {self.device_name}")

    # ===== Command Event Handlers =====

    def _on_cmd_play(self, event: Event):
        """Handle play command"""
        url = event.data.get("url")
        position = event.data.get("position", 0.0)  # Extract position, default to 0

        if not url:
            log_warning("VirtualDevice", f"[{event.trace_id}] Play command without URL: {self.device_name}")
            return

        # Update metadata if provided
        if "title" in event.data:
            self.play_title = event.data.get("title", "")
        if "artist" in event.data:
            self.play_artist = event.data.get("artist", "")
        if "album" in event.data:
            self.play_album = event.data.get("album", "")
        if "cover_url" in event.data:
            self.play_cover_url = event.data.get("cover_url", "")
        if "duration" in event.data:
            self.play_duration = event.data.get("duration", 0.0)

        self._execute_play(url, position, event.trace_id)

    def _on_cmd_stop(self, event: Event):
        """Handle stop command"""
        self._execute_stop(event.trace_id)

    def _on_cmd_pause(self, event: Event):
        """Handle pause command"""
        self._execute_pause(event.trace_id)

    def _on_cmd_seek(self, event: Event):
        """Handle seek command"""
        position = event.data.get("position", 0.0)
        self._execute_seek(position, event.trace_id)

    def _on_cmd_volume(self, event: Event):
        """Handle volume command"""
        volume = event.data.get("volume", 100)
        self._execute_set_volume(volume, event.trace_id)

    def _on_cmd_mute(self, event: Event):
        """Handle mute command"""
        muted = event.data.get("muted", False)
        self._execute_set_mute(muted, event.trace_id)

    def _on_cmd_dsp(self, event: Event):
        """Handle DSP configuration command"""
        enabled = event.data.get("enabled", False)
        config = event.data.get("config", {})
        self._execute_set_dsp(enabled, config, event.trace_id)

    def _on_cmd_reset_dsp(self, event: Event):
        """Handle reset DSP command"""
        self._execute_reset_dsp(event.trace_id)

    # ===== Command Execution =====

    def _execute_play(self, url: str, position: float = 0.0, trace_id: str = "--------"):
        """Execute play command

        Args:
            url: Media URL to play
            position: Start position in seconds (default: 0.0)
            trace_id: Trace ID for logging
        """
        log_info("VirtualDevice", f"[{trace_id}] Play: {self.device_name} position={position}s")

        self.play_url = url
        self.play_state = "PLAYING"
        self.play_position = position
        self.play_start_time = time.time()
        self.last_seen = time.time()

        # Execute via output (pass position for seeking)
        if self._output:
            self._output.handle_action("play", uri=url, position=position)

        # Publish state changed event
        event_bus.publish(state_changed(
            self.device_id,
            state="PLAYING",
            url=url
        ))

    def _execute_stop(self, trace_id: str = "--------"):
        """Execute stop command"""
        log_info("VirtualDevice", f"[{trace_id}] Stop: {self.device_name}")

        self.play_state = "STOPPED"
        self.play_position = 0.0
        self.play_start_time = 0.0
        self.last_seen = time.time()

        if self._output:
            self._output.handle_action("stop")

        event_bus.publish(state_changed(self.device_id, state="STOPPED"))

    def _execute_pause(self, trace_id: str = "--------"):
        """Execute pause command"""
        log_info("VirtualDevice", f"[{trace_id}] Pause: {self.device_name}")

        # Save current position
        if self.play_state == "PLAYING" and self.play_start_time > 0:
            elapsed = time.time() - self.play_start_time
            self.play_position += elapsed

        self.play_state = "PAUSED_PLAYBACK"
        self.play_start_time = 0.0
        self.last_seen = time.time()

        if self._output:
            self._output.handle_action("pause")

        event_bus.publish(state_changed(self.device_id, state="PAUSED_PLAYBACK"))

    def _execute_seek(self, position: float, trace_id: str = "--------"):
        """Execute seek command"""
        log_info("VirtualDevice", f"[{trace_id}] Seek: {self.device_name} position={position}s")

        self.play_position = position
        if self.play_state == "PLAYING":
            self.play_start_time = time.time()
        self.last_seen = time.time()

        if self._output:
            self._output.handle_action("seek", position=position)

    def _execute_set_volume(self, volume: int, trace_id: str = "--------"):
        """Execute set volume command"""
        self.volume = max(0, min(100, volume))
        log_debug("VirtualDevice", f"[{trace_id}] Volume: {self.device_name} volume={self.volume}%")

        if self._output:
            self._output.handle_action("set_volume", volume=self.volume)

        event_bus.publish(volume_changed(self.device_id, self.volume, self.muted))

    def _execute_set_mute(self, muted: bool, trace_id: str = "--------"):
        """Execute set mute command"""
        self.muted = muted
        log_debug("VirtualDevice", f"[{trace_id}] Mute: {self.device_name} muted={muted}")

        if self._output:
            self._output.handle_action("set_mute", muted=muted)

        event_bus.publish(volume_changed(self.device_id, self.volume, self.muted))

    def _execute_set_dsp(self, enabled: bool, config: dict, trace_id: str = "--------"):
        """Execute set DSP command"""
        self.dsp_enabled = enabled
        if config:
            self.dsp_config.update(config)

        log_info("VirtualDevice", f"[{trace_id}] DSP: {self.device_name} enabled={enabled}")

        # Publish DSP changed event (ConfigStore will save it)
        event_bus.publish(dsp_changed(self.device_id, enabled, self.dsp_config))

    def _execute_reset_dsp(self, trace_id: str = "--------"):
        """Execute reset DSP command"""
        self.dsp_enabled = False
        self.dsp_config = copy.deepcopy(DEFAULT_DSP_CONFIG)

        log_info("VirtualDevice", f"[{trace_id}] DSP Reset: {self.device_name}")

        event_bus.publish(dsp_changed(self.device_id, False, self.dsp_config))

    # ===== Output Management =====

    def set_output(self, output: "BaseOutput"):
        """Set output instance"""
        self._output = output

    def get_output(self) -> Optional["BaseOutput"]:
        """Get output instance"""
        return self._output

    def set_enhancer(self, enhancer: "BaseEnhancer"):
        """Set DSP enhancer"""
        self._enhancer = enhancer

    def get_enhancer(self) -> Optional["BaseEnhancer"]:
        """Get DSP enhancer"""
        return self._enhancer

    # ===== State Methods =====

    def update_playback_state(
        self,
        state: str,
        url: str = None,
        title: str = None,
        artist: str = None,
        album: str = None,
        cover_url: str = None,
        duration: float = None,
    ):
        """Update playback state and metadata (called by external sources like DLNA)"""
        self.play_state = state

        if url is not None:
            self.play_url = url
        if title is not None:
            self.play_title = title
        if artist is not None:
            self.play_artist = artist
        if album is not None:
            self.play_album = album
        if cover_url is not None:
            self.play_cover_url = cover_url
        if duration is not None:
            self.play_duration = duration

        if state == "PLAYING":
            self.play_start_time = time.time()
        elif state == "STOPPED":
            self.play_position = 0.0
            self.play_start_time = 0.0

        self.last_seen = time.time()

    def update_audio_info(
        self,
        format: str = None,
        bitrate: str = None,
        sample_rate: int = None,
        channels: int = None,
    ):
        """Update audio stream information"""
        if format is not None:
            self.audio_format = format
        if bitrate is not None:
            self.audio_bitrate = bitrate
        if sample_rate is not None:
            self.audio_sample_rate = sample_rate
        if channels is not None:
            self.audio_channels = channels

    def set_active_client(self, client_ip: str, client_sid: str):
        """
        Set the active DLNA client.

        Args:
            client_ip: Client IP address
            client_sid: Client subscription ID (SID), can be None if not found
        """
        self.active_client_ip = client_ip
        self.active_client_sid = client_sid
        log_debug("VirtualDevice", f"Active client set: {client_ip} (SID: {client_sid})")

    def get_active_client(self) -> tuple[Optional[str], Optional[str]]:
        """
        Get the active DLNA client.

        Returns:
            Tuple of (client_ip, client_sid)
        """
        return self.active_client_ip, self.active_client_sid

    def get_current_position(self) -> float:
        """Get current playback position in seconds"""
        # Try to get actual position from Output instance
        if self._output and hasattr(self._output, 'get_current_position'):
            try:
                return self._output.get_current_position()
            except:
                pass

        # Fallback to theoretical position calculation
        if self.play_state == "PLAYING" and self.play_start_time > 0:
            elapsed = time.time() - self.play_start_time
            return self.play_position + elapsed
        return self.play_position

    def set_position(self, position: float):
        """Set playback position (for seek operations)"""
        self.play_position = position
        if self.play_state == "PLAYING":
            self.play_start_time = time.time()

    # ===== Lifecycle =====

    async def start(self) -> bool:
        """Start the virtual device"""
        self.subscribe_events()
        log_info("VirtualDevice", f"Started: {self.device_name}")
        return True

    async def shutdown(self):
        """Shutdown the virtual device"""
        self.unsubscribe_events()

        if self._output:
            if hasattr(self._output, 'cleanup'):
                self._output.cleanup()
            self._output = None

        log_info("VirtualDevice", f"Shutdown: {self.device_name}")

    # ===== Serialization =====

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "airplay_id": self.airplay_id,
            "airplay_address": self.airplay_address,
            "airplay_model": self.airplay_model,
            "channel_mode": self.channel_mode,
            "group_id": self.group_id,
            "play_state": self.play_state,
            "play_url": self.play_url,
            "play_title": self.play_title,
            "play_artist": self.play_artist,
            "play_album": self.play_album,
            "play_cover_url": self.play_cover_url,
            "play_duration": self.play_duration,
            "play_position": self.get_current_position(),
            "audio_format": self.audio_format,
            "audio_bitrate": self.audio_bitrate,
            "audio_sample_rate": self.audio_sample_rate,
            "audio_channels": self.audio_channels,
            "dsp_enabled": self.dsp_enabled,
            "dsp_config": self.dsp_config,
            "volume": self.volume,
            "muted": self.muted,
            "connected": self.connected,
        }

    # ===== Utility Methods =====

    def format_duration(self) -> str:
        """Format duration as HH:MM:SS string"""
        return self._format_time(self.play_duration)

    def format_position(self) -> str:
        """Format current position as HH:MM:SS string"""
        return self._format_time(self.get_current_position())

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as HH:MM:SS string"""
        if seconds <= 0:
            return "00:00:00"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def parse_time(time_str: str) -> float:
        """Parse HH:MM:SS string to seconds"""
        try:
            parts = time_str.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            else:
                return float(parts[0])
        except (ValueError, IndexError):
            return 0.0
