"""
System Volume Controller - Cross-platform system volume control abstraction

Provides unified interface for controlling system volume across different platforms:
- Windows: pycaw (Core Audio API)
- Linux: amixer (ALSA mixer)
- macOS: osascript (AppleScript)
"""
import sys
import subprocess
from abc import ABC, abstractmethod
from typing import Optional

from core.utils import log_info, log_debug, log_warning, log_error


class SystemVolumeController(ABC):
    """Abstract base class for system volume control"""

    @abstractmethod
    def get_volume(self) -> int:
        """
        Get current system volume.

        Returns:
            Volume level 0-100
        """
        pass

    @abstractmethod
    def set_volume(self, volume: int) -> bool:
        """
        Set system volume.

        Args:
            volume: Volume level 0-100

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def get_mute(self) -> bool:
        """
        Get current mute state.

        Returns:
            True if muted, False otherwise
        """
        pass

    @abstractmethod
    def set_mute(self, muted: bool) -> bool:
        """
        Set mute state.

        Args:
            muted: True to mute, False to unmute

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if volume controller is available on this system.

        Returns:
            True if available, False otherwise
        """
        pass


class WindowsVolumeController(SystemVolumeController):
    """Windows system volume controller using pycaw"""

    def __init__(self):
        self._available = False
        self._volume = None

        try:
            from pycaw.pycaw import AudioUtilities

            # Get default audio device
            devices = AudioUtilities.GetSpeakers()

            # New pycaw API: EndpointVolume is already available as a property
            self._volume = devices.EndpointVolume
            self._available = True

            log_info("VolumeControl", "Windows volume controller initialized (pycaw)")

        except ImportError:
            log_warning("VolumeControl", "pycaw not available - install with: pip install pycaw comtypes")
        except Exception as e:
            log_warning("VolumeControl", f"Failed to initialize Windows volume control: {e}")

    def is_available(self) -> bool:
        return self._available

    def get_volume(self) -> int:
        if not self._available or not self._volume:
            return 0
        try:
            # Get volume as scalar 0.0-1.0
            volume_scalar = self._volume.GetMasterVolumeLevelScalar()
            return int(volume_scalar * 100)
        except Exception as e:
            log_debug("VolumeControl", f"Failed to get volume: {e}")
            return 0

    def set_volume(self, volume: int) -> bool:
        if not self._available or not self._volume:
            return False
        try:
            # Convert 0-100 to 0.0-1.0
            volume_scalar = max(0.0, min(1.0, volume / 100.0))
            self._volume.SetMasterVolumeLevelScalar(volume_scalar, None)
            log_debug("VolumeControl", f"Windows volume set to {volume}%")
            return True
        except Exception as e:
            log_warning("VolumeControl", f"Failed to set volume: {e}")
            return False

    def get_mute(self) -> bool:
        if not self._available or not self._volume:
            return False
        try:
            return bool(self._volume.GetMute())
        except Exception as e:
            log_debug("VolumeControl", f"Failed to get mute state: {e}")
            return False

    def set_mute(self, muted: bool) -> bool:
        if not self._available or not self._volume:
            return False
        try:
            self._volume.SetMute(1 if muted else 0, None)
            log_debug("VolumeControl", f"Windows mute set to {muted}")
            return True
        except Exception as e:
            log_warning("VolumeControl", f"Failed to set mute: {e}")
            return False


class LinuxVolumeController(SystemVolumeController):
    """Linux system volume controller using amixer (ALSA)"""

    def __init__(self):
        self._available = self._check_amixer()
        if self._available:
            log_info("VolumeControl", "Linux volume controller initialized (amixer)")
        else:
            log_warning("VolumeControl", "amixer not available - install alsa-utils")

    def _check_amixer(self) -> bool:
        """Check if amixer command is available"""
        try:
            subprocess.run(
                ["amixer", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def is_available(self) -> bool:
        return self._available

    def get_volume(self) -> int:
        if not self._available:
            return 0
        try:
            result = subprocess.run(
                ["amixer", "sget", "Master"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                # Parse output like: "Front Left: Playback 65535 [100%] [0.00dB] [on]"
                import re
                match = re.search(r'\[(\d+)%\]', result.stdout)
                if match:
                    return int(match.group(1))
        except Exception as e:
            log_debug("VolumeControl", f"Failed to get volume: {e}")
        return 0

    def set_volume(self, volume: int) -> bool:
        if not self._available:
            return False
        try:
            volume_clamped = max(0, min(100, volume))
            result = subprocess.run(
                ["amixer", "sset", "Master", f"{volume_clamped}%"],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0:
                log_debug("VolumeControl", f"Linux volume set to {volume_clamped}%")
                return True
        except Exception as e:
            log_warning("VolumeControl", f"Failed to set volume: {e}")
        return False

    def get_mute(self) -> bool:
        if not self._available:
            return False
        try:
            result = subprocess.run(
                ["amixer", "sget", "Master"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                # Check for [off] in output
                return "[off]" in result.stdout
        except Exception as e:
            log_debug("VolumeControl", f"Failed to get mute state: {e}")
        return False

    def set_mute(self, muted: bool) -> bool:
        if not self._available:
            return False
        try:
            mute_arg = "mute" if muted else "unmute"
            result = subprocess.run(
                ["amixer", "sset", "Master", mute_arg],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0:
                log_debug("VolumeControl", f"Linux mute set to {muted}")
                return True
        except Exception as e:
            log_warning("VolumeControl", f"Failed to set mute: {e}")
        return False


class MacOSVolumeController(SystemVolumeController):
    """macOS system volume controller using osascript (AppleScript)"""

    def __init__(self):
        self._available = self._check_osascript()
        if self._available:
            log_info("VolumeControl", "macOS volume controller initialized (osascript)")
        else:
            log_warning("VolumeControl", "osascript not available")

    def _check_osascript(self) -> bool:
        """Check if osascript command is available"""
        try:
            subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def is_available(self) -> bool:
        return self._available

    def get_volume(self) -> int:
        if not self._available:
            return 0
        try:
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception as e:
            log_debug("VolumeControl", f"Failed to get volume: {e}")
        return 0

    def set_volume(self, volume: int) -> bool:
        if not self._available:
            return False
        try:
            volume_clamped = max(0, min(100, volume))
            result = subprocess.run(
                ["osascript", "-e", f"set volume output volume {volume_clamped}"],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0:
                log_debug("VolumeControl", f"macOS volume set to {volume_clamped}%")
                return True
        except Exception as e:
            log_warning("VolumeControl", f"Failed to set volume: {e}")
        return False

    def get_mute(self) -> bool:
        if not self._available:
            return False
        try:
            result = subprocess.run(
                ["osascript", "-e", "output muted of (get volume settings)"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip().lower() == "true"
        except Exception as e:
            log_debug("VolumeControl", f"Failed to get mute state: {e}")
        return False

    def set_mute(self, muted: bool) -> bool:
        if not self._available:
            return False
        try:
            mute_arg = "true" if muted else "false"
            result = subprocess.run(
                ["osascript", "-e", f"set volume output muted {mute_arg}"],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0:
                log_debug("VolumeControl", f"macOS mute set to {muted}")
                return True
        except Exception as e:
            log_warning("VolumeControl", f"Failed to set mute: {e}")
        return False


class DummyVolumeController(SystemVolumeController):
    """Dummy volume controller for unsupported platforms"""

    def __init__(self):
        log_warning("VolumeControl", f"No volume controller available for platform: {sys.platform}")

    def is_available(self) -> bool:
        return False

    def get_volume(self) -> int:
        return 0

    def set_volume(self, volume: int) -> bool:
        return False

    def get_mute(self) -> bool:
        return False

    def set_mute(self, muted: bool) -> bool:
        return False


def create_system_volume_controller() -> SystemVolumeController:
    """
    Factory function to create platform-specific volume controller.

    Auto-detects the platform and returns the appropriate controller.

    Returns:
        SystemVolumeController instance for the current platform
    """
    if sys.platform == "win32":
        return WindowsVolumeController()
    elif sys.platform.startswith("linux"):
        return LinuxVolumeController()
    elif sys.platform == "darwin":
        return MacOSVolumeController()
    else:
        return DummyVolumeController()
