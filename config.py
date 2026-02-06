"""
unAirplay - Global Configuration
"""
import socket

# ================= Application Info =================
APP_NAME = "unAirplay"
APP_VERSION = "1.1.2"

# ================= Network Configuration =================
HTTP_PORT = 6088
WEB_PORT = 6089

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
SAMPLE_RATE = 44100          # Output sample rate
CHANNELS = 2                 # Number of channels
CHUNK_DURATION_MS = 100      # Audio chunk duration in milliseconds
BUFFER_SIZE = 10             # Audio buffer queue size

# Minimum cache buffer size before starting playback (KB)
# Playback starts when downloaded cache file exceeds this size
MIN_CACHE_SIZE = 100  # KB

# Streaming audio playback behavior
# When playing streaming sources (duration=0 or very large):
# - True: Seek to latest position (for live streams)
# - False: Play from beginning (for on-demand streams)
# 流式音频播放行为：
# - True: 跳到最新位置播放（适用于直播流）
# - False: 从头播放（适用于点播流）
STREAMING_SEEK_TO_LATEST = True

# ================= Channel Separation (Reserved) =================
# Enable stereo channel separation for multiple speakers
# CHANNEL_SEPARATION_ENABLED = False

# Speaker group configuration
# 扬声器组 多个输出源组合 左右声道分离
# Format: [{"group_id": "living_room", "left": "device_id_1", "right": "device_id_2"}]
# SPEAKER_GROUPS = []

# ================= AirPlay Scanner Configuration =================
# Interval for scanning AirPlay devices (seconds)
AIRPLAY_SCAN_INTERVAL = 30

# Timeout for AirPlay device discovery (seconds)
AIRPLAY_SCAN_TIMEOUT = 5

# Exclude devices by IP address or name
# 按IP或名字地址排除设备，例如: ["192.168.1.100", "小喇叭"]
AIRPLAY_EXCLUDE = []

# Device offline detection configuration
# 设备离线检测配置
# Device will be removed after this many consecutive failed scans
# 设备连续多少次扫描未检测到后，删除虚拟设备
AIRPLAY_OFFLINE_THRESHOLD = 3

# ================= Server Speaker Configuration =================
# Whether to enable the Server Speaker virtual device (output to the local speaker of the server)
# After enabling, it will:
#   1. Detect if there is an audio output device in the system
#   2. If there is a device, create the Server Speaker virtual device
#   3. If there is no device, output a warning in the log
ENABLE_SERVER_SPEAKER = True

# ================= DSP Default Configuration =================
DEFAULT_DSP_CONFIG = {
    "eq_enabled": False,
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
    "spectral_enabled": True,
    "spectral_mode": "fft",  # "iir", "fft", or "fir"
    "highfreq_gain": 1.3,
    "lowfreq_gain": 1.0,
    "use_compression": False,
    "compression_threshold": 0.7,
    "compression_ratio": 3.0,
    "compression_makeup": 1.2,
    "use_stereo": False,
    "stereo_width": 1.2,
}
