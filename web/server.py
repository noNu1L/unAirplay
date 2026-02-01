"""
Web Server - API and frontend for DLNA to AirPlay bridge

This module provides web control panel and REST API.
It communicates via events instead of directly modifying devices.
"""
import copy
import os
from typing import TYPE_CHECKING
from aiohttp import web

from core.utils import log_info
from core.event_bus import event_bus
from core.events import cmd_set_dsp, cmd_reset_dsp
from config import LOCAL_IP, WEB_PORT, DEFAULT_DSP_CONFIG

if TYPE_CHECKING:
    from device.device_manager import DeviceManager


class WebServer:
    """Web control panel and API server"""

    def __init__(self, device_manager: "DeviceManager"):
        """
        Initialize web server.

        Args:
            device_manager: Device manager instance
        """
        self._device_manager = device_manager
        self._static_dir = os.path.join(os.path.dirname(__file__), "static")

    # ============== Page Routes ==============

    async def handle_index(self, request: web.Request):
        """Serve main page"""
        html_path = os.path.join(self._static_dir, "index.html")
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            return web.Response(text=html_content, content_type='text/html', charset='utf-8')
        except FileNotFoundError:
            return web.Response(text="index.html not found", status=404)

    # ============== Device API ==============

    async def handle_get_devices(self, request: web.Request):
        """Get all virtual devices with state"""
        return web.json_response(self._device_manager.to_dict())

    async def handle_get_device(self, request: web.Request):
        """Get single device info"""
        device_id = request.match_info.get("device_id")
        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)
        return web.json_response(device.to_dict())

    # ============== DSP API ==============

    async def handle_set_dsp(self, request: web.Request):
        """Set DSP configuration for a device"""
        device_id = request.match_info.get("device_id")
        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        try:
            data = await request.json()
            enabled = data.get("enabled", False)
            config = data.get("config", {})

            # Publish DSP configuration command event
            event_bus.publish(cmd_set_dsp(device_id, enabled, config))

            return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_reset_dsp(self, request: web.Request):
        """Reset DSP to defaults for a device"""
        device_id = request.match_info.get("device_id")
        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        # Publish reset DSP command event
        event_bus.publish(cmd_reset_dsp(device_id))

        log_info("WebServer", f"DSP reset to defaults: {device.device_name}")
        return web.json_response({"status": "ok"})

    # ============== Static Files ==============

    async def handle_static(self, request: web.Request):
        """Serve static files"""
        filename = request.match_info.get("filename", "")
        filepath = os.path.join(self._static_dir, filename)

        if not os.path.isfile(filepath):
            return web.Response(status=404, text="File not found")

        # Determine content type
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            ".html": "text/html",
            ".css": "text/css",
            ".js": "application/javascript",
            ".json": "application/json",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".svg": "image/svg+xml",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        with open(filepath, "rb") as f:
            return web.Response(body=f.read(), content_type=content_type)

    # ============== Application Setup ==============

    def create_app(self) -> web.Application:
        """Create web application with routes"""
        app = web.Application()

        # Frontend
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/static/{filename:.*}", self.handle_static)

        # Device API
        app.router.add_get("/api/devices", self.handle_get_devices)
        app.router.add_get("/api/device/{device_id}", self.handle_get_device)

        # DSP API
        app.router.add_post("/api/device/{device_id}/dsp", self.handle_set_dsp)
        app.router.add_post("/api/device/{device_id}/dsp/reset", self.handle_reset_dsp)

        return app

    async def start(self):
        """Start web server"""
        app = self.create_app()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
        await site.start()
        log_info("WebServer", f"Web panel started: http://{LOCAL_IP}:{WEB_PORT}")
