"""
ConfigStore - Persistent configuration storage

This module subscribes to DSP_CHANGED events and automatically saves configuration.
ConfigStore - 持久化配置存储

此模块订阅 DSP_CHANGED 事件并自动保存配置。
"""
import json
import os
import copy
from typing import Dict, Any, Optional

from .utils import log_info, log_warning, log_debug
from .event_bus import event_bus
from .events import EventType, Event
from config import DEFAULT_DSP_CONFIG

# Default config file path
# 默认配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


class ConfigStore:
    """
    Persistent configuration storage using JSON file.

    Subscribes to DSP_CHANGED events and automatically saves configuration.

    Structure:
    {
        "devices": {
            "server_speaker": {
                "dsp_enabled": false,
                "dsp_config": { ... }
            },
            "a1b2c3d4e5f6": {
                "dsp_enabled": true,
                "dsp_config": { ... }
            }
        }
    }
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._config_file = CONFIG_FILE
        self._config: Dict[str, Any] = {"devices": {}}
        self._load()

        # Subscribe to DSP changed events for automatic saving
        # 订阅 DSP 更改事件以自动保存
        event_bus.subscribe(EventType.DSP_CHANGED, self._on_dsp_changed)
        log_debug("ConfigStore", "Subscribed to DSP_CHANGED events")

    def _on_dsp_changed(self, event: Event):
        """
        Handle DSP configuration change event.

        Automatically saves the new configuration to disk.
        """
        device_id = event.device_id
        enabled = event.data.get("enabled", False)
        config = event.data.get("config", {})

        self.set_device_config(device_id, enabled, config)
        log_debug("ConfigStore", f"Auto-saved DSP config for device: {device_id}...")

    def _load(self):
        """Load configuration from file"""
        if not os.path.exists(self._config_file):
            log_debug("ConfigStore", f"Config file not found, using defaults")
            self._config = {"devices": {}}
            return

        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._config = data

            log_info("ConfigStore", f"Loaded config with {len(self._config.get('devices', {}))} device(s)")

        except Exception as e:
            log_warning("ConfigStore", f"Failed to load config: {e}")
            self._config = {"devices": {}}

    def _save(self):
        """Save configuration to file
        保存配置到文件
        """
        try:
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=4, ensure_ascii=False)
            log_debug("ConfigStore", "Config saved")
        except Exception as e:
            log_warning("ConfigStore", f"Failed to save config: {e}")

    def get_device_config(self, device_id: str) -> Any | None:
        """
        Get device configuration.

        Args:
            device_id: Device ID / 设备 ID

        Returns:
            Device config dict with dsp_enabled and dsp_config / 包含 dsp_enabled 和 dsp_config 的设备配置字典
        """
        devices = self._config.get("devices", {})
        if device_id in devices:
            return devices[device_id]
        return None

    def set_device_config(self, device_id: str, dsp_enabled: bool, dsp_config: Dict[str, Any]):
        """
        Set device configuration.
        设置设备配置。

        Args:
            device_id: Device ID / 设备 ID
            dsp_enabled: Whether DSP is enabled / 是否启用 DSP
            dsp_config: DSP configuration dictionary / DSP 配置字典
        """
        if "devices" not in self._config:
            self._config["devices"] = {}

        self._config["devices"][device_id] = {
            "dsp_enabled": dsp_enabled,
            "dsp_config": dsp_config
        }
        self._save()
        log_info("ConfigStore", f"Saved config for device: {device_id}")

    def get_dsp_enabled(self, device_id: str) -> bool:
        """Get DSP enabled state for device
        获取设备的 DSP 启用状态
        """
        config = self.get_device_config(device_id)
        if config:
            return config.get("dsp_enabled", False)
        return False

    def get_dsp_config(self, device_id: str) -> Dict[str, Any]:
        """Get DSP config for device
        获取设备的 DSP 配置
        """
        config = self.get_device_config(device_id)
        if config:
            return config.get("dsp_config", copy.deepcopy(DEFAULT_DSP_CONFIG))
        return copy.deepcopy(DEFAULT_DSP_CONFIG)


# Global instance
config_store = ConfigStore()
