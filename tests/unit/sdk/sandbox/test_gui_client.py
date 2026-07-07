import base64
import types

import pytest

from rock.actions import Command
from rock.actions.sandbox.response import CommandResponse
from rock.sdk.sandbox.client import Sandbox
from rock.sdk.sandbox.config import SandboxConfig
from rock.sdk.sandbox.gui import DEFAULT_SCREENSHOT_DIR, Gui, GuiScreenshot


def test_sandbox_exposes_gui_facade():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))

    assert isinstance(sandbox.gui, Gui)


@pytest.mark.asyncio
async def test_gui_start_runs_image_command():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))
    commands = []

    async def fake_execute(self, command):
        commands.append(command)
        return CommandResponse(stdout="started", exit_code=0)

    sandbox.execute = types.MethodType(fake_execute, sandbox)  # type: ignore

    result = await sandbox.gui.start()

    assert result.exit_code == 0
    assert commands == [Command(command=["bash", "-lc", "rock-gui-start"], timeout=90)]


@pytest.mark.asyncio
async def test_gui_click_validates_coordinates():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))

    with pytest.raises(ValueError, match="x must be >= 0"):
        await sandbox.gui.click(-1, 10)


@pytest.mark.asyncio
async def test_gui_click_runs_pyautogui_in_sandbox():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))
    commands = []

    async def fake_execute(self, command):
        commands.append(command)
        return CommandResponse(stdout="ok", exit_code=0)

    sandbox.execute = types.MethodType(fake_execute, sandbox)  # type: ignore

    result = await sandbox.gui.click(12, 34)

    assert result.exit_code == 0
    assert len(commands) == 1
    assert commands[0].timeout == 90
    assert commands[0].command[:2] == ["bash", "-lc"]
    assert "DISPLAY=:99 python3 - <<'PY'" in commands[0].command[2]
    assert "pyautogui.click(12, 34)" in commands[0].command[2]


@pytest.mark.asyncio
async def test_gui_typewrite_json_escapes_text():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))
    commands = []

    async def fake_execute(self, command):
        commands.append(command)
        return CommandResponse(stdout="ok", exit_code=0)

    sandbox.execute = types.MethodType(fake_execute, sandbox)  # type: ignore

    await sandbox.gui.typewrite('hello "rock"')

    assert 'pyautogui.typewrite("hello \\"rock\\"")' in commands[0].command[2]


@pytest.mark.asyncio
async def test_gui_hotkey_requires_at_least_one_key():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))

    with pytest.raises(ValueError, match="at least one key"):
        await sandbox.gui.hotkey()


@pytest.mark.asyncio
async def test_gui_screenshot_decodes_base64_output():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))
    png = b"fake-png"
    encoded = base64.b64encode(png).decode("ascii")

    async def fake_execute(self, command):
        assert command.timeout == 90
        assert "scrot" in command.command[2]
        assert "base64.b64encode" in command.command[2]
        return CommandResponse(stdout=f"noise\n{encoded}\n", exit_code=0)

    sandbox.execute = types.MethodType(fake_execute, sandbox)  # type: ignore

    result = await sandbox.gui.screenshot(path="/tmp/example.png")

    assert isinstance(result, GuiScreenshot)
    assert result.content == png
    assert result.mime_type == "image/png"
    assert result.path == "/tmp/example.png"
    assert result.response.exit_code == 0


@pytest.mark.asyncio
async def test_gui_screenshot_uses_userdefined_logs_by_default():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))
    png = b"fake-png"
    encoded = base64.b64encode(png).decode("ascii")

    async def fake_execute(self, command):
        assert f"path={DEFAULT_SCREENSHOT_DIR}/rock-gui-screenshot-" in command.command[2]
        assert 'mkdir -p "${parent}"' in command.command[2]
        return CommandResponse(stdout=f"{encoded}\n", exit_code=0)

    sandbox.execute = types.MethodType(fake_execute, sandbox)  # type: ignore

    result = await sandbox.gui.screenshot()

    assert result.content == png
    assert result.path.startswith(f"{DEFAULT_SCREENSHOT_DIR}/rock-gui-screenshot-")
    assert result.path.endswith(".png")


@pytest.mark.asyncio
async def test_gui_screenshot_failure_returns_empty_content():
    sandbox = Sandbox(SandboxConfig(image="mock-image"))

    async def fake_execute(self, command):
        return CommandResponse(stdout="boom", stderr="failed", exit_code=1)

    sandbox.execute = types.MethodType(fake_execute, sandbox)  # type: ignore

    result = await sandbox.gui.screenshot()

    assert result.content == b""
    assert result.response.exit_code == 1
