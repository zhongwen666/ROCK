# Ubuntu GUI Sandbox Design

## Context

ROCK currently lets SDK users operate a sandbox through command execution, sessions, file APIs, and proxy routes. The new GUI work should support Ubuntu sandboxes first. The SDK should only send GUI instructions; it should not install or bootstrap GUI dependencies at call time.

The GUI runtime will be provided by a dedicated Ubuntu-based image. SDK GUI methods will assume that image contract is already satisfied.

## Goals

- Provide an Ubuntu 22.04 GUI sandbox image suitable for programmatic GUI interaction.
- Keep SDK GUI methods thin: validate inputs, run a command in the sandbox, and return command results or screenshot data.
- Support pyautogui-style operations from the SDK:
  - readiness check
  - screenshot
  - click, double click, right click, move, drag
  - typewrite, press, key down, key up, hotkey
  - scroll
- Allow browser-based visual observation through noVNC when the image starts that optional service.

## Non-Goals

- Windows or macOS GUI support.
- Runtime installation of Xvfb, window manager, pyautogui, or noVNC from SDK methods.
- Full desktop productization, user management, or persistent GUI session orchestration beyond the image entrypoint.
- Replacing existing sandbox command/session APIs.

## Recommended Image

Create a `rock-ubuntu-gui` image based on `ubuntu:22.04`.

The image should include:

- Python 3 and pip
- Xvfb for a virtual X11 display
- openbox as a lightweight window manager
- pyautogui and its Linux screenshot/input dependencies
- x11-utils, xdotool, scrot, python3-tk, python3-dev, and common fonts
- x11vnc, websockify, and noVNC for optional browser observation on port 8006
- an entrypoint script that starts Xvfb, openbox, and optional noVNC services

Default display contract:

- `DISPLAY=:99`
- screen size defaults to `1280x720x24`
- noVNC listens on `0.0.0.0:8006` when enabled
- noVNC is enabled by default and can be disabled with `ROCK_GUI_ENABLE_NOVNC=false`
- the default image tag used in docs and tests is `rock-ubuntu-gui:22.04`

## SDK Contract

The SDK client does not import or depend on pyautogui locally. Each GUI method executes a short Python command inside the sandbox using the existing session/run mechanism.

The SDK should provide a small GUI facade, for example `sandbox.gui`, to keep GUI methods separate from general sandbox lifecycle methods.

Expected behavior:

- `check_ready()` verifies that `DISPLAY` is set and that `pyautogui` can query screen size.
- Mouse and keyboard methods call the matching pyautogui operation in the sandbox.
- `screenshot()` captures an image to a sandbox temporary path, reads it through existing file APIs, and returns the image content to the caller.
- Methods fail clearly when the image contract is not met, for example missing `DISPLAY`, missing pyautogui, or no active X server.

## Data Flow

1. User creates a sandbox with the GUI image through `SandboxConfig.image`.
2. Image entrypoint starts the virtual display and window manager.
3. User calls an SDK GUI method.
4. SDK formats a sandbox-side Python snippet and runs it through the existing command/session path.
5. The snippet imports pyautogui and performs the action against the sandbox display.
6. SDK returns the command result or screenshot payload to the caller.

noVNC is a parallel observation path. Existing platform VNC proxy routes forward browser traffic to sandbox port 8006, but SDK GUI actions do not require that service to be reachable.

## Error Handling

GUI methods should surface actionable messages:

- Missing `DISPLAY`: "GUI display is not configured; use the Ubuntu GUI image or start Xvfb."
- Missing pyautogui: "pyautogui is not installed in the sandbox image."
- X server unavailable: "Cannot connect to the sandbox display."
- Invalid coordinates or keys: return validation errors before running the sandbox command where practical.
- Screenshot failure: include the sandbox-side stderr and suggested readiness check.

## Testing

Unit tests should cover SDK command construction and validation without requiring a real GUI.

Image verification should run in Docker or a ROCK sandbox and confirm:

- `check_ready()` succeeds.
- screen size is reported as `1280x720` by default.
- a screenshot can be produced.
- click and keyboard operations execute without pyautogui errors.
- noVNC responds on port 8006 when enabled.

## Implementation Defaults

- Use `rock-ubuntu-gui:22.04` as the local/default image tag in documentation and tests. Deployment environments may retag it for their registry.
- Use sandbox temporary files for screenshot capture, then return content through SDK file reads.
- Start noVNC by default because it improves debugging and works with the existing platform VNC proxy route. Allow operators to disable it with `ROCK_GUI_ENABLE_NOVNC=false`.
