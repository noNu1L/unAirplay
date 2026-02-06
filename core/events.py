"""
Event Definitions - Event types and event factory functions

This module defines all event types used in the event-driven architecture.
Events are the primary communication mechanism between components.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum, auto
import time


class EventType(Enum):
    """Event type enumeration"""

    # ===== Command Events =====
    # Published by external components (DLNAService, WebServer)
    # Subscribed by VirtualDevice
    CMD_PLAY = auto()           # Play command
    CMD_STOP = auto()           # Stop command
    CMD_PAUSE = auto()          # Pause command
    CMD_SEEK = auto()           # Seek command
    CMD_SET_VOLUME = auto()     # Set volume
    CMD_SET_MUTE = auto()       # Set mute
    CMD_SET_DSP = auto()        # Set DSP configuration
    CMD_RESET_DSP = auto()      # Reset DSP to defaults

    # ===== Device Events =====
    # Published by DeviceManager
    DEVICE_ADDED = auto()       # Device added
    DEVICE_REMOVED = auto()     # Device removed
    DEVICE_CONNECTED = auto()   # Device connected
    DEVICE_DISCONNECTED = auto()  # Device disconnected
    DEVICE_OFFLINE_THRESHOLD_REACHED = auto()  # Device offline threshold reached

    # ===== State Events =====
    # Published by VirtualDevice
    STATE_CHANGED = auto()      # Playback state changed
    POSITION_UPDATED = auto()   # Playback position updated
    METADATA_UPDATED = auto()   # Metadata updated
    DSP_CHANGED = auto()        # DSP configuration changed
    VOLUME_CHANGED = auto()     # Volume changed

    # ===== System Events =====
    SYSTEM_STARTUP = auto()     # System startup
    SYSTEM_SHUTDOWN = auto()    # System shutdown


@dataclass
class Event:
    """
    Event base class

    Attributes:
        type: Event type
        device_id: Target device ID (None = broadcast)
        data: Event data dictionary
        timestamp: Event creation timestamp
    """
    type: EventType
    device_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __repr__(self):
        return f"Event({self.type.name}, device={self.device_id if self.device_id else 'all'}...)"


# ===== Command Event Factories =====

def cmd_play(device_id: str, url: str, position: float = 0.0, **metadata) -> Event:
    """Create play command event"""
    return Event(
        type=EventType.CMD_PLAY,
        device_id=device_id,
        data={"url": url, "position": position, **metadata}
    )


def cmd_stop(device_id: str) -> Event:
    """Create stop command event"""
    return Event(type=EventType.CMD_STOP, device_id=device_id)


def cmd_pause(device_id: str) -> Event:
    """Create pause command event"""
    return Event(type=EventType.CMD_PAUSE, device_id=device_id)


def cmd_seek(device_id: str, position: float) -> Event:
    """Create seek command event"""
    return Event(
        type=EventType.CMD_SEEK,
        device_id=device_id,
        data={"position": position}
    )


def cmd_set_volume(device_id: str, volume: int) -> Event:
    """Create set volume command event"""
    return Event(
        type=EventType.CMD_SET_VOLUME,
        device_id=device_id,
        data={"volume": volume}
    )


def cmd_set_mute(device_id: str, muted: bool) -> Event:
    """Create set mute command event"""
    return Event(
        type=EventType.CMD_SET_MUTE,
        device_id=device_id,
        data={"muted": muted}
    )


def cmd_set_dsp(device_id: str, enabled: bool, config: dict = None) -> Event:
    """Create DSP configuration command event"""
    return Event(
        type=EventType.CMD_SET_DSP,
        device_id=device_id,
        data={"enabled": enabled, "config": config or {}}
    )


def cmd_reset_dsp(device_id: str) -> Event:
    """Create reset DSP command event"""
    return Event(type=EventType.CMD_RESET_DSP, device_id=device_id)


# ===== State Event Factories =====

def state_changed(device_id: str, state: str, **extra) -> Event:
    """Create state changed event"""
    return Event(
        type=EventType.STATE_CHANGED,
        device_id=device_id,
        data={"state": state, **extra}
    )


def position_updated(device_id: str, position: float, duration: float = 0) -> Event:
    """Create position updated event"""
    return Event(
        type=EventType.POSITION_UPDATED,
        device_id=device_id,
        data={"position": position, "duration": duration}
    )


def metadata_updated(device_id: str, title: str = "", artist: str = "", album: str = "", cover_url: str = "", duration: float = 0) -> Event:
    """Create metadata updated event"""
    return Event(
        type=EventType.METADATA_UPDATED,
        device_id=device_id,
        data={
            "title": title,
            "artist": artist,
            "album": album,
            "cover_url": cover_url,
            "duration": duration
        }
    )


def dsp_changed(device_id: str, enabled: bool, config: dict = None) -> Event:
    """Create DSP changed event"""
    return Event(
        type=EventType.DSP_CHANGED,
        device_id=device_id,
        data={"enabled": enabled, "config": config or {}}
    )


def volume_changed(device_id: str, volume: int, muted: bool = False) -> Event:
    """Create volume changed event"""
    return Event(
        type=EventType.VOLUME_CHANGED,
        device_id=device_id,
        data={"volume": volume, "muted": muted}
    )


# ===== Device Event Factories =====

def device_added(device_id: str, device_info: dict) -> Event:
    """Create device added event"""
    return Event(
        type=EventType.DEVICE_ADDED,
        device_id=device_id,
        data=device_info
    )


def device_removed(device_id: str) -> Event:
    """Create device removed event"""
    return Event(type=EventType.DEVICE_REMOVED, device_id=device_id)


def device_connected(device_id: str) -> Event:
    """Create device connected event"""
    return Event(type=EventType.DEVICE_CONNECTED, device_id=device_id)


def device_disconnected(device_id: str) -> Event:
    """Create device disconnected event"""
    return Event(type=EventType.DEVICE_DISCONNECTED, device_id=device_id)


def device_offline_threshold_reached(airplay_id: str) -> Event:
    """Create device offline threshold reached event (triggers virtual device removal)"""
    return Event(
        type=EventType.DEVICE_OFFLINE_THRESHOLD_REACHED,
        device_id=None,  # Using airplay_id in data, not device_id
        data={"airplay_id": airplay_id}
    )


# ===== System Event Factories =====

def system_startup() -> Event:
    """Create system startup event"""
    return Event(type=EventType.SYSTEM_STARTUP)


def system_shutdown() -> Event:
    """Create system shutdown event"""
    return Event(type=EventType.SYSTEM_SHUTDOWN)
