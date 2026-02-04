"""
DLNA Service - Multi-device SSDP + HTTP Service with single port routing

There are currently two DLNA implementation methods:
1.the client establishes a DLNA streaming media source service for playback.
2.the client provides a network URL as the playback source.

目前有两种 DLNA 实现方式:
1.一种是客户端建立一个 DLNA 流媒体源服务以进行播放
2.一种是客户端提供一个网络 URL 作为播放源

如网易云音乐 安卓版:
1.在APP外开DLNA来推送的话,会建立一个流媒体播放源供FFmpeg解码播放 -> CurrentURI: http://192.168.67.112:8080/upnp.flv
    这种控制权全在APP中,但是音质比较差,不到100kbps,缺失太多高频部分,所以可以使用DSP来提升听感

2.在APP内开DLNA来推送的话,APP会从DLNA发送网络URL播放源 -> CurrentURI: http://m701.music.126.net/xxx.mp3?xxx
    这种会分离控制权,由FFmpeg独立播放,APP再获取播放进度,如果切换歌曲会重新发送url资源,音质比较好,绝大多数音质都能达到320kbps


Example: NetEase Cloud Music (Android):
1. External DLNA casting (Casting from outside the app interface):
The app creates a local streaming source for FFmpeg to decode and play
 -> CurrentURI: http://192.168.67.112:8080/upnp.flv.
    Control: The app retains full control over the stream.
    Audio Quality: Poor (less than 100kbps) with significant loss of high-frequency detail.
    Solution: DSP (Digital Signal Processing) can be applied to enhance the listening experience.

2. Internal DLNA casting (Casting from within the app interface):
The app sends a direct network URL as the playback source
-> CurrentURI: http://m701.music.126.net/xxx.mp3?xxx.
    Control: Playback control is decoupled; FFmpeg handles streaming independently while the app syncs playback progress. A new URL is sent whenever the song changes.
    Audio Quality: High (mostly up to 320kbps).


DLNA属性值适配情况(安卓) 为 N 则说明客户端请求body不包含这些内容，则无法显示
DLNA attribute value compatibility (Android) If it is set to N,
 it indicates that the client's request body does not contain these contents, and thus cannot be displayed.

        NetEase Cloud Music  | QQ Music |Kugou Music|Kuwo Music|Migu Music
                    网易云音乐   QQ音乐      酷狗音乐      酷我音乐     咪咕音乐
title                  Y        Y           Y           Y            Y
album_match            Y        Y           N           N            N
artist_match           Y        Y           Y           Y            N
album_art_match        Y        Y           Y           Y            Y



"""
import asyncio
import re
import socket
import struct
import html
import time
import uuid
import aiohttp
from aiohttp import web
from typing import Optional, Dict, Any, TYPE_CHECKING
from xml.sax.saxutils import escape as xml_escape

from core.utils import log_info, log_debug, log_warning, log_error
from core.event_bus import event_bus
from core.events import (
    EventType, Event,
    cmd_play, cmd_stop, cmd_pause, cmd_seek, cmd_set_volume, cmd_set_mute
)
from core.ffprobe import probe_media, format_bitrate
from config import LOCAL_IP, HTTP_PORT, SSDP_MULTICAST_ADDR, SSDP_PORT

if TYPE_CHECKING:
    from device.device_manager import DeviceManager
    from device.virtual_device import VirtualDevice


# ============== XML Templates ==============

def get_device_xml(device: "VirtualDevice") -> str:
    """Generate Device Description XML for a virtual device"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>
    <friendlyName>{device.device_name}</friendlyName>
    <manufacturer>DLNA Bridge</manufacturer>
    <modelName>unAirplay</modelName>
    <modelNumber>2.0</modelNumber>
    <UDN>{device.dlna_uuid}</UDN>
    <serviceList>
      <service>
        <serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:AVTransport</serviceId>
        <SCPDURL>/device/{device.device_id}/AVTransport.xml</SCPDURL>
        <controlURL>/device/{device.device_id}/ctl/AVTransport</controlURL>
        <eventSubURL>/device/{device.device_id}/evt/AVTransport</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId>
        <SCPDURL>/device/{device.device_id}/RenderingControl.xml</SCPDURL>
        <controlURL>/device/{device.device_id}/ctl/RenderingControl</controlURL>
        <eventSubURL>/device/{device.device_id}/evt/RenderingControl</eventSubURL>
      </service>
      <service>
        <serviceType>urn:schemas-upnp-org:service:ConnectionManager:1</serviceType>
        <serviceId>urn:upnp-org:serviceId:ConnectionManager</serviceId>
        <SCPDURL>/device/{device.device_id}/ConnectionManager.xml</SCPDURL>
        <controlURL>/device/{device.device_id}/ctl/ConnectionManager</controlURL>
        <eventSubURL>/device/{device.device_id}/evt/ConnectionManager</eventSubURL>
      </service>
    </serviceList>
  </device>
</root>"""


