"""
AirPlayScanner - Discover AirPlay devices on the network
"""
import asyncio
import sys
from typing import List, Dict, Any, Optional, Callable

import pyatv
from pyatv.const import Protocol

from core.utils import log_info, log_debug, log_warning
from config import AIRPLAY_SCAN_TIMEOUT, AIRPLAY_SCAN_INTERVAL


class AirPlayScanner:
    """
    AirPlay device scanner.

    Periodically scans the network for AirPlay devices and notifies
    when devices are discovered or lost.
    """

    def __init__(
        self,
        on_device_found: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_device_lost: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize AirPlay scanner.

        Args:
            on_device_found: Callback when a new device is found
            on_device_lost: Callback when a device is lost
        """
        self._on_device_found = on_device_found
        self._on_device_lost = on_device_lost

        self._devices: Dict[str, Dict[str, Any]] = {}  # identifier -> device info
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def scan_once(self) -> List[Dict[str, Any]]:
        """
        Perform a single scan for AirPlay devices.

        Returns:
            List of discovered device info dictionaries
        """
        log_debug("AirPlayScanner", f"Starting device scan (timeout={AIRPLAY_SCAN_TIMEOUT}s)")

        try:
            # Scan for AirPlay devices
            atvs = await pyatv.scan(
                loop=self._loop or asyncio.get_event_loop(),
                timeout=AIRPLAY_SCAN_TIMEOUT,
                protocol=Protocol.AirPlay,
            )

            discovered = []
            for atv in atvs:
                # Extract device model (convert enum to string)
                model = "Unknown"
                if atv.device_info and atv.device_info.model:
                    model = str(atv.device_info.model).split(".")[-1]

                device_info = {
                    "name": atv.name,
                    "identifier": atv.identifier,
                    "address": str(atv.address),
                    "model": model,
                    "services": [
                        str(service.protocol).split(".")[-1]
                        for service in atv.services
                    ],
                }
                discovered.append(device_info)

                log_debug(
                    "AirPlayScanner",
                    f"Found device: {device_info['name']} ({device_info['address']}) [{device_info['model']}]"
                )

            log_debug("AirPlayScanner", f"Scan complete, found {len(discovered)} device(s)")
            return discovered

        except Exception as e:
            log_warning("AirPlayScanner", f"Scan failed: {e}")
            return []

    async def _scan_loop(self):
        """
        Continuous scanning loop.
        """
        log_info("AirPlayScanner", "Starting periodic device scanning")

        while self._running:
            try:
                # Perform scan
                discovered = await self.scan_once()

                # Build set of discovered identifiers
                discovered_ids = {d["identifier"] for d in discovered}
                current_ids = set(self._devices.keys())

                # Check for new devices
                for device_info in discovered:
                    identifier = device_info["identifier"]
                    if identifier not in self._devices:
                        # New device found
                        self._devices[identifier] = device_info
                        log_info(
                            "AirPlayScanner",
                            f"New device discovered: {device_info['name']} ({device_info['address']})"
                        )
                        if self._on_device_found:
                            try:
                                self._on_device_found(device_info)
                            except Exception as e:
                                log_warning("AirPlayScanner", f"on_device_found callback error: {e}")
                    else:
                        # Update existing device info (address may change)
                        self._devices[identifier] = device_info

                # Check for lost devices
                lost_ids = current_ids - discovered_ids
                for identifier in lost_ids:
                    device_info = self._devices.pop(identifier, None)
                    if device_info:
                        log_info(
                            "AirPlayScanner",
                            f"Device lost: {device_info['name']} ({device_info['address']})"
                        )
                        if self._on_device_lost:
                            try:
                                self._on_device_lost(identifier)
                            except Exception as e:
                                log_warning("AirPlayScanner", f"on_device_lost callback error: {e}")

                # Wait for next scan interval
                await asyncio.sleep(AIRPLAY_SCAN_INTERVAL)

            except asyncio.CancelledError:
                log_debug("AirPlayScanner", "Scan loop cancelled")
                break
            except Exception as e:
                log_warning("AirPlayScanner", f"Scan loop error: {e}")
                await asyncio.sleep(AIRPLAY_SCAN_INTERVAL)

        log_info("AirPlayScanner", "Periodic scanning stopped")

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """
        Start periodic scanning.

        Args:
            loop: Event loop to use (optional)
        """
        if self._running:
            log_debug("AirPlayScanner", "Scanner already running")
            return

        self._running = True
        self._loop = loop or asyncio.get_event_loop()
        self._scan_task = asyncio.create_task(self._scan_loop())
        log_info("AirPlayScanner", "Scanner started")

    def stop(self):
        """
        Stop periodic scanning.
        """
        if not self._running:
            return

        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            self._scan_task = None

        log_info("AirPlayScanner", "Scanner stopped")

    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Get list of currently discovered devices.

        Returns:
            List of device info dictionaries
        """
        return list(self._devices.values())

    def get_device(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get device info by identifier.

        Args:
            identifier: Device identifier

        Returns:
            Device info dictionary or None
        """
        return self._devices.get(identifier)

    def is_running(self) -> bool:
        """
        Check if scanner is running.

        Returns:
            True if running
        """
        return self._running
