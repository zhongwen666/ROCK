FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV ROCK_GUI_DISPLAY=:99
ENV ROCK_GUI_WIDTH=1280
ENV ROCK_GUI_HEIGHT=720
ENV ROCK_GUI_DEPTH=24
ENV ROCK_GUI_ENABLE_NOVNC=true
ENV DISPLAY=:99

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    dbus-x11 \
    fonts-dejavu \
    fonts-noto-cjk \
    procps \
    python3 \
    python3-dev \
    python3-pip \
    python3-tk \
    scrot \
    websockify \
    x11-utils \
    x11vnc \
    xauth \
    xdotool \
    xfce4 \
    xfce4-terminal \
    xvfb \
    novnc \
    && python3 -m pip install --no-cache-dir pyautogui pillow \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY rock-gui-start /usr/local/bin/rock-gui-start
RUN chmod +x /usr/local/bin/rock-gui-start
