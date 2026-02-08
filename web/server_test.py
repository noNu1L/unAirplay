"""
Test API Server - Debug and testing endpoints

This module provides test/debug APIs for development and troubleshooting.
These APIs are separate from the main server to keep production code clean.

测试 API 服务器 - 用于开发和调试的端点
"""
import time
import aiohttp
from typing import TYPE_CHECKING
from aiohttp import web
from xml.sax.saxutils import escape as xml_escape

from core.utils import log_info, log_warning
from core.event_bus import event_bus
from core.events import cmd_stop, cmd_pause

if TYPE_CHECKING:
    from device.device_manager import DeviceManager
    from source.dlna_service import DLNAService


class TestAPIRoutes:
    """
    Test API routes for debugging and development.

    Usage:
        test_api = TestAPIRoutes(device_manager, dlna_service)
        test_api.register_routes(app)
    """

    def __init__(self, device_manager: "DeviceManager", dlna_service: "DLNAService" = None):
        """
        Initialize test API routes.

        Args:
            device_manager: Device manager instance
            dlna_service: DLNA service instance (for querying subscribers)
        """
        self._device_manager = device_manager
        self._dlna_service = dlna_service

    def register_routes(self, app: web.Application):
        """Register test API routes to the application"""
        # Playback Control API
        app.router.add_post("/api/device/{device_id}/playback/stop", self.handle_playback_stop)
        app.router.add_post("/api/device/{device_id}/playback/pause", self.handle_playback_pause)

        # DLNA Debug API
        app.router.add_get("/api/dlna/subscribers", self.handle_get_dlna_subscribers)
        app.router.add_get("/api/device/{device_id}/subscribers", self.handle_get_device_subscribers)
        app.router.add_post("/api/device/{device_id}/subscriber/{sid}/notify/stop", self.handle_notify_subscriber_stop)
        app.router.add_post("/api/device/{device_id}/subscriber/{sid}/notify/{state}", self.handle_notify_subscriber_state)

        # Legacy Test API
        app.router.add_post("/api/device/{device_id}/test/stop", self.handle_test_stop)

    # ============== Playback Control API ==============

    async def handle_playback_stop(self, request: web.Request):
        """
        Send STOP command to a device.
        Stops playback and notifies all DLNA subscribers.

        向指定设备发送 STOP 命令，停止播放并通知所有 DLNA 订阅客户端。
        """
        device_id = request.match_info.get("device_id")
        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        event_bus.publish(cmd_stop(device_id))

        log_info("TestAPI", f"STOP command sent: {device.device_name}")
        return web.json_response({
            "status": "ok",
            "device_id": device_id,
            "device_name": device.device_name,
            "action": "stop"
        })

    async def handle_playback_pause(self, request: web.Request):
        """
        Send PAUSE command to a device.
        Pauses playback and notifies all DLNA subscribers.

        向指定设备发送 PAUSE 命令，暂停播放并通知所有 DLNA 订阅客户端。
        """
        device_id = request.match_info.get("device_id")
        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        event_bus.publish(cmd_pause(device_id))

        log_info("TestAPI", f"PAUSE command sent: {device.device_name}")
        return web.json_response({
            "status": "ok",
            "device_id": device_id,
            "device_name": device.device_name,
            "action": "pause"
        })

    # ============== DLNA Debug API ==============

    async def handle_get_dlna_subscribers(self, request: web.Request):
        """
        Get all DLNA subscribers across all devices.

        获取所有设备的 DLNA 订阅客户端列表。
        """
        if not self._dlna_service:
            return web.json_response({"error": "DLNA service not available"}, status=503)

        now = time.time()
        result = {}

        # Iterate through all devices and their subscribers
        for device_id, subscribers in self._dlna_service._subscribers.items():
            device = self._device_manager.get_device(device_id)
            device_name = device.device_name if device else "Unknown"

            device_subs = []
            for sid, sub_info in subscribers.items():
                device_subs.append({
                    "sid": sid,
                    "callback": sub_info.get("callback", ""),
                    "service": sub_info.get("service", ""),
                    "timeout": sub_info.get("timeout", 0),
                    "expires_in": int(sub_info.get("expires", 0) - now),
                    "seq": sub_info.get("seq", 0),
                    "expired": sub_info.get("expires", 0) < now,
                    "client_ip": sub_info.get("client_ip", ""),
                    "last_play_url": sub_info.get("last_play_url", ""),
                })

            if device_subs:
                result[device_id] = {
                    "device_name": device_name,
                    "subscribers": device_subs
                }

        return web.json_response({
            "total_devices": len(result),
            "total_subscribers": sum(len(d["subscribers"]) for d in result.values()),
            "devices": result
        })

    async def handle_get_device_subscribers(self, request: web.Request):
        """
        Get DLNA subscribers for a specific device.

        获取指定设备的 DLNA 订阅客户端列表。
        """
        if not self._dlna_service:
            return web.json_response({"error": "DLNA service not available"}, status=503)

        device_id = request.match_info.get("device_id")
        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        now = time.time()
        subscribers = self._dlna_service._subscribers.get(device_id, {})

        subs_list = []
        for sid, sub_info in subscribers.items():
            subs_list.append({
                "sid": sid,
                "callback": sub_info.get("callback", ""),
                "service": sub_info.get("service", ""),
                "timeout": sub_info.get("timeout", 0),
                "expires_in": int(sub_info.get("expires", 0) - now),
                "seq": sub_info.get("seq", 0),
                "expired": sub_info.get("expires", 0) < now,
                "client_ip": sub_info.get("client_ip", ""),
                "last_play_url": sub_info.get("last_play_url", ""),
            })

        return web.json_response({
            "device_id": device_id,
            "device_name": device.device_name,
            "subscriber_count": len(subs_list),
            "subscribers": subs_list
        })

    async def handle_notify_subscriber_stop(self, request: web.Request):
        """
        Send STOP notification to a specific DLNA subscriber.
        Does NOT actually stop playback, only sends UPnP GENA NOTIFY.

        向指定的 DLNA 订阅者发送 STOP 通知。
        不会实际停止播放，仅发送 UPnP GENA NOTIFY 事件。
        用于测试 DLNA 客户端是否正确响应 STOP 事件。
        """
        if not self._dlna_service:
            return web.json_response({"error": "DLNA service not available"}, status=503)

        device_id = request.match_info.get("device_id")
        sid = request.match_info.get("sid")

        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        # Find subscriber
        subscribers = self._dlna_service._subscribers.get(device_id, {})
        sub_info = subscribers.get(sid)
        if not sub_info:
            return web.json_response({"error": "Subscriber not found"}, status=404)

        callback_url = sub_info.get("callback", "")
        if not callback_url:
            return web.json_response({"error": "Subscriber has no callback URL"}, status=400)

        # Build STOP event XML
        event_xml = self._build_stop_event_xml(device)

        # Get and increment sequence number
        seq = sub_info.get("seq", 0)
        sub_info["seq"] = seq + 1

        # Send NOTIFY to subscriber
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "NT": "upnp:event",
                    "NTS": "upnp:propchange",
                    "SID": sid,
                    "SEQ": str(seq),
                    "Content-Type": "text/xml; charset=utf-8",
                }
                async with session.request(
                    "NOTIFY",
                    callback_url,
                    headers=headers,
                    data=event_xml,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    log_info("TestAPI", f"STOP notify sent to {callback_url} -> {resp.status}")
                    return web.json_response({
                        "status": "ok",
                        "device_id": device_id,
                        "device_name": device.device_name,
                        "sid": sid,
                        "callback": callback_url,
                        "response_status": resp.status,
                        "seq": seq
                    })
        except Exception as e:
            log_warning("TestAPI", f"Failed to send STOP notify: {e}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "callback": callback_url
            }, status=500)

    def _build_stop_event_xml(self, device) -> str:
        """Build UPnP event XML with STOPPED state"""
        return self._build_state_event_xml(device, "STOPPED", "OK", "Play")

    def _build_state_event_xml(self, device, transport_state: str, transport_status: str = "OK", actions: str = "") -> str:
        """
        Build UPnP event XML with custom state.

        Args:
            device: Virtual device
            transport_state: STOPPED, PLAYING, PAUSED_PLAYBACK, TRANSITIONING, NO_MEDIA_PRESENT
            transport_status: OK, ERROR_OCCURRED
            actions: Available actions (Play, Pause, Stop, Seek)
        """
        uri_escaped = xml_escape(device.play_url) if device.play_url else ""

        # Default actions based on state
        if not actions:
            if transport_state == "PLAYING":
                actions = "Pause,Stop,Seek"
            elif transport_state == "PAUSED_PLAYBACK":
                actions = "Play,Stop"
            elif transport_state == "STOPPED":
                actions = "Play"
            elif transport_state == "NO_MEDIA_PRESENT":
                actions = ""
            else:
                actions = "Stop"

        # For NO_MEDIA_PRESENT, clear URIs
        if transport_state == "NO_MEDIA_PRESENT":
            uri_escaped = ""

        inner_xml = f'''<Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/">
  <InstanceID val="0">
    <TransportState val="{transport_state}"/>
    <TransportStatus val="{transport_status}"/>
    <CurrentTransportActions val="{actions}"/>
    <AVTransportURI val="{uri_escaped}"/>
    <CurrentTrackURI val="{uri_escaped}"/>
  </InstanceID>
</Event>'''

        return f'''<?xml version="1.0" encoding="UTF-8"?>
<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">
  <e:property>
    <LastChange>{xml_escape(inner_xml)}</LastChange>
  </e:property>
</e:propertyset>'''

    async def handle_notify_subscriber_state(self, request: web.Request):
        """
        Send custom state notification to a specific DLNA subscriber.
        用于测试不同状态通知对 DLNA 客户端的影响。

        Supported states:
            - stopped: TransportState=STOPPED
            - playing: TransportState=PLAYING
            - paused: TransportState=PAUSED_PLAYBACK
            - no_media: TransportState=NO_MEDIA_PRESENT (clears URIs)
            - error: TransportStatus=ERROR_OCCURRED
        """
        if not self._dlna_service:
            return web.json_response({"error": "DLNA service not available"}, status=503)

        device_id = request.match_info.get("device_id")
        sid = request.match_info.get("sid")
        state = request.match_info.get("state", "").lower()

        # Map state parameter to UPnP values
        state_map = {
            "stopped": ("STOPPED", "OK"),
            "playing": ("PLAYING", "OK"),
            "paused": ("PAUSED_PLAYBACK", "OK"),
            "no_media": ("NO_MEDIA_PRESENT", "OK"),
            "error": ("STOPPED", "ERROR_OCCURRED"),
        }

        if state not in state_map:
            return web.json_response({
                "error": f"Unknown state: {state}",
                "supported_states": list(state_map.keys())
            }, status=400)

        transport_state, transport_status = state_map[state]

        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        # Find subscriber
        subscribers = self._dlna_service._subscribers.get(device_id, {})
        sub_info = subscribers.get(sid)
        if not sub_info:
            return web.json_response({"error": "Subscriber not found"}, status=404)

        callback_url = sub_info.get("callback", "")
        if not callback_url:
            return web.json_response({"error": "Subscriber has no callback URL"}, status=400)

        # Build event XML with custom state
        event_xml = self._build_state_event_xml(device, transport_state, transport_status)

        # Get and increment sequence number
        seq = sub_info.get("seq", 0)
        sub_info["seq"] = seq + 1

        # Send NOTIFY to subscriber
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "NT": "upnp:event",
                    "NTS": "upnp:propchange",
                    "SID": sid,
                    "SEQ": str(seq),
                    "Content-Type": "text/xml; charset=utf-8",
                }
                async with session.request(
                    "NOTIFY",
                    callback_url,
                    headers=headers,
                    data=event_xml,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    log_info("TestAPI", f"{state.upper()} notify sent to {callback_url} -> {resp.status}")
                    return web.json_response({
                        "status": "ok",
                        "device_id": device_id,
                        "device_name": device.device_name,
                        "sid": sid,
                        "callback": callback_url,
                        "state_sent": state,
                        "transport_state": transport_state,
                        "transport_status": transport_status,
                        "response_status": resp.status,
                        "seq": seq
                    })
        except Exception as e:
            log_warning("TestAPI", f"Failed to send {state} notify: {e}")
            return web.json_response({
                "status": "error",
                "error": str(e),
                "callback": callback_url
            }, status=500)

    # ============== Legacy Test API ==============

    async def handle_test_stop(self, request: web.Request):
        """
        Test endpoint: Send STOP command to a device.
        This triggers the full event flow:
        1. VirtualDevice receives CMD_STOP and stops playback
        2. VirtualDevice publishes STATE_CHANGED with "STOPPED"
        3. DLNAService notifies all subscribers via UPnP GENA NOTIFY

        测试端点：向设备发送 STOP 命令。
        用于测试 DLNA 客户端是否正确响应 STOP 事件（如播放下一首）。

        Deprecated: Use /api/device/{device_id}/playback/stop instead.
        """
        device_id = request.match_info.get("device_id")
        device = self._device_manager.get_device(device_id)
        if not device:
            return web.json_response({"error": "Device not found"}, status=404)

        event_bus.publish(cmd_stop(device_id))

        log_info("TestAPI", f"Test STOP sent: {device.device_name}")
        return web.json_response({
            "status": "ok",
            "message": f"STOP command sent to {device.device_name}, DLNA subscribers notified"
        })