AV_TRANSPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>
    <action><name>SetAVTransportURI</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>CurrentURI</name><direction>in</direction><relatedStateVariable>AVTransportURI</relatedStateVariable></argument>
      <argument><name>CurrentURIMetaData</name><direction>in</direction><relatedStateVariable>AVTransportURIMetaData</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>Play</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Speed</name><direction>in</direction><relatedStateVariable>TransportPlaySpeed</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>Stop</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>Pause</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>Seek</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Unit</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SeekMode</relatedStateVariable></argument>
      <argument><name>Target</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_SeekTarget</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>GetPositionInfo</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Track</name><direction>out</direction><relatedStateVariable>CurrentTrack</relatedStateVariable></argument>
      <argument><name>TrackDuration</name><direction>out</direction><relatedStateVariable>CurrentTrackDuration</relatedStateVariable></argument>
      <argument><name>TrackMetaData</name><direction>out</direction><relatedStateVariable>CurrentTrackMetaData</relatedStateVariable></argument>
      <argument><name>TrackURI</name><direction>out</direction><relatedStateVariable>CurrentTrackURI</relatedStateVariable></argument>
      <argument><name>RelTime</name><direction>out</direction><relatedStateVariable>RelativeTimePosition</relatedStateVariable></argument>
      <argument><name>AbsTime</name><direction>out</direction><relatedStateVariable>AbsoluteTimePosition</relatedStateVariable></argument>
      <argument><name>RelCount</name><direction>out</direction><relatedStateVariable>RelativeCounterPosition</relatedStateVariable></argument>
      <argument><name>AbsCount</name><direction>out</direction><relatedStateVariable>AbsoluteCounterPosition</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>GetTransportInfo</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>CurrentTransportState</name><direction>out</direction><relatedStateVariable>TransportState</relatedStateVariable></argument>
      <argument><name>CurrentTransportStatus</name><direction>out</direction><relatedStateVariable>TransportStatus</relatedStateVariable></argument>
      <argument><name>CurrentSpeed</name><direction>out</direction><relatedStateVariable>TransportPlaySpeed</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>GetMediaInfo</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>NrTracks</name><direction>out</direction><relatedStateVariable>NumberOfTracks</relatedStateVariable></argument>
      <argument><name>MediaDuration</name><direction>out</direction><relatedStateVariable>CurrentMediaDuration</relatedStateVariable></argument>
      <argument><name>CurrentURI</name><direction>out</direction><relatedStateVariable>AVTransportURI</relatedStateVariable></argument>
      <argument><name>CurrentURIMetaData</name><direction>out</direction><relatedStateVariable>AVTransportURIMetaData</relatedStateVariable></argument>
      <argument><name>NextURI</name><direction>out</direction><relatedStateVariable>NextAVTransportURI</relatedStateVariable></argument>
      <argument><name>NextURIMetaData</name><direction>out</direction><relatedStateVariable>NextAVTransportURIMetaData</relatedStateVariable></argument>
      <argument><name>PlayMedium</name><direction>out</direction><relatedStateVariable>PlaybackStorageMedium</relatedStateVariable></argument>
      <argument><name>RecordMedium</name><direction>out</direction><relatedStateVariable>RecordStorageMedium</relatedStateVariable></argument>
      <argument><name>WriteStatus</name><direction>out</direction><relatedStateVariable>RecordMediumWriteStatus</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>GetCurrentTransportActions</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Actions</name><direction>out</direction><relatedStateVariable>CurrentTransportActions</relatedStateVariable></argument>
    </argumentList></action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_InstanceID</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>AVTransportURI</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>AVTransportURIMetaData</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>TransportState</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>TransportStatus</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>TransportPlaySpeed</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>CurrentTransportActions</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_SeekMode</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_SeekTarget</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>CurrentTrack</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>CurrentTrackDuration</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>CurrentTrackMetaData</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>CurrentTrackURI</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>RelativeTimePosition</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>AbsoluteTimePosition</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>RelativeCounterPosition</name><dataType>i4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>AbsoluteCounterPosition</name><dataType>i4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>NumberOfTracks</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>CurrentMediaDuration</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>NextAVTransportURI</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>NextAVTransportURIMetaData</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>PlaybackStorageMedium</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>RecordStorageMedium</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>RecordMediumWriteStatus</name><dataType>string</dataType></stateVariable>
  </serviceStateTable>
