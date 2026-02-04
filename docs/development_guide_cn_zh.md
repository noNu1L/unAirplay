# unAirplay - 开发规范文档

## 一、项目架构概述

### 1.1 核心流程

```
输入源 [DLNA] → FFmpeg → DSP [可选] → 输出 [AirPlay / Server Speaker]
```

### 1.2 事件驱动架构

本项目采用**事件驱动模型**，所有组件间通信必须通过事件总线（EventBus）进行，严禁直接调用。

**核心原则：**
- ✅ 所有状态变更通过事件通知
- ✅ 组件间解耦，通过事件通信
- ❌ 禁止组件间直接调用方法

---

## 二、核心组件定义

### 2.1 虚拟设备（VirtualDevice）- **容器/执行人**

**文件**: `device/virtual_device.py`

**职责：**
- 项目的**最核心组件**，所有服务围绕它运行
- 作为容器，持有设备状态（播放状态、音量、DSP配置等）
- 作为执行人，订阅命令事件并执行
- 拥有并管理自己的 Output 实例（AirPlay 或 Server Speaker）
- 拥有并管理自己的 DSP Enhancer

**状态包含：**
- 播放控制：播放/暂停/停止/Seek
- 音量控制：音量值、静音状态
- DSP 配置：是否启用、DSP 参数
- 音频信息：格式、码率、采样率
- 元数据：标题、艺术家、专辑、封面

**交互模式：**
- 订阅命令事件（CMD_PLAY, CMD_STOP, CMD_PAUSE, CMD_SEEK, CMD_SET_VOLUME, CMD_SET_DSP 等）
- 发布状态事件（STATE_CHANGED, VOLUME_CHANGED, DSP_CHANGED 等）

**严格规则：**
- ❌ 任何外部组件不得直接调用 VirtualDevice 的方法
- ✅ 必须通过 EventBus 发布命令事件来操作
- ✅ VirtualDevice 执行完命令后发布状态事件

---

### 2.2 设备管理器（DeviceManager）- **管理员**

**文件**: `device/device_manager.py`

**职责：**
- 管理 VirtualDevice 的生命周期（创建、销毁）
- 扫描 AirPlay 设备并创建对应的虚拟设备
- 创建 Server Speaker 虚拟设备
- 发布设备事件（DEVICE_ADDED, DEVICE_REMOVED, DEVICE_CONNECTED, DEVICE_DISCONNECTED）
- 加载/保存设备配置（通过 ConfigStore）

**严格规则：**
- ✅ DeviceManager **仅负责生命周期管理**
- ❌ **不参与** VirtualDevice 的内部实现细节
- ❌ **不直接操作** VirtualDevice 的状态
- ✅ 通过 EventBus 发布命令事件来通知 VirtualDevice
- ✅ 所有外部组件想操作设备，必须通过 DeviceManager 获取设备引用，然后通过事件通知

---

### 2.3 配置存储（ConfigStore）- **外围组件**

**文件**: `core/config_store.py`

**职责：**
- 持久化保存设备配置（DSP 配置等）
- 订阅 DSP_CHANGED 事件并自动保存

**严格规则：**
- ❌ 外部组件**禁止直接调用** ConfigStore 的保存方法
- ✅ 配置更新必须通过事件流：
  1. 外部组件发布命令事件（如 CMD_SET_DSP）
  2. VirtualDevice 执行并发布状态事件（DSP_CHANGED）
  3. ConfigStore 订阅状态事件并自动保存
- ✅ 读取配置可以直接通过 DeviceManager.get_device() 获取设备状态

---

### 2.4 Web 服务器（WebServer）- **外围组件**

**文件**: `web/server.py`

**职责：**
- 提供 Web 控制面板
- 发布 DSP 配置命令事件

**严格规则：**
- ❌ 禁止直接读写 ConfigStore
- ❌ 禁止直接操作 VirtualDevice
- ✅ 读取状态：通过 DeviceManager.get_device() 获取设备
- ✅ 修改配置：发布命令事件（CMD_SET_DSP, CMD_RESET_DSP 等）

---

### 2.5 DLNA 服务（DLNAService）- **外围组件**

