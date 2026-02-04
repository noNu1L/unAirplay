# unAirplay

[English](README.md) | [中文](README_CN.md)

---

unAirplay is an audio bridging tool. It forwards DLNA/UPnP audio streams to AirPlay devices or the server's local speakers, allowing Android devices or music apps that don't support AirPlay to push audio to AirPlay devices.

This project integrates DSP (Digital Signal Processing) functionality for adjusting the output audio characteristics.

**Note:** Currently, this project has only been tested on HomePod (1st generation) devices and has not been fully tested on Sonos or other AirPlay brand devices.

## Features

- **Protocol Bridging**: Push audio from DLNA clients to AirPlay devices.
- **Local Output**: Support playing audio directly through the server's local sound card/speakers.
- **Web Control Panel**: Access at `http://<server-ip>:6089`, supports playback status monitoring and DSP audio adjustments (EQ, spectral enhancement, stereo widening, etc.).

## How to Use

### 1. Deploy with Docker (Recommended)

Clone the source code:

```bash
git clone https://github.com/noNu1L/unAirplay
cd unAirplay/docker
```

Start the service:

```bash
docker compose up -d
```

### 2. Run Locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the project:

```bash
python run.py
```

## Configuration

The project supports automatic discovery and configuration, usually ready to use upon startup.

- **Auto Discovery**: After startup, the program will automatically scan for AirPlay devices on the local network and generate virtual DLNA devices with the suffix `[D]`.
- **Server Speaker**: If the running environment has audio output capability, the program will generate a Server Speaker virtual bridge device by default.
- **Modify Settings**: Edit the `config.py` file for custom adjustments:
  - **Disable Local Playback**: Set `ENABLE_SERVER_SPEAKER = False` to disable the Server Speaker virtual device.
  - **Port Settings**: You can modify the Web page and service ports in the configuration file.

## FAQ

- **Software Compatibility**: Currently compatible with DLNA playback from NetEase Cloud Music, QQ Music, Kugou Music, Kuwo Music, and Migu Music. If media information shows as "None" on the Web page, it means the corresponding music software did not include that metadata when streaming.
- **About Audio Quality**: Some Android music apps may have lower original stream quality when pushing from non-playback screens (i.e., non-direct URL push mode). In this case, enabling spectral enhancement in DSP can improve the listening experience to some extent.
