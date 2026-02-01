"""
Audio Device Detector - Detect available audio output devices

Uses sounddevice (PortAudio) to detect if the system has audio output devices.
This helps determine whether Server Speaker should be created.
"""
from typing import Any

import sounddevice as sd

from core.utils import log_info, log_debug


def has_audio_output_device() -> bool:
    """
    Check if system has at least one audio output device.

    Returns:
        True if at least one output device is available, False otherwise
    """
    try:
        devices = sd.query_devices()
        for dev in devices:
            if dev['max_output_channels'] > 0:
                return True
        return False
    except Exception as e:
        log_debug("AudioDetector", f"Failed to query audio devices: {e}")
        return False


def log_audio_devices():
    """
    Log available audio devices to console.

    This helps with debugging audio device detection issues.
    """
    try:
        devices = sd.query_devices()
        default_output = sd.default.device[1] if isinstance(sd.default.device, tuple) else sd.default.device

        log_info("AudioDetector", "=== Available Audio Devices ===")

        output_count = 0
        for i, dev in enumerate(devices):
            if dev['max_output_channels'] > 0:
                default_marker = " (default)" if i == default_output else ""
                log_info("AudioDetector",
                        f"  [{i}] {dev['name']} - "
                        f"{dev['max_output_channels']} channels @ {int(dev['default_samplerate'])}Hz"
                        f"{default_marker}")
                output_count += 1

        if output_count == 0:
            log_info("AudioDetector", "  No audio output devices found")
        else:
            log_info("AudioDetector", f"  Total: {output_count} output device(s)")

        log_info("AudioDetector", "=" * 40)

    except Exception as e:
        log_debug("AudioDetector", f"Failed to list audio devices: {e}")


def get_default_output_device() -> Any | None:
    """
    Get default audio output device information.

    Returns:
        Dictionary with device info, or None if no default device
    """
    try:
        default_idx = sd.default.device[1] if isinstance(sd.default.device, tuple) else sd.default.device
        devices = sd.query_devices()
        if 0 <= default_idx < len(devices):
            return devices[default_idx]
    except Exception as e:
        log_debug("AudioDetector", f"Failed to get default device: {e}")
    return None