**文件**: `source/dlna_service.py`

**职责：**
- 处理 DLNA/UPnP 协议请求
- 发布播放控制命令事件
- 订阅状态事件用于 UPnP GENA 通知

**严格规则：**
- ❌ 禁止直接操作 VirtualDevice
- ✅ 接收 DLNA 请求后发布命令事件（CMD_PLAY, CMD_STOP, CMD_SEEK, CMD_SET_VOLUME 等）
- ✅ 订阅 STATE_CHANGED 事件发送 UPnP 通知给客户端

---

## 三、事件驱动模型

### 3.1 事件总线（EventBus）

**文件**: `core/event_bus.py`

**核心机制：**
- 发布-订阅模式
- 支持设备ID过滤（事件只发送给特定设备）
- 异步事件处理

### 3.2 事件类型

**文件**: `core/events.py`

#### 命令事件（Command Events）
由外部组件发布，VirtualDevice 订阅并执行：

| 事件类型 | 发布者 | 订阅者 | 说明 |
|---------|--------|--------|------|
| CMD_PLAY | DLNA/WebServer | VirtualDevice | 播放命令 |
| CMD_STOP | DLNA/WebServer | VirtualDevice | 停止命令 |
| CMD_PAUSE | DLNA/WebServer | VirtualDevice | 暂停命令 |
| CMD_SEEK | DLNA/WebServer | VirtualDevice | 调整进度 |
| CMD_SET_VOLUME | DLNA/WebServer | VirtualDevice | 设置音量 |
| CMD_SET_MUTE | DLNA/WebServer | VirtualDevice | 设置静音 |
| CMD_SET_DSP | WebServer | VirtualDevice | 设置 DSP |
| CMD_RESET_DSP | WebServer | VirtualDevice | 重置 DSP |

#### 状态事件（State Events）
由 VirtualDevice 发布，外部组件订阅：

| 事件类型 | 发布者 | 订阅者 | 说明 |
|---------|--------|--------|------|
| STATE_CHANGED | VirtualDevice | DLNA/WebServer | 播放状态变更 |
| VOLUME_CHANGED | VirtualDevice | WebServer | 音量变更 |
| DSP_CHANGED | VirtualDevice | ConfigStore | DSP 配置变更 |
| METADATA_UPDATED | VirtualDevice | WebServer | 元数据更新 |

#### 设备事件（Device Events）
由 DeviceManager 发布：

| 事件类型 | 发布者 | 说明 |
|---------|--------|------|
| DEVICE_ADDED | DeviceManager | 设备添加 |
| DEVICE_REMOVED | DeviceManager | 设备移除 |
| DEVICE_CONNECTED | DeviceManager | 设备连接 |
| DEVICE_DISCONNECTED | DeviceManager | 设备断开 |

### 3.3 事件流示例

#### 示例 1：DLNA 客户端播放音乐

```
1. DLNA 客户端发送 SetAVTransportURI + Play
2. DLNAService 解析请求
3. DLNAService 发布 cmd_play(device_id, url, position) 事件
4. VirtualDevice 订阅到 CMD_PLAY 事件
5. VirtualDevice 执行播放：
   - 更新内部状态（play_state = "PLAYING"）
   - 调用 Output.handle_action("play", uri, position)
6. VirtualDevice 发布 state_changed(device_id, state="PLAYING") 事件
7. DLNAService 订阅到 STATE_CHANGED 事件
8. DLNAService 发送 UPnP GENA 通知给 DLNA 客户端
```

#### 示例 2：Web 面板修改 DSP 配置

```
1. 用户在 Web 面板修改 DSP 配置
2. WebServer 发布 cmd_set_dsp(device_id, enabled, config) 事件
3. VirtualDevice 订阅到 CMD_SET_DSP 事件
4. VirtualDevice 执行：
   - 更新 dsp_enabled 和 dsp_config
5. VirtualDevice 发布 dsp_changed(device_id, enabled, config) 事件
6. ConfigStore 订阅到 DSP_CHANGED 事件
7. ConfigStore 自动保存配置到文件
8. WebServer 订阅到 DSP_CHANGED 事件（可选）
9. WebServer 更新前端显示
```

