# ROCK Ubuntu GUI Image

This image provides an Ubuntu XFCE desktop and the dependencies for ROCK SDK
GUI automation. It is based on `ubuntu:22.04` and installs Python, pip, XFCE,
noVNC, and GUI automation dependencies during the image build.
It does not define or rely on Docker `ENTRYPOINT`; ROCK may override container
entrypoints during sandbox startup.

## Build

```bash
docker build -t rock-ubuntu-gui:22.04 docker/gui/ubuntu
```

## Start GUI Stack In A Running Sandbox

```bash
rock-gui-start
```

`rock-gui-start` starts `Xvfb`, an XFCE desktop session, and optional noVNC.
The image does not rely on Docker `ENTRYPOINT`.

Defaults:

- `DISPLAY=:99`
- `ROCK_GUI_WIDTH=1280`
- `ROCK_GUI_HEIGHT=720`
- `ROCK_GUI_DEPTH=24`
- `ROCK_GUI_ENABLE_NOVNC=true`
- `ROCK_GUI_NOVNC_PORT=8006`
- Desktop: XFCE

Disable noVNC:

```bash
ROCK_GUI_ENABLE_NOVNC=false rock-gui-start
```

## Verify

```bash
rock-gui-start
python3 - <<'PY'
import pyautogui
print(pyautogui.size())
pyautogui.screenshot('/tmp/rock-gui-check.png')
PY
```
