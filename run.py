"""
 Main Entry Point

Event-driven architecture:
- VirtualDevice subscribes to command events and executes them
- DLNAService/WebServer publish command events
- ConfigStore subscribes to DSP events and auto-saves
- DeviceManager manages device lifecycle and creates outputs

Features:
1. Auto-discover AirPlay devices on the network
2. Create virtual DLNA renderers for each AirPlay device
3. Create Server Speaker virtual device for local audio output
4. Support passthrough mode (no decode/encode) and DSP mode
5. Web control panel for monitoring and DSP configuration
"""
import asyncio
import signal
import sys
from typing import Optional

from core.utils import log_info, set_log_level, LOG_LEVEL_DEBUG, LOG_LEVEL_INFO
from core.ffmpeg_checker import check_ffmpeg_or_exit
from config import APP_NAME, APP_VERSION, DEBUG

from device.device_manager import DeviceManager
from device.virtual_device import VirtualDevice
from source.dlna_service import DLNAService
from output.airplay_output import AirPlayOutputManager
from output.server_speaker import ServerSpeakerOutput
from enhancer.dsp_numpy2 import NumpyEnhancer as ScipyEnhancer
from web.server import WebServer


class UnAirplay:
    """
    Main application for UnAirplay.

    Uses event-driven architecture for decoupled communication.
    """

    def __init__(self):
        """Initialize the bridge"""
        # Device management
        self._device_manager = DeviceManager()

        # DLNA service (communicates via events)
        self._dlna_service = DLNAService(self._device_manager)

        # Output managers
        self._airplay_manager = AirPlayOutputManager()
        self._server_speaker: Optional[ServerSpeakerOutput] = None

        # Web server (communicates via events)
        self._web_server = WebServer(self._device_manager, self._dlna_service)

        # Event loop reference
        self._loop = None
        self._running = False

        # Set output factory for device manager
        self._device_manager.set_output_factory(self._create_output_for_device)

    def _create_output_for_device(self, device: VirtualDevice):
        """
        Create and attach output to a virtual device.

        This is called by DeviceManager when a new device is created.

        Args:
            device: Virtual device that needs an output
        """
        log_info("Bridge", f"Creating output for: {device.device_name} (type: {device.device_type})")

        # Create DSP enhancer
        enhancer = ScipyEnhancer()
        device.set_enhancer(enhancer)

        # Create output based on device type
        if device.device_type == "airplay":
            # Create AirPlay output
            output = self._airplay_manager.create_output(device, enhancer)
            device.set_output(output)

            # Start output background tasks
            output.start_background_loop()
            output.run_coroutine(output.connect())

        elif device.device_type == "server_speaker":
            # Create Server Speaker output
            self._server_speaker = ServerSpeakerOutput(device, enhancer)
            device.set_output(self._server_speaker)

            # Start output
            self._server_speaker.start()

    async def run(self):
        """Run the main application"""
        self._loop = asyncio.get_event_loop()
        self._running = True

        # Print startup banner
        print(" ")
        print(f"  {APP_NAME} v{APP_VERSION}")
        print(" ")

        # Start device manager (scans for AirPlay devices, creates virtual devices)
        await self._device_manager.start(self._loop)

        # Start DLNA service (subscribes to state events, publishes commands)
        await self._dlna_service.start()

        # Start web server (publishes DSP commands)
        await self._web_server.start()

        log_info("Bridge", "All services started. Event-driven system ready.")

        # Keep running
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    async def shutdown(self):
        """Shutdown the application"""
        log_info("Bridge", "Shutting down...")
        self._running = False

        # Stop services
        await self._dlna_service.stop()
        self._device_manager.stop()
        self._airplay_manager.cleanup_all()
        if self._server_speaker:
            self._server_speaker.cleanup()

        log_info("Bridge", "Shutdown complete")


def main():
    """Main entry point"""

    # Set log level based on DEBUG configuration
    if DEBUG:
        set_log_level(LOG_LEVEL_DEBUG)
        log_info("Startup", "DEBUG mode enabled - Log level set to DEBUG")
    else:
        set_log_level(LOG_LEVEL_INFO)

    # Check FFmpeg availability before starting
    # 在启动前检查 FFmpeg 可用性
    check_ffmpeg_or_exit("Startup")

    app = UnAirplay()

    def signal_handler(sig, frame):
        print()
        asyncio.create_task(app.shutdown())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Windows event loop policy
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
