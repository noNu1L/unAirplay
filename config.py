"""
DLNA to AirPlay Bridge - Global Configuration
"""
import socket
import uuid

# ================= Application Info =================
APP_NAME = "DLNA to AirPlay"
APP_VERSION = "1.0.0"

# ================= Network Configuration =================
HTTP_PORT = 8088
WEB_PORT = 8089

SSDP_MULTICAST_ADDR = "239.255.255.250"
SSDP_PORT = 1900


def get_local_ip():
    """Get local LAN IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


LOCAL_IP = get_local_ip()

# ================= Virtual Device Configuration =================
# Device name suffix for virtual DLNA devices
DEVICE_SUFFIX = "[D]"

# Server Speaker device name
SERVER_SPEAKER_NAME = "Server Speaker"

# ================= Audio Configuration =================
SAMPLE_RATE = 48000          # Output sample rate (48000 for AirPlay compatibility)
CHANNELS = 2                 # Number of channels
CHUNK_DURATION_MS = 100      # Audio chunk duration in milliseconds
BUFFER_SIZE = 10             # Audio buffer queue size

# Output bitrate for DSP mode (when re-encoding is needed)
OUTPUT_BITRATE = "320k"

# ================= Channel Separation (Reserved) =================
# Enable stereo channel separation for multiple speakers
CHANNEL_SEPARATION_ENABLED = False

# Speaker group configuration
# 扬声器组 多个输出源组合 左右声道分离
# Format: [{"group_id": "living_room", "left": "device_id_1", "right": "device_id_2"}]
SPEAKER_GROUPS = []

# ================= AirPlay Scanner Configuration =================
# Interval for scanning AirPlay devices (seconds)
AIRPLAY_SCAN_INTERVAL = 30

# Timeout for AirPlay device discovery (seconds)
AIRPLAY_SCAN_TIMEOUT = 5

# ================= Server Speaker Configuration =================
# Whether to enable the Server Speaker virtual device (output to the local speaker of the server)
# After enabling, it will:
#   1. Detect if there is an audio output device in the system
#   2. If there is a device, create the Server Speaker virtual device
#   3. If there is no device, output a warning in the log
ENABLE_SERVER_SPEAKER = True

# ================= DSP Default Configuration =================
DEFAULT_DSP_CONFIG = {
    "eq_enabled": True,
    "eq_31": 0.0,
    "eq_62": 0.0,
    "eq_125": 0.0,
    "eq_250": 0.0,
    "eq_500": 0.0,
    "eq_1000": 0.0,
    "eq_2000": 0.0,
    "eq_4000": 0.0,
    "eq_8000": 0.0,
    "eq_16000": 0.0,
    "highfreq_gain": 1.3,
    "lowfreq_gain": 1.0,
    "use_spectral": True,
    "use_compression": False,
    "compression_threshold": 0.7,
    "compression_ratio": 3.0,
    "compression_makeup": 1.2,
    "use_stereo": False,
    "stereo_width": 1.2,
}
