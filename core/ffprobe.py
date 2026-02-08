"""
FFprobe Utility - Get media information without decoding

Uses ffprobe (part of FFmpeg suite) to extract media metadata.
"""
import asyncio
import subprocess
import json
from typing import Optional, Dict, Any

from core.utils import log_debug, log_warning


async def probe_media(url: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """
    Asynchronously get media information using ffprobe.

    Args:
        url: Media URL to probe
        timeout: Timeout in seconds

    Returns:
        Dictionary with media info:
        {
            "codec": "mp3",
            "sample_rate": 44100,
            "bitrate": 320000,
            "channels": 2,
            "duration": 235.5,
            "title": "Song Title",
            "artist": "Artist Name",
            "album": "Album Name"
        }
        Returns None if probe fails.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            "-select_streams", "a:0",  # First audio stream only
            url
        ]

        # Run ffprobe in executor to avoid blocking
        loop = asyncio.get_running_loop()

        def run_ffprobe():
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='ignore'  # Ignore encoding errors
            )
            return result.stdout, result.stderr

        stdout, stderr = await loop.run_in_executor(None, run_ffprobe)

        if not stdout:
            log_warning("FFprobe", f"No output from ffprobe")
            return None

        data = json.loads(stdout)

        # Extract audio stream info
        streams = data.get("streams", [])
        format_info = data.get("format", {})

        if not streams:
            log_warning("FFprobe", "No audio streams found")
            return None

        audio_stream = streams[0]

        # Build result
        result = {
            "codec": audio_stream.get("codec_name", ""),
            "sample_rate": int(audio_stream.get("sample_rate", 0)),
            "channels": int(audio_stream.get("channels", 0)),
            "bitrate": 0,
            "duration": 0.0,
            "title": "",
            "artist": "",
            "album": ""
        }

        # Bitrate: try stream first, then format
        if "bit_rate" in audio_stream:
            result["bitrate"] = int(audio_stream["bit_rate"])
        elif "bit_rate" in format_info:
            result["bitrate"] = int(format_info["bit_rate"])

        # Duration: try stream first, then format
        if "duration" in audio_stream:
            result["duration"] = float(audio_stream["duration"])
        elif "duration" in format_info:
            result["duration"] = float(format_info["duration"])

        # Metadata tags: extract from format.tags (ID3, Vorbis, etc.)
        tags = format_info.get("tags", {})
        # Tag keys may be uppercase or lowercase depending on format
        for key in tags:
            key_lower = key.lower()
            if key_lower == "title":
                result["title"] = tags[key]
            elif key_lower == "artist":
                result["artist"] = tags[key]
            elif key_lower == "album":
                result["album"] = tags[key]
        return result

    except subprocess.TimeoutExpired:
        log_warning("FFprobe", f"Timeout probing media")
        return None
    except json.JSONDecodeError as e:
        log_warning("FFprobe", f"Failed to parse ffprobe output: {e}")
        return None
    except Exception as e:
        log_warning("FFprobe", f"Error probing media: {e}")
        return None


def format_bitrate(bitrate: int) -> str:
    """
    Format bitrate as human-readable string.

    Args:
        bitrate: Bitrate in bits per second

    Returns:
        Formatted string like "320 kbps"
    """
    if bitrate <= 0:
        return ""
    elif bitrate >= 1000000:
        return f"{bitrate // 1000000} Mbps"
    elif bitrate >= 1000:
        return f"{bitrate // 1000} kbps"
    else:
        return f"{bitrate} bps"
