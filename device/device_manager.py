"""
DeviceManager - Virtual device lifecycle manager

This module manages the lifecycle of virtual devices:
- Creates virtual devices for discovered AirPlay devices
- Creates Server Speaker virtual device
- Publishes device events (DEVICE_ADDED, DEVICE_REMOVED, etc.)
- Loads/saves device configuration via ConfigStore
"""
import asyncio
from typing import Dict, List, Optional, Any, Callable

from core.utils import log_info, log_debug, log_warning
from core.event_bus import event_bus
from core.events import EventType, device_added, device_removed, device_connected, device_disconnected
from core.config_store import config_store
from config import ENABLE_SERVER_SPEAKER
from output.audio_device_detector import has_audio_output_device, log_audio_devices
from .virtual_device import VirtualDevice
from .airplay_scanner import AirPlayScanner


class DeviceManager:
    """
    Virtual device manager.

    Manages the lifecycle of virtual DLNA devices:
    - Creating virtual devices for discovered AirPlay devices
    - Creating Server Speaker virtual device for local audio output
    - Publishing device events
    - Loading/saving device configuration
    """

    def __init__(self):
        """Initialize device manager."""
        self._devices: Dict[str, VirtualDevice] = {}  # device_id -> VirtualDevice
        self._airplay_map: Dict[str, str] = {}  # airplay_id -> device_id
        self._scanner = AirPlayScanner(
            on_device_found=self._on_airplay_found,
            on_device_lost=self._on_airplay_lost,
        )
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Callbacks for output creation (set by run.py)
        self._output_factory: Optional[Callable[[VirtualDevice], None]] = None

    def set_output_factory(self, factory: Callable[[VirtualDevice], None]):
        """
        Set factory function for creating outputs.

        Args:
            factory: Function that creates and attaches output to device
        """
        self._output_factory = factory

    def _on_airplay_found(self, airplay_info: Dict[str, Any]):
        """
        Handle AirPlay device discovery.

        Args:
            airplay_info: AirPlay device information
        """
        airplay_id = airplay_info.get("identifier")
        if not airplay_id:
            return

        # Check if we already have a virtual device for this AirPlay device
        if airplay_id in self._airplay_map:
            # Update existing device info
            device_id = self._airplay_map[airplay_id]
            device = self._devices.get(device_id)
            if device:
                device.airplay_address = airplay_info.get("address")
                device.connected = True
                log_debug("DeviceManager", f"Updated AirPlay device: {device.device_name}")

                # Publish connected event
                event_bus.publish(device_connected(device_id))
            return

        # Create new virtual device
        device = VirtualDevice.create_airplay_device(airplay_info)
        device.connected = True

        # Load saved DSP config
        self._load_device_config(device)

        self._devices[device.device_id] = device
        self._airplay_map[airplay_id] = device.device_id

        log_info("DeviceManager", f"Created virtual device: {device.device_name} (AirPlay: {airplay_info.get('name')}, id: {device.device_id})")

        # Start device (subscribe to events)
        asyncio.run_coroutine_threadsafe(device.start(), self._loop)

        # Create output via factory
        if self._output_factory:
            try:
                self._output_factory(device)
            except Exception as e:
                log_warning("DeviceManager", f"Output factory error: {e}")

        # Publish device added event
        event_bus.publish(device_added(device.device_id, device.to_dict()))

    def _on_airplay_lost(self, airplay_id: str):
        """
        Handle AirPlay device loss.

        Args:
            airplay_id: AirPlay device identifier
        """
        device_id = self._airplay_map.get(airplay_id)
        if not device_id:
            return

        device = self._devices.get(device_id)
        if device:
            device.connected = False
            log_info("DeviceManager", f"AirPlay device disconnected: {device.device_name}")

            # Publish disconnected event
            event_bus.publish(device_disconnected(device_id))

    def _create_server_speaker(self):
        """Create Server Speaker virtual device for local audio output."""
        device = VirtualDevice.create_server_speaker()
        device.connected = True

        # Load saved DSP config
        self._load_device_config(device)

        self._devices[device.device_id] = device

        log_info("DeviceManager", f"Created virtual device: {device.device_name} (id: {device.device_id})")

        # Start device (subscribe to events)
        asyncio.run_coroutine_threadsafe(device.start(), self._loop)

        # Create output via factory
        if self._output_factory:
            try:
                self._output_factory(device)
            except Exception as e:
                log_warning("DeviceManager", f"Output factory error: {e}")

        # Publish device added event
        event_bus.publish(device_added(device.device_id, device.to_dict()))

    async  def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """
        Start device manager.

        Args:
            loop: Event loop to use
        """
        if self._running:
            return

        self._running = True
        self._loop = loop or asyncio.get_event_loop()

        # Set event bus loop
        event_bus.set_loop(self._loop)

        log_info("DeviceManager", "Starting device manager")

        # Create Server Speaker device if enabled
        if ENABLE_SERVER_SPEAKER:
            log_info("DeviceManager", "Server Speaker enabled in config")
            log_audio_devices()

            if has_audio_output_device():
                self._create_server_speaker()
            else:
                log_warning("DeviceManager",
                           "Server Speaker enabled but no audio output device found - skipping creation")
        else:
            log_info("DeviceManager", "Server Speaker disabled in config")

        # Start AirPlay scanner
        self._scanner.start(self._loop)

        # Perform initial scan
        log_info("DeviceManager", "Performing initial AirPlay device scan...")
        devices = await self._scanner.scan_once()
        for device_info in devices:
            self._on_airplay_found(device_info)

        log_info("DeviceManager", f"Device manager started with {len(self._devices)} device(s)")

    def stop(self):
        """Stop device manager."""
        if not self._running:
            return

        self._running = False
        self._scanner.stop()

        # Shutdown all devices
        for device in self._devices.values():
            asyncio.run_coroutine_threadsafe(device.shutdown(), self._loop)

        log_info("DeviceManager", "Device manager stopped")

    def get_device(self, device_id: str) -> Optional[VirtualDevice]:
        """Get virtual device by ID."""
        return self._devices.get(device_id)

    def get_device_by_uuid(self, dlna_uuid: str) -> Optional[VirtualDevice]:
        """Get virtual device by DLNA UUID."""
        for device in self._devices.values():
            if device.dlna_uuid == dlna_uuid:
                return device
        return None

    def get_device_by_airplay_id(self, airplay_id: str) -> Optional[VirtualDevice]:
        """Get virtual device by AirPlay device identifier."""
        device_id = self._airplay_map.get(airplay_id)
        if device_id:
            return self._devices.get(device_id)
        return None

    def get_all_devices(self) -> List[VirtualDevice]:
        """Get all virtual devices."""
        return list(self._devices.values())

    def get_airplay_devices(self) -> List[VirtualDevice]:
        """Get all AirPlay virtual devices."""
        return [d for d in self._devices.values() if d.device_type == "airplay"]

    def get_server_speaker_device(self) -> Optional[VirtualDevice]:
        """Get the Server Speaker virtual device."""
        for d in self._devices.values():
            if d.device_type == "server_speaker":
                return d
        return None

    def get_connected_devices(self) -> List[VirtualDevice]:
        """Get all connected virtual devices."""
        return [d for d in self._devices.values() if d.connected]

    def _load_device_config(self, device: VirtualDevice):
        """Load saved DSP configuration for a device."""
        saved_config = config_store.get_device_config(device.device_id)
        if saved_config:
            device.dsp_enabled = saved_config.get("dsp_enabled", False)
            saved_dsp = saved_config.get("dsp_config", {})
            if saved_dsp:
                device.dsp_config.update(saved_dsp)
            log_info("DeviceManager", f"Loaded saved DSP config for: {device.device_name}")

    def to_dict(self) -> List[Dict[str, Any]]:
        """Convert all devices to dictionary list for JSON serialization."""
        return [device.to_dict() for device in self._devices.values()]

    def is_running(self) -> bool:
        """Check if device manager is running."""
        return self._running
