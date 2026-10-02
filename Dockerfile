# language: Dockerfile, file: Dockerfile, target: Linux/OpenShift/Docker
# Enterprise Multi-Arch Docker Container for Telegram Restricted Content Bot & Web Studio

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8888 \
    SERVICE_TYPE=both

# Install essential system libraries, FFmpeg, fonts, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    git \
    curl \
    build-essential \
    libssl-dev \
    libffi-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency definition and install packages
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy all application source code
COPY . /app

# Create necessary runtime directories
RUN mkdir -p /app/downloads /app/sessions /app/data /app/scratch

# OpenShift & Non-Root container compliance:
# OpenShift assigns arbitrary random UIDs belonging to the root group (GID 0)
RUN chgrp -R 0 /app && \
    chmod -R g=u /app && \
    chmod +x /app/*.sh /app/docker-entrypoint.sh 2>/dev/null || true

# Expose Web Studio Cockpit port
EXPOSE 8888

# Use docker-entrypoint to manage Bot and Web Studio processes
ENTRYPOINT ["/bin/bash", "/app/docker-entrypoint.sh"]
