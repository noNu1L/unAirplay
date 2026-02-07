# unAirplay

[English](README.md) | [中文](README_CN.md)

---

unAirplay 是一个音频桥接工具。它能将 DLNA/UPnP 协议的音频流转发到 AirPlay 设备或服务器本地扬声器，让不支持 AirPlay 的安卓设备或音乐 App 也能向 AirPlay 设备推送音频。

本项目集成了 DSP（数字信号处理）功能，可用于调整输出音频的听感。

**注意：** 目前该项目仅在 HomePod (第一代) 设备上测试通过，尚未在 Sonos 或其他 AirPlay 品牌设备上进行充分测试。

## 功能特性

- **协议桥接**：将 DLNA 客户端的音频推送到 AirPlay 设备。
- **本地输出**：支持将音频直接通过服务器的本地声卡/扬声器播放。
- **Web 控制面板**：访问 `http://<服务器IP>:6089`，支持播放状态监控和 DSP 音效调整（EQ、频谱增强、立体声拓宽等）。

## 如何使用

### 1. 使用 Docker 部署（推荐）

克隆源码：

```bash
git clone https://github.com/noNu1L/unAirplay
cd unAirplay/docker
```

启动服务：

```bash
docker compose up -d
```

### 2. 本地运行

安装依赖：

```bash
pip install -r requirements.txt
```

运行项目：

```bash
python run.py
```

## 配置说明

项目支持自动发现和配置，通常启动即可使用。

- **自动发现**：启动后，程序会自动扫描局域网内的 AirPlay 设备，并生成后缀为 `[D]` 的虚拟 DLNA 设备。
- **Server Speaker**：如果运行环境具备音频输出能力，程序会默认生成一个 Server Speaker 虚拟桥接设备。
- **修改设置**：编辑 `config.py` 文件可以进行自定义调整：
  - **禁用本地播放**：设置 `ENABLE_SERVER_SPEAKER = False` 即可关闭 Server Speaker 虚拟设备。
  - **端口设置**：可以在配置文件中修改 Web 页面和服务的运行端口。

## 常见问题

- **关于音质**：部分安卓音乐 App 在非播放界面推送时（即非 URL 直接推送模式），原始流音质可能较低。此时开启 DSP 中的频谱增强可以在一定程度上改善听感。
- **播放完当前歌曲却没有继续播放下一首**：如果出现此问题（安卓手机 APP 内部 DLNA 推送），请尝试关闭该软件的"忽略电池优化"、"后台高耗电白名单"等相关设置。
- **关于 DSP 模式**：CPU 占用：FIR > IIR >= FFT。音质效果：FIR >= FFT > IIR。IIR 模式延迟最低（零延迟），FFT 模式 CPU 效率更高。根据您的优先级选择：延迟优先或资源消耗优先。
