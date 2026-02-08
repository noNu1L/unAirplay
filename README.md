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

### 1. Deploy with Docker Hub Image (Recommended)

Pull and run the pre-built Docker image:

```bash
docker run -d \
  --name un-airplay \
  --network host \
  --restart unless-stopped \
  youmiepie/un-airplay:latest
```

**Docker Hub**: [youmiepie/un-airplay](https://hub.docker.com/r/youmiepie/un-airplay)

**Supported Platforms**:
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM64/Apple Silicon)

### 2. Build Docker Image Locally (Alternative)

If you have network issues pulling from Docker Hub, you can build locally:

Clone the source code:

```bash
git clone https://github.com/noNu1L/unAirplay
cd unAirplay/docker
```

Start the service:

```bash
docker compose up -d
```

### 3. Run Locally

**Prerequisites:**
- **FFmpeg**: Required for audio processing. Must be installed and added to system PATH.
  - **Windows**:
    - Option 1: `winget install ffmpeg`
    - Option 2: Download from [ffmpeg.org](https://ffmpeg.org/download.html), extract to your installation directory (e.g., `C:\Program Files\ffmpeg`), and add the `bin` folder to system PATH (System Properties → Environment Variables → Path → New)
  - **Linux**: `sudo apt install ffmpeg`
  - **macOS**: `brew install ffmpeg`

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

- **About Audio Quality**: Some Android music apps may have lower original stream quality when pushing from non-playback screens (i.e., non-direct URL push mode). In this case, enabling spectral enhancement in DSP can improve the listening experience to some extent.
- **Current Song Finishes but Next Song Doesn't Play**: If this happens when using in-app DLNA casting on Android, try disabling "Ignore Battery Optimization" or removing the app from the "High Power Consumption Whitelist" in your phone's battery settings.
- **About DSP Modes**: CPU usage: FIR > IIR >= FFT. Audio quality: FIR >= FFT > IIR. IIR mode has lower latency (zero delay), while FFT mode provides better CPU efficiency. Choose based on your priorities: latency vs. resource consumption.