</scpd>"""

RENDERING_CONTROL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>
    <action><name>GetVolume</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Channel</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Channel</relatedStateVariable></argument>
      <argument><name>CurrentVolume</name><direction>out</direction><relatedStateVariable>Volume</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>SetVolume</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Channel</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Channel</relatedStateVariable></argument>
      <argument><name>DesiredVolume</name><direction>in</direction><relatedStateVariable>Volume</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>GetMute</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Channel</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Channel</relatedStateVariable></argument>
      <argument><name>CurrentMute</name><direction>out</direction><relatedStateVariable>Mute</relatedStateVariable></argument>
    </argumentList></action>
    <action><name>SetMute</name><argumentList>
      <argument><name>InstanceID</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_InstanceID</relatedStateVariable></argument>
      <argument><name>Channel</name><direction>in</direction><relatedStateVariable>A_ARG_TYPE_Channel</relatedStateVariable></argument>
      <argument><name>DesiredMute</name><direction>in</direction><relatedStateVariable>Mute</relatedStateVariable></argument>
    </argumentList></action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_InstanceID</name><dataType>ui4</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>A_ARG_TYPE_Channel</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>Volume</name><dataType>ui2</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>Mute</name><dataType>boolean</dataType></stateVariable>
  </serviceStateTable>
</scpd>"""

CONNECTION_MANAGER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<scpd xmlns="urn:schemas-upnp-org:service-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <actionList>
    <action><name>GetProtocolInfo</name><argumentList>
      <argument><name>Source</name><direction>out</direction><relatedStateVariable>SourceProtocolInfo</relatedStateVariable></argument>
      <argument><name>Sink</name><direction>out</direction><relatedStateVariable>SinkProtocolInfo</relatedStateVariable></argument>
    </argumentList></action>
  </actionList>
  <serviceStateTable>
    <stateVariable sendEvents="no"><name>SourceProtocolInfo</name><dataType>string</dataType></stateVariable>
    <stateVariable sendEvents="no"><name>SinkProtocolInfo</name><dataType>string</dataType></stateVariable>
  </serviceStateTable>
</scpd>"""

SINK_FORMATS = ",".join([
    "http-get:*:audio/flac:*",
    "http-get:*:audio/x-flac:*",
    "http-get:*:audio/wav:*",
    "http-get:*:audio/x-wav:*",
    "http-get:*:audio/L16:*",
    "http-get:*:audio/L24:*",
    "http-get:*:audio/x-aiff:*",
    "http-get:*:audio/aiff:*",
    "http-get:*:audio/x-m4a:*",
    "http-get:*:audio/m4a:*",
    "http-get:*:audio/x-ape:*",
    "http-get:*:audio/ape:*",
    "http-get:*:audio/x-dsd:*",
    "http-get:*:audio/aac:*",
    "http-get:*:audio/aacp:*",
    "http-get:*:audio/mp4:*",
    "http-get:*:audio/ogg:*",
    "http-get:*:audio/x-ogg:*",
    "http-get:*:audio/mpeg:*",
    "http-get:*:audio/mp3:*",
    "http-get:*:audio/mpeg3:*",
    "http-get:*:audio/x-mpeg:*",
    "http-get:*:audio/*:*",
])


def soap_response(action: str, service: str, params: str = "") -> str:
    """Generate SOAP Response"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body><u:{action}Response xmlns:u="urn:schemas-upnp-org:service:{service}:1">{params}</u:{action}Response></s:Body>
