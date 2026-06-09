# AirPlay2 元数据显示方案

## 背景

当前 DLNA 侧已经能拿到歌曲信息，日志中可以看到 title、artist、album 已正确解析，包括日文歌曲信息。问题出在输出到 HomePod 后，苹果家庭 App 不显示歌曲信息。

本轮已经验证过的失败方向：

- RAOP metadata 强制发送：HomePod 的 RAOP TXT `md=-`，不声明 text metadata 支持；强发 `SET_PARAMETER` text/progress 后仍不显示。
- pyatv MRP Now Playing：MRP tunnel 可以连上，也能尝试发送 Now Playing protobuf，但 Home app 仍不显示。
- pyatv AirPlay `/play` direct URL：HomePod 返回 `SETUP 400 Bad Request` 或 legacy `/play 455`，不能作为稳定播放路线。

结论：继续在 pyatv RAOP 流上补 metadata 性价比不高，应该转向真正的 AirPlay2 audio sender 会话。

## 参考项目

### OwnTone

仓库：https://github.com/owntone/owntone-server

OwnTone 是目前最成熟的开源参考。它能向 AirPlay/HomePod 输出音频，并且 metadata 路线清晰：

- 在 AirPlay 会话建立后发送 `SET_PARAMETER (text)`。
- text 使用 `application/x-dmap-tagged`，也就是 DMAP/DAAP tagged metadata。
- 同时发送 `SET_PARAMETER (progress)`，body 为 `progress: display/pos/end\r\n`。
- 发送 artwork 时直接用 `image/jpeg` 或 `image/png`。
- text/progress/artwork 请求都会带 `RTP-Info: rtptime=<track_start_rtptime>`。
- 设备能力来自 AirPlay features，例如 `MetadataFeatures_0/1/2` 分别对应 artwork/progress/text。

可模仿的核心字段：

- `minm`: title
- `asar`: artist
- `asal`: album
- `asaa`: album artist
- `astm`: duration ms
- `asac`: artwork count

### airplay2-rs

仓库：https://github.com/lmcgartland/airplay2-rs

airplay2-rs 更适合参考 AirPlay2 播放链路。它的重点不是 metadata，而是完整 sender：

- mDNS 发现 AirPlay 设备。
- `GET /info` 获取设备能力。
- HomeKit transient pairing，HomePod 使用 HKP=4 和 PIN `3939`。
- 建立加密 RTSP 控制通道。
- 两阶段 AirPlay2 `SETUP`，body 为 binary plist。
- 建立 event TCP 连接和 control UDP 端口。
- `RECORD`、`FLUSH` 后发送 ALAC/AAC RTP 音频。
- NTP/PTP timing，PTP 用于 HomePod 和多房间同步。

可模仿的核心顺序：

```text
scan
connect tcp
GET /info
pair-setup or pair-verify
encrypted OPTIONS
SETUP phase 1
connect event port
bind control port
SETUP phase 2
RECORD
SET_PARAMETER volume/metadata
send RTP audio
periodic feedback
```

### Music Assistant

仓库：https://github.com/music-assistant/server

Music Assistant 是 Python 工程集成方式的参考。它没有把所有 AirPlay2 底层协议都写在 Python 里，而是用 Python 编排 provider，底层播放交给 native helper。这种架构更适合本项目。

## 推荐实现路线

### 阶段 1：建立可验证基线

先用 OwnTone 对同一个 HomePod 播放一首带 title/artist/album/artwork 的歌曲，并抓包确认 Home app 是否显示。

需要记录：

- HomePod 的 AirPlay features。
- OwnTone 是否选择 AirPlay2 还是 RAOP fallback。
- `SET_PARAMETER (text)` 的 Content-Type 和 body。
- `SET_PARAMETER (progress)` 的数值。
- metadata 请求中的 `RTP-Info`。
- artwork 请求的 Content-Type。

成功标准：OwnTone 播放时 Home app 能显示歌曲信息；抓包里能定位 metadata 请求。

### 阶段 2：Rust sidecar 验证 AirPlay2 播放