---

## 四、输出层（Output）

### 4.1 输出抽象

**基类**: `output/base.py` - `BaseOutput`

**实现类：**
- `output/airplay_output.py` - `AirPlayOutput`
- `output/server_speaker.py` - `ServerSpeakerOutput`

### 4.2 输出职责

**由 VirtualDevice 调配：**
- 接收播放命令（play, stop, pause, seek）
- 管理 FFmpeg 解码进程
- 应用 DSP 处理（可选）
- 输出音频流

**音频链路：**

#### AirPlay 输出
```
URL → FFmpegDownloader → cache file → FFmpegDecoder → [Optional DSP] → pyatv (ALAC) → AirPlay Device
```

#### Server Speaker 输出
```
URL → FFmpegDownloader → cache file → FFmpegDecoder → [Optional DSP] → sounddevice → System Speaker
```

### 4.3 FFmpeg 公共模块

FFmpeg 功能已抽取为公共模块，位于 `core/` 目录：

| 模块 | 职责 |
|------|------|
| `ffmpeg_utils.py` | PCMFormat 枚举、进程工具函数 |
| `ffmpeg_downloader.py` | 下载音频到缓存文件（-c:a copy，无重编码） |
| `ffmpeg_decoder.py` | 解码缓存文件为 PCM 流 |

**解耦架构（边下载边播放）：**
```
URL → FFmpegDownloader → cache/{device_id}_xxx.mkv → FFmpegDecoder → PCM
         (下载线程)              (等待100KB缓冲)         (播放线程)
```

**Seek 支持：** 下载器支持从指定位置开始下载（`-ss` 参数），解码器从缓存文件头开始。

**使用示例：**
```python
from core.ffmpeg_downloader import FFmpegDownloader, DownloaderConfig
from core.ffmpeg_decoder import FFmpegDecoder, DecoderConfig
from core.ffmpeg_utils import PCMFormat

# 下载器
downloader = FFmpegDownloader(DownloaderConfig(
    cache_dir="cache",
    cache_filename=f"{device_id}_play_cache"
))
downloader.start(url, seek_position=60.0)  # 从 60 秒开始下载

# 解码器
decoder = FFmpegDecoder(DecoderConfig(
    pcm_format=PCMFormat.F32LE,  # 或 PCMFormat.S16LE
    realtime=True
))
decoder.start(downloader.file_path)
```

### 4.4 音频设备检测

**文件**: `output/audio_device_detector.py`

**职责：**
- 检测系统可用的音频输出设备
- 获取默认音频输出设备
- 列出所有音频输出设备信息

**使用场景：**
- Server Speaker 输出初始化时检测可用设备
- Web 面板显示可用音频设备列表

---

## 五、DSP 增强器（Enhancer）

### 5.1 DSP 抽象

**基类**: `enhancer/base.py` - `BaseEnhancer`

**主实现类**: `enhancer/dsp_numpy2.py` - `NumpyEnhancer`

### 5.2 DSP 模块化架构

`NumpyEnhancer` 采用模块化设计，组合以下子模块：

| 模块 | 文件 | 职责 |
|------|------|------|
| 均衡器 & 音调增强 | `dsp_equalizer_tone_iir.py` | IIR 滤波器实现（低延迟） |
| 均衡器 & 音调增强 | `dsp_equalizer_tone_fft.py` | FFT 频域实现（高精度） |
| 均衡器 & 音调增强 | `dsp_equalizer_tone_fir.py` | FIR 滤波器实现（线性相位） |
| 动态压缩器 | `dsp_compression.py` | 动态范围压缩 |
| 立体声增强 | `dsp_stereo.py` | Mid-Side 立体声处理 |

**处理流程：**
```
音频输入 → 均衡器&音调 (IIR/FFT/FIR 三选一) → 动态压缩 → 立体声增强 → 音频输出
```

### 5.3 DSP 职责

- 接收 PCM 音频数据（numpy 数组，float32，范围 [-1, 1]）
- 应用音频增强（均衡器、音调、压缩器、立体声增强）
- 返回处理后的 PCM 数据

---

