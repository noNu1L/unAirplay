FROM python:3.11-slim

# Install system dependencies
# - ffmpeg: for audio processing
# - libportaudio2: for sounddevice (local audio output)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libportaudio2 \
    libportaudiocpp0 \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose ports
# 8088: DLNA HTTP service
# 8089: Web control panel
# 1900/udp: SSDP multicast discovery
EXPOSE 8088 8089 1900/udp

# Run the application
CMD ["python", "run.py"]