</s:Envelope>"""


# ============== DLNA Service ==============

class DLNAService:
    """
    DLNA Service with multi-device support.

    Uses single HTTP port with routing to handle multiple virtual devices.
    Route pattern: /device/{device_id}/...

    This is an external component that communicates via events:
    - Publishes command events (CMD_PLAY, CMD_STOP, etc.)
    - Subscribes to state events (STATE_CHANGED) for UPnP GENA notifications
    """

    def __init__(self, device_manager: "DeviceManager"):
        """
        Initialize DLNA service.

        Args:
            device_manager: Device manager instance
        """
        self._device_manager = device_manager
        self._running = False

        self._ssdp_socket = None
        self._ssdp_task = None
        self._notify_task = None
        self._runner = None

        # Per-device volume/mute state (not handled by event system yet)
        self._device_states: Dict[str, Dict[str, Any]] = {}  # device_id -> state

        # UPnP Event Subscription Management (per device)
        # {device_id: {sid: {"callback": url, "timeout": int, "expires": float, "seq": int}}}
        self._subscribers: Dict[str, Dict[str, dict]] = {}

        # Subscribe to state change events for UPnP GENA notifications
        event_bus.subscribe(EventType.STATE_CHANGED, self._on_state_changed)

    def _on_state_changed(self, event: Event):
        """
        Handle state change events from VirtualDevice.

        Sends UPnP GENA event notifications to subscribed control points.
        """
        device_id = event.device_id
        device = self._device_manager.get_device(device_id)
        if device:
            # Send UPnP event notifications
            asyncio.create_task(self._notify_subscribers(device))

    def _get_device_state(self, device_id: str) -> Dict[str, Any]:
        """Get or create device state"""
        if device_id not in self._device_states:
            self._device_states[device_id] = {
                "volume": 100,
                "muted": False,
            }
        return self._device_states[device_id]

    def _get_device_subscribers(self, device_id: str) -> Dict[str, dict]:
        """Get or create device subscribers dict"""
        if device_id not in self._subscribers:
            self._subscribers[device_id] = {}
        return self._subscribers[device_id]

    # ================= SSDP =================

    def _build_ssdp_response(self, device: "VirtualDevice", st: str) -> bytes:
        """Build SSDP response for a device"""
        location = f"http://{LOCAL_IP}:{HTTP_PORT}/device/{device.device_id}/device.xml"
        return (
            "HTTP/1.1 200 OK\r\n"
            f"LOCATION: {location}\r\n"
            f"ST: {st}\r\n"
            f"USN: {device.dlna_uuid}::{st}\r\n"
            "CACHE-CONTROL: max-age=1800\r\n"
            "SERVER: Python/unAirplay UPnP/1.0\r\n"
            "EXT:\r\n"
            "\r\n"
        ).encode()

    def _build_notify(self, device: "VirtualDevice", nt: str) -> bytes:
        """Build SSDP NOTIFY for a device"""
        location = f"http://{LOCAL_IP}:{HTTP_PORT}/device/{device.device_id}/device.xml"
        return (
            "NOTIFY * HTTP/1.1\r\n"
            f"HOST: {SSDP_MULTICAST_ADDR}:{SSDP_PORT}\r\n"
            f"NT: {nt}\r\n"
            "NTS: ssdp:alive\r\n"
            f"USN: {device.dlna_uuid}::{nt}\r\n"
            f"LOCATION: {location}\r\n"
            "CACHE-CONTROL: max-age=1800\r\n"
            "SERVER: Python/unAirplay UPnP/1.0\r\n"
            "\r\n"
        ).encode()

    async def _start_ssdp(self):
        """Start SSDP listener"""
        self._ssdp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._ssdp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._ssdp_socket.bind(("", SSDP_PORT))

        mreq = struct.pack("4s4s", socket.inet_aton(SSDP_MULTICAST_ADDR), socket.inet_aton(LOCAL_IP))
        self._ssdp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self._ssdp_socket.setblocking(False)

        usn_types = [
            "upnp:rootdevice",
            "urn:schemas-upnp-org:device:MediaRenderer:1",
            "urn:schemas-upnp-org:service:AVTransport:1",
            "urn:schemas-upnp-org:service:RenderingControl:1",
            "urn:schemas-upnp-org:service:ConnectionManager:1",
        ]

        loop = asyncio.get_event_loop()
        log_info("SSDP", "SSDP listener started")

        while self._running:
            try:
                data, addr = await loop.run_in_executor(None, lambda: self._ssdp_socket.recvfrom(4096))
                message = data.decode("utf-8", errors="ignore")

                if "M-SEARCH" in message:
                    log_debug("SSDP", f"M-SEARCH received from {addr[0]}")

                    # Respond for each virtual device
                    for device in self._device_manager.get_all_devices():
                        for st in usn_types:
                            if st in message or "ssdp:all" in message:
                                response = self._build_ssdp_response(device, st)
                                self._ssdp_socket.sendto(response, addr)

            except (BlockingIOError, OSError):
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_warning("SSDP", f"Error: {e}")
                await asyncio.sleep(1)

    async def _send_notify_periodically(self):
        """Send periodic SSDP NOTIFY messages"""
        usn_types = [
            "upnp:rootdevice",
            "urn:schemas-upnp-org:device:MediaRenderer:1",
            "urn:schemas-upnp-org:service:AVTransport:1",
            "urn:schemas-upnp-org:service:RenderingControl:1",
            "urn:schemas-upnp-org:service:ConnectionManager:1",
        ]

        while self._running:
            try:
                if self._ssdp_socket:
                    for device in self._device_manager.get_all_devices():
                        for nt in usn_types:
                            notify = self._build_notify(device, nt)
                            self._ssdp_socket.sendto(notify, (SSDP_MULTICAST_ADDR, SSDP_PORT))

                    device_count = len(self._device_manager.get_all_devices())
                    log_debug("SSDP", f"NOTIFY sent for {device_count} device(s)")

            except asyncio.CancelledError:
                break
            except Exception as e:
                log_warning("SSDP", f"NOTIFY send failed: {e}")

            await asyncio.sleep(30)

    # ================= HTTP Handlers =================

    @staticmethod
    def _parse_soap_action(body: str) -> Optional[str]:
        """Parse SOAP action name from request body"""
        match = re.search(r"<u:(\w+)", body)
        return match.group(1) if match else None

    @staticmethod
    def _decode_xml_entities(text: str) -> str:
        """Decode XML/HTML entities"""
        return html.unescape(text)

    def _get_device_from_request(self, request: web.Request) -> Optional["VirtualDevice"]:
        """Get virtual device from request path"""
        device_id = request.match_info.get("device_id")
        if not device_id:
            return None
        return self._device_manager.get_device(device_id)

    async def _handle_device_xml(self, request: web.Request):
        """Handle device description XML request"""
        device = self._get_device_from_request(request)
        if not device:
            return web.Response(status=404, text="Device not found")

        return web.Response(
            text=get_device_xml(device),
            content_type="text/xml",
            charset="utf-8"
        )

    async def _handle_av_transport_xml(self, request: web.Request):
        """Handle AVTransport service description"""
        return web.Response(text=AV_TRANSPORT_XML, content_type="text/xml", charset="utf-8")

    async def _handle_rendering_control_xml(self, request: web.Request):
        """Handle RenderingControl service description"""
        return web.Response(text=RENDERING_CONTROL_XML, content_type="text/xml", charset="utf-8")

    async def _handle_connection_manager_xml(self, request: web.Request):
        """Handle ConnectionManager service description"""
        return web.Response(text=CONNECTION_MANAGER_XML, content_type="text/xml", charset="utf-8")

    async def _handle_av_transport_ctl(self, request: web.Request):
        """Handle AVTransport control requests"""
        device = self._get_device_from_request(request)
        if not device:
            return web.Response(status=404, text="Device not found")

        body = await request.text()
        action = self._parse_soap_action(body)
        req_ip = request.remote or "unknown"

        log_debug("AVTransport", f"Action: {action} from {req_ip} for {device.device_name}")

        if action == "SetAVTransportURI":
            log_debug("SetAVTransportURI", f"body:\n{body}\n--- end ---")
            match = re.search(r"<CurrentURI>([^<]*)</CurrentURI>", body)
            if match:
                uri = self._decode_xml_entities(match.group(1))
                device.play_url = uri
                device.play_state = "TRANSITIONING"
                device.play_position = 0.0
                device.play_start_time = 0.0

                # Parse metadata
                metadata_match = re.search(r"<CurrentURIMetaData>([^<]*)</CurrentURIMetaData>", body)
                if metadata_match:
                    metadata = self._decode_xml_entities(metadata_match.group(1))
                    self._parse_metadata(device, metadata)

                # Probe media info asynchronously (non-blocking)
                asyncio.create_task(self._probe_and_update_media_info(device, uri))

            response = soap_response("SetAVTransportURI", "AVTransport")

        elif action == "Play":
            log_info("Playback", f"Play: {device.device_name}")

            event_bus.publish(cmd_play(device.device_id, device.play_url, device.play_position))
            # TODO 大文件解码Seek行为等待时间比较长,需要缓存层解决 。已加入缓存层，但未对Seek行为读取缓存
            response = soap_response("Play", "AVTransport")

        elif action == "Stop":
            log_info("Playback", f"Stop: {device.device_name}")

            # Publish stop command event
            event_bus.publish(cmd_stop(device.device_id))
            response = soap_response("Stop", "AVTransport")

        elif action == "Pause":
            log_info("Playback", f"Pause: {device.device_name}")

            # Publish pause command event
            event_bus.publish(cmd_pause(device.device_id))
            response = soap_response("Pause", "AVTransport")

        elif action == "Seek":
            # TODO 大文件解码Seek行为等待时间比较长,需要缓存层解决
            match = re.search(r"<Target>([^<]*)</Target>", body)
            if match:
                target = match.group(1)
                position = device.parse_time(target)

                # Filter: skip seek if position is same as current (Migu Music bug workaround)
                if abs(position - device.get_current_position()) < 1.0:
                    log_debug("Playback", f"Seek ignored (same position {position:.1f}s): {device.device_name}")
                else:
                    log_info("Playback", f"Seek to {target}: {device.device_name}")
                    # Publish seek command event
                    event_bus.publish(cmd_seek(device.device_id, position))
            response = soap_response("Seek", "AVTransport")

        # Some clients may frequently request this interface to obtain the playback progress,
        # such as the internal DLNA of the Android version of NetEase Cloud Music.

        # 有的客户端会频繁请求该接口, 以获取播放进度, 如安卓版本网易云音乐内部DLNA
        elif action == "GetPositionInfo":
            position_str = device.format_position()
            duration_str = device.format_duration()
            uri_escaped = xml_escape(device.play_url) if device.play_url else ""
            response = soap_response("GetPositionInfo", "AVTransport", f"""
      <Track>1</Track>
      <TrackDuration>{duration_str}</TrackDuration>
      <TrackMetaData></TrackMetaData>
      <TrackURI>{uri_escaped}</TrackURI>
      <RelTime>{position_str}</RelTime>
      <AbsTime>{position_str}</AbsTime>
      <RelCount>2147483647</RelCount>
      <AbsCount>2147483647</AbsCount>""")
            log_debug("GetPositionInfo", f"Position: {position_str}")

        elif action == "GetTransportInfo":
            response = soap_response("GetTransportInfo", "AVTransport", f"""
      <CurrentTransportState>{device.play_state}</CurrentTransportState>
      <CurrentTransportStatus>OK</CurrentTransportStatus>
      <CurrentSpeed>1</CurrentSpeed>""")

        elif action == "GetMediaInfo":
            duration_str = device.format_duration()
            uri_escaped = xml_escape(device.play_url) if device.play_url else ""
            response = soap_response("GetMediaInfo", "AVTransport", f"""
      <NrTracks>1</NrTracks>
      <MediaDuration>{duration_str}</MediaDuration>
      <CurrentURI>{uri_escaped}</CurrentURI>
      <CurrentURIMetaData></CurrentURIMetaData>
      <NextURI></NextURI>
      <NextURIMetaData></NextURIMetaData>
      <PlayMedium>NETWORK</PlayMedium>
      <RecordMedium>NOT_IMPLEMENTED</RecordMedium>
      <WriteStatus>NOT_IMPLEMENTED</WriteStatus>""")

        # [DLNA standard] GetCurrentTransportActions - return available actions based on state
        elif action == "GetCurrentTransportActions":
            # Return available actions based on current state
            if device.play_state == "PLAYING":
                actions = "Pause,Stop,Seek"
            elif device.play_state == "PAUSED_PLAYBACK":
                actions = "Play,Stop"
            elif device.play_state == "TRANSITIONING":
                actions = "Stop"
            else:  # STOPPED
                actions = "Play"
            response = soap_response("GetCurrentTransportActions", "AVTransport",
                                   f"<Actions>{actions}</Actions>")

        else:
            response = soap_response(action or "Unknown", "AVTransport")

        return web.Response(text=response, content_type="text/xml", charset="utf-8")

    async def _handle_rendering_control_ctl(self, request: web.Request):
        """Handle RenderingControl requests"""
        device = self._get_device_from_request(request)
        if not device:
            return web.Response(status=404, text="Device not found")

        body = await request.text()
        action = self._parse_soap_action(body)

        if action == "GetVolume":
            # Read from output (supports real-time volume reading)
            volume = 100  # default
            output = device.get_output()
            if output and hasattr(output, 'get_volume'):
                try:
                    volume = output.get_volume()
                except Exception as e:
                    log_debug("RenderingControl", f"Failed to get volume from output: {e}")
                    # Fall back to device cached volume if available
                    volume = device.volume if hasattr(device, 'volume') else 100

            response = soap_response("GetVolume", "RenderingControl",
                                   f"<CurrentVolume>{volume}</CurrentVolume>")

        elif action == "SetVolume":
            match = re.search(r"<DesiredVolume>(\d+)</DesiredVolume>", body)
            if match:
                volume = int(match.group(1))
                log_info("Volume", f"Volume set to {volume}: {device.device_name}")

                # Publish set volume command event
                event_bus.publish(cmd_set_volume(device.device_id, volume))
            response = soap_response("SetVolume", "RenderingControl")

        elif action == "GetMute":
            # Read from output (supports real-time mute reading)
            muted = False  # default
            output = device.get_output()
            if output and hasattr(output, 'get_mute'):
                try:
                    muted = output.get_mute()
                except Exception as e:
                    log_debug("RenderingControl", f"Failed to get mute from output: {e}")

            mute_val = "1" if muted else "0"
            response = soap_response("GetMute", "RenderingControl",
                                   f"<CurrentMute>{mute_val}</CurrentMute>")

        elif action == "SetMute":
            match = re.search(r"<DesiredMute>(\d+)</DesiredMute>", body)
            if match:
                muted = match.group(1) == "1"
                log_info("Mute", f"{'Muted' if muted else 'Unmuted'}: {device.device_name}")

                # Publish set mute command event
                event_bus.publish(cmd_set_mute(device.device_id, muted))
            response = soap_response("SetMute", "RenderingControl")

        else:
            response = soap_response(action or "Unknown", "RenderingControl")

        return web.Response(text=response, content_type="text/xml", charset="utf-8")

    async def _handle_connection_manager_ctl(self, request: web.Request):
        """Handle ConnectionManager requests"""
        response = soap_response("GetProtocolInfo", "ConnectionManager",
                               f"<Source></Source><Sink>{SINK_FORMATS}</Sink>")
        return web.Response(text=response, content_type="text/xml", charset="utf-8")

    def _parse_metadata(self, device: "VirtualDevice", metadata: str):
        """Parse and update device metadata from DIDL-Lite"""
        # Standard format: <tag>text</tag>
        title_match = re.search(r'<dc:title>([^<]+)</dc:title>', metadata)
        artist_match = re.search(r'<upnp:artist[^>]*>([^<]+)</upnp:artist>', metadata)
        album_match = re.search(r'<upnp:album>([^<]+)</upnp:album>', metadata)
        album_art_match = re.search(r'<upnp:albumArtURI>([^<]+)</upnp:albumArtURI>', metadata)
        duration_match = re.search(r'duration="([^"]+)"', metadata)

        # Kugou CDATA format: <tag><![CDATA[text]]></tag>
        if not title_match:
            title_match = re.search(r'<dc:title><!\[CDATA\[([^\]]+)\]\]></dc:title>', metadata)
        if not artist_match:
            artist_match = re.search(r'<upnp:artist[^>]*><!\[CDATA\[([^\]]+)\]\]></upnp:artist>', metadata)
        if not album_match:
            album_match = re.search(r'<upnp:album><!\[CDATA\[([^\]]+)\]\]></upnp:album>', metadata)

        # Kuwo format: uses <dc:creator> instead of <upnp:artist>
        if not artist_match:
            artist_match = re.search(r'<dc:creator>([^<]+)</dc:creator>', metadata)

        title = self._decode_xml_entities(title_match.group(1)) if title_match else "None"
        artist = self._decode_xml_entities(artist_match.group(1)) if artist_match else "None"
        album = self._decode_xml_entities(album_match.group(1)) if album_match else "None"
        cover_url = self._decode_xml_entities(album_art_match.group(1)) if album_art_match else "None"
        duration_str = duration_match.group(1) if duration_match else "None"

        device.play_title = title
        device.play_artist = artist
        device.play_album = album
        device.play_cover_url = cover_url
        device.play_duration = device.parse_time(duration_str)

        log_info("Metadata", f"\n\ttitle:  {title}\n\tartist: {artist}\n\talbum:  {album}\n\tduration: {duration_str}")

    async def _probe_and_update_media_info(self, device: "VirtualDevice", url: str):
        """
        Probe media info using FFprobe and update device audio info.
        This runs asynchronously to avoid blocking the DLNA response.
        """
        try:
            media_info = await probe_media(url, timeout=10.0)
            if media_info:
                device.audio_format = media_info.get("codec", "")
                device.audio_sample_rate = media_info.get("sample_rate", 0)
                device.audio_channels = media_info.get("channels", 0)
                device.audio_bitrate = format_bitrate(media_info.get("bitrate", 0))

                log_info("MediaInfo", f"codec={device.audio_format}, "
                         f"sample_rate={device.audio_sample_rate}Hz, "
                         f"bitrate={device.audio_bitrate}, "
                         f"channels={device.audio_channels}")
        except Exception as e:
            log_warning("MediaInfo", f"Failed to probe media: {e}")

    # ================= UPnP GENA Event Notifications =================

    def _build_last_change(self, device: "VirtualDevice") -> str:
        """Build LastChange XML for event notification"""
        if device.play_state == "PLAYING":
            actions = "Pause,Stop,Seek"
        elif device.play_state == "PAUSED_PLAYBACK":
            actions = "Play,Stop"
        elif device.play_state == "TRANSITIONING":
            actions = "Stop"
        else:  # STOPPED
            actions = "Play"

        uri_escaped = xml_escape(device.play_url) if device.play_url else ""

        inner_xml = f'''<Event xmlns="urn:schemas-upnp-org:metadata-1-0/AVT/">
  <InstanceID val="0">
    <TransportState val="{device.play_state}"/>
    <TransportStatus val="OK"/>
    <CurrentTransportActions val="{actions}"/>
    <AVTransportURI val="{uri_escaped}"/>
    <CurrentTrackURI val="{uri_escaped}"/>
  </InstanceID>
</Event>'''
        return xml_escape(inner_xml)

    def _build_event_xml(self, device: "VirtualDevice") -> str:
        """Build full event notification XML"""
        last_change = self._build_last_change(device)
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">
  <e:property>
    <LastChange>{last_change}</LastChange>
  </e:property>
</e:propertyset>'''

    async def _notify_subscribers(self, device: "VirtualDevice"):
        """Send event notifications to all subscribers for a device"""
        subscribers = self._get_device_subscribers(device.device_id)
        if not subscribers:
            return

        event_xml = self._build_event_xml(device)
        now = time.time()
        expired_sids = []

        for sid, sub_info in subscribers.items():
            #TODO  订阅设备过期问题待修复
            if sub_info["expires"] < now:
                expired_sids.append(sid)
                continue

            if sub_info.get("service") != "AVTransport":
                continue

            callback_url = sub_info["callback"]
            seq = sub_info["seq"]
            sub_info["seq"] += 1

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
                        if resp.status < 300:
                            log_debug("Event", f"Notification sent: {device.play_state} -> {device.device_name}")
                        else:
                            log_debug("Event", f"Notification failed ({resp.status})")
            except Exception as e:
                log_debug("Event", f"Notification exception: {e}")

        # Clean up expired subscriptions
        for sid in expired_sids:
            del subscribers[sid]
            log_debug("Subscribe", f"Subscription expired: {sid[:20]}...")

    async def _handle_event_sub(self, request: web.Request):
        """Handle event subscription/unsubscription requests"""
        device = self._get_device_from_request(request)
        if not device:
            return web.Response(status=404, text="Device not found")

        method = request.method
        service = request.match_info.get("service", "unknown")
        subscribers = self._get_device_subscribers(device.device_id)

        if method == "SUBSCRIBE":
            sid_header = request.headers.get("SID")

            if sid_header:
                # Renewal
                if sid_header in subscribers:
                    timeout_header = request.headers.get("TIMEOUT", "Second-1800")
                    timeout_match = re.search(r"Second-(\d+)", timeout_header)
                    timeout = int(timeout_match.group(1)) if timeout_match else 1800
                    subscribers[sid_header]["expires"] = time.time() + timeout
                    subscribers[sid_header]["timeout"] = timeout
                    log_debug("Subscribe", f"Renewal: {sid_header[:20]}... ({service})")
                    return web.Response(
                        status=200,
                        headers={"SID": sid_header, "TIMEOUT": f"Second-{timeout}"}
                    )
                else:
                    return web.Response(status=412)
            else:
                # New subscription
                callback_header = request.headers.get("CALLBACK", "")
                callback_match = re.search(r"<([^>]+)>", callback_header)
                if not callback_match:
                    return web.Response(status=400)

                callback_url = callback_match.group(1)
                timeout_header = request.headers.get("TIMEOUT", "Second-1800")
                timeout_match = re.search(r"Second-(\d+)", timeout_header)
                timeout = int(timeout_match.group(1)) if timeout_match else 1800

                sid = f"uuid:{uuid.uuid4()}"
                subscribers[sid] = {
                    "callback": callback_url,
                    "timeout": timeout,
                    "expires": time.time() + timeout,
                    "seq": 0,
                    "service": service
                }
                log_info("Subscribe", f"New subscription: {device.device_name} ({service})")

                if service == "AVTransport":
                    asyncio.create_task(self._send_initial_event(device, sid, callback_url))

                return web.Response(
                    status=200,
                    headers={"SID": sid, "TIMEOUT": f"Second-{timeout}"}
                )

        elif method == "UNSUBSCRIBE":
            sid_header = request.headers.get("SID")
            if sid_header and sid_header in subscribers:
                del subscribers[sid_header]
                log_debug("Subscribe", f"Unsubscribe: {sid_header[:20]}...")
                return web.Response(status=200)
            else:
                return web.Response(status=412)

        return web.Response(status=405)

    async def _send_initial_event(self, device: "VirtualDevice", sid: str, callback_url: str):
        """Send initial event on subscription"""
        event_xml = self._build_event_xml(device)
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "NT": "upnp:event",
                    "NTS": "upnp:propchange",
                    "SID": sid,
                    "SEQ": "0",
                    "Content-Type": "text/xml; charset=utf-8",
                }
                async with session.request(
                    "NOTIFY",
                    callback_url,
                    headers=headers,
                    data=event_xml,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    log_debug("Subscribe", f"Initial event sent: {resp.status}")
        except Exception as e:
            log_debug("Subscribe", f"Initial event failed: {e}")

    # ================= Service Lifecycle =================

    def _create_app(self) -> web.Application:
        """Create aiohttp application with routes"""
        app = web.Application()

        # Device-specific routes (with device_id)
        app.router.add_get("/device/{device_id}/device.xml", self._handle_device_xml)
        app.router.add_get("/device/{device_id}/AVTransport.xml", self._handle_av_transport_xml)
        app.router.add_get("/device/{device_id}/RenderingControl.xml", self._handle_rendering_control_xml)
        app.router.add_get("/device/{device_id}/ConnectionManager.xml", self._handle_connection_manager_xml)
        app.router.add_post("/device/{device_id}/ctl/AVTransport", self._handle_av_transport_ctl)
        app.router.add_post("/device/{device_id}/ctl/RenderingControl", self._handle_rendering_control_ctl)
        app.router.add_post("/device/{device_id}/ctl/ConnectionManager", self._handle_connection_manager_ctl)
        app.router.add_route("SUBSCRIBE", "/device/{device_id}/evt/{service}", self._handle_event_sub)
        app.router.add_route("UNSUBSCRIBE", "/device/{device_id}/evt/{service}", self._handle_event_sub)

        return app

    async def start(self):
        """Start DLNA service"""
        if self._running:
            return

        self._running = True

        # Start SSDP
        self._ssdp_task = asyncio.create_task(self._start_ssdp())
        self._notify_task = asyncio.create_task(self._send_notify_periodically())

        # Start HTTP server
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", HTTP_PORT)
        await site.start()

        log_info("DLNAService", f"DLNA service started on http://{LOCAL_IP}:{HTTP_PORT}")

    async def stop(self):
        """Stop DLNA service"""
        if not self._running:
            return

        self._running = False
        log_info("DLNAService", "Stopping DLNA service...")

        if self._ssdp_task:
            self._ssdp_task.cancel()
            try:
                await self._ssdp_task
            except asyncio.CancelledError:
                pass

        if self._notify_task:
            self._notify_task.cancel()
            try:
                await self._notify_task
            except asyncio.CancelledError:
                pass

        if self._ssdp_socket:
            self._ssdp_socket.close()

        if self._runner:
            await self._runner.cleanup()

        log_info("DLNAService", "DLNA service stopped")

    def is_running(self) -> bool:
        """Check if service is running"""
        return self._running