## 六、开发规范

### 6.1 必须遵守的原则

#### ✅ 事件驱动通信
- 所有组件间通信必须通过 EventBus
- 发布命令事件让目标组件执行
- 订阅状态事件获取更新

#### ✅ 职责分离
- DeviceManager 只管理生命周期
- VirtualDevice 是唯一的执行人
- 外部组件通过事件通知，不直接操作

#### ✅ 配置流程
```
外部组件 → 发布命令事件 → VirtualDevice 执行 → 发布状态事件 → ConfigStore 保存
```

### 6.2 禁止的操作

#### ❌ 直接调用
```python
# 错误示例
device.play_state = "PLAYING"  # 禁止直接修改
device.set_volume(50)          # 禁止直接调用

# 正确示例
event_bus.publish(cmd_play(device_id, url))
event_bus.publish(cmd_set_volume(device_id, 50))
```

#### ❌ 跨层访问
```python
# 错误示例
config_store.save_device_config(device_id, config)  # 外部组件禁止直接保存

# 正确示例
event_bus.publish(cmd_set_dsp(device_id, enabled, config))
# ConfigStore 自动订阅 DSP_CHANGED 事件并保存
```

#### ❌ 绕过管理器
```python
# 错误示例
device = VirtualDevice.create_airplay_device(info)  # 禁止外部创建

# 正确示例
# DeviceManager 自动扫描并创建设备
```

---

## 七、新功能开发流程

### 7.1 添加新的命令

**步骤：**

1. **定义事件类型**（`core/events.py`）
```python
class EventType(Enum):
    CMD_NEW_FEATURE = auto()
```

2. **创建事件工厂**（`core/events.py`）
```python
def cmd_new_feature(device_id: str, param: Any) -> Event:
    return Event(
        type=EventType.CMD_NEW_FEATURE,
        device_id=device_id,
        data={"param": param}
    )
```

3. **VirtualDevice 订阅事件**（`device/virtual_device.py`）
```python
def subscribe_events(self):
    # ...
    event_bus.subscribe(EventType.CMD_NEW_FEATURE, self._on_cmd_new_feature, device_id=self.device_id)

def _on_cmd_new_feature(self, event: Event):
    param = event.data.get("param")
    self._execute_new_feature(param)

def _execute_new_feature(self, param: Any):
    # 执行逻辑
    # ...
    # 发布状态事件（如需要）
    event_bus.publish(state_changed(self.device_id, state="..."))
```

4. **外部组件发布事件**（如 `source/dlna_service.py` 或 `web/server.py`）
```python
event_bus.publish(cmd_new_feature(device_id, param))
```

### 7.2 添加新的输出类型

**步骤：**

1. **继承 BaseOutput**（`output/new_output.py`）
```python
from output.base import BaseOutput

class NewOutput(BaseOutput):
    def handle_action(self, action: str, **kwargs):
        # 实现播放控制
        pass
```

2. **在 DeviceManager 的 output factory 中添加**（`run.py`）
```python
def _create_output_for_device(self, device: VirtualDevice):
    if device.device_type == "new_type":
        output = NewOutput(device, enhancer)
        device.set_output(output)
```

---

## 八、总结

### 核心原则

1. **VirtualDevice 是中心** - 所有操作围绕它执行
2. **事件驱动通信** - 禁止直接调用，必须通过事件
3. **DeviceManager 是管理员** - 只管生命周期，不管内部实现
4. **外部组件解耦** - ConfigStore、WebServer、DLNAService 通过事件交互
5. **Output 是工具** - 由 VirtualDevice 调配 FFmpeg 和音频输出

### 开发检查清单

开发新功能时，必须检查：

- [ ] 是否通过 EventBus 发布命令事件？
- [ ] VirtualDevice 是否订阅了该事件？
- [ ] 执行完成后是否发布状态事件？
- [ ] 是否有直接调用 VirtualDevice 的方法？（禁止）
- [ ] 是否有直接调用 ConfigStore 保存？（禁止）
- [ ] 是否绕过 DeviceManager 创建设备？（禁止）

---

**版本**: v1.1.0
**日期**: 2026-02-04