不要一开始纯 Python 重写 AirPlay2。建议先把 airplay2-rs 做成 sidecar：

- Rust 负责 AirPlay2 pairing、RTSP、RTP、ALAC、timing。
- Python 负责 DLNA、元数据解析、设备管理。
- 两边通过 stdin/stdout JSON、HTTP 或 WebSocket 通信。

建议 sidecar API：

```json
{"cmd":"discover"}
{"cmd":"play_url","device_id":"...","url":"...","title":"...","artist":"...","album":"...","duration":235}
{"cmd":"set_metadata","title":"...","artist":"...","album":"...","duration":235}
{"cmd":"set_artwork","content_type":"image/jpeg","data_base64":"..."}
{"cmd":"stop"}
```

成功标准：HomePod 能通过 AirPlay2 sender 会话稳定播放，且不中断当前 DLNA 控制流程。

### 阶段 3：实现 OwnTone 风格 metadata

在 AirPlay2 会话建立后实现三类 metadata：

1. text metadata

```text
SET_PARAMETER rtsp://<host>/<session>
Content-Type: application/x-dmap-tagged
RTP-Info: rtptime=<track_start_rtptime>

<DMAP tagged body>
```

2. progress metadata

```text
SET_PARAMETER rtsp://<host>/<session>
Content-Type: text/parameters
RTP-Info: rtptime=<track_start_rtptime>

progress: <display>/<pos>/<end>\r\n
```

3. artwork metadata

```text
SET_PARAMETER rtsp://<host>/<session>
Content-Type: image/jpeg
RTP-Info: rtptime=<track_start_rtptime>

<jpeg bytes>
```

DMAP 编码需要按 big-endian 写入：

```text
tag: 4 bytes ascii
length: 4 bytes uint32 be
payload: bytes
```

字符串 payload 使用 UTF-8。日文、希腊字母等非 ASCII 字符不要再做错误编码转换。

成功标准：

- Home app 显示 title。
- Home app 或控制中心显示 artist/album。
- artwork 能显示或至少不影响 text metadata。
- 切歌时 metadata 能跟随更新，不残留上一首。

### 阶段 4：再考虑 Python 纯实现

Python 可以实现控制面，但完整替代 Rust sidecar 成本较高。

Python 可优先实现：

- mDNS discovery：`zeroconf`
- binary plist：`plistlib`
- RTSP request/response：`asyncio.open_connection`
- DMAP metadata 编码
- HomeKit pairing：`cryptography` + SRP 实现

不建议第一阶段用 Python 实现：

- ALAC/AAC 实时编码
- RTP 精确发包和重传
- PTP timing
- 多房间同步

如果后续确实要纯 Python，建议先限定为单 HomePod、NTP timing、非多房间。

## 本项目落地建议

短期保留当前 pyatv RAOP 播放路径作为稳定 fallback。新增 AirPlay2 实验路径时，应独立于现有 `AirPlayOutput`：

```text
output/
  airplay_output.py              # 当前稳定 pyatv RAOP/DSP 路径
  airplay2_output.py             # 新 AirPlay2 sidecar 路径
  airplay2_sidecar_client.py     # Python 到 Rust helper 的通信层
```

配置建议：

```python
AIRPLAY_OUTPUT_MODE = "raop"      # raop | airplay2
AIRPLAY2_HELPER_PATH = "..."
AIRPLAY2_METADATA_ENABLED = True
```

不要再把 MRP tunnel、RAOP 强发 metadata、AirPlay `/play` direct URL 混在当前输出路径里。它们已经验证不能解决 HomePod Home app 显示问题，会增加后续排查噪音。

## 下一步检查清单

- 用 OwnTone 播放同一首歌确认 Home app 显示行为。
- 抓包保存 OwnTone 的 AirPlay2 metadata 请求样本。
- 运行 airplay2-rs 对 HomePod 播放 10 秒，确认本机网络和设备支持 AirPlay2 sender。
- 在 airplay2-rs 中补最小 DMAP text metadata 发送实验。
- 若 Rust 实验能显示歌名，再接入 Python sidecar。
