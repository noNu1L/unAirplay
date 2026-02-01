# DLNA to AirPlay Bridge

一个轻量级的 DLNA/UPnP 到 AirPlay 桥接服务，让任何 DLNA 客户端都能推送音频到 AirPlay 设备或本地扬声器。

## 特性

- 🎵 **DLNA 到 AirPlay 桥接** - 将 DLNA/UPnP 音频流转发到 AirPlay 设备（如 HomePod、Apple TV）
- 🔊 **Server Speaker 支持** - 支持输出到服务器本地扬声器
- 🎚️ **系统级音量控制** - 跨平台控制系统音量（Windows/Linux/macOS）
- 🎛️ **DSP 音频增强** - 内置均衡器、压缩器、立体声增强等音频处理
- 🌐 **Web 控制面板** - 友好的 Web 界面管理设备和 DSP 配置
- 🔄 **自动设备发现** - 自动扫描并创建 AirPlay 虚拟设备
- 📱 **多设备支持** - 同时支持多个 AirPlay 设备

## 系统要求

- Python 3.10+
- Windows/Linux/macOS
- FFmpeg（用于音频解码）

### 音量控制依赖

- **Windows**: pycaw + comtypes
- **Linux**: amixer (alsa-utils)
- **macOS**: osascript (系统自带)

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config.py` 自定义配置：

```python
# 是否启用 Server Speaker（输出到本地扬声器）
ENABLE_SERVER_SPEAKER = True

# HTTP 服务端口
HTTP_PORT = 8088
WEB_PORT = 8089
```

### 3. 运行

```bash
python run.py
```

服务启动后：
- DLNA 服务：`http://<本机IP>:8088`
- Web 控制面板：`http://<本机IP>:8089`

## 使用方法

1. **启动服务** - 运行 `python run.py`
2. **连接 DLNA 客户端** - 在 DLNA 客户端（如网易云音乐、Spotify）中选择虚拟设备
3. **播放音乐** - 音频将自动转发到 AirPlay 设备或本地扬声器
4. **调整设置** - 通过 Web 面板调整音量和 DSP 配置

## 架构说明

本项目采用**事件驱动架构**：

```
DLNA 客户端 → DLNA Service → EventBus → VirtualDevice → Output (AirPlay/Speaker)
```

- **VirtualDevice** - 核心组件，管理设备状态和命令执行
- **EventBus** - 事件总线，解耦组件间通信
- **Output Layer** - 抽象输出层（AirPlay/ServerSpeaker）
- **DSP Enhancer** - 可选的音频增强处理

详细架构文档请参考 `docs/development_guide.md`

## 支持的客户端

- 网易云音乐（Android/iOS/Windows）
- BubbleUPnP
- Hi-Fi Cast
- VLC Media Player
- 其他支持 DLNA/UPnP 的播放器

## 许可证

MIT License

## 致谢

- [pyatv](https://github.com/postlund/pyatv) - AirPlay 协议实现
- [pycaw](https://github.com/AndreMiras/pycaw) - Windows 音量控制
- [sounddevice](https://python-sounddevice.readthedocs.io/) - 跨平台音频输出
