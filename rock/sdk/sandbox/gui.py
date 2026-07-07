import base64
import json
import shlex
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rock.actions import Command, CommandResponse

if TYPE_CHECKING:
    from rock.sdk.sandbox.client import Sandbox


DEFAULT_SCREENSHOT_DIR = "/data/logs/userdefined"


@dataclass(frozen=True)
class GuiScreenshot:
    content: bytes
    mime_type: str
    path: str
    response: CommandResponse


class Gui:
    def __init__(self, sandbox: "Sandbox", display: str = ":99"):
        self._sandbox = sandbox
        self.display = display

    async def start(self, timeout: float = 90) -> CommandResponse:
        return await self._sandbox.execute(Command(command=["bash", "-lc", "rock-gui-start"], timeout=timeout))

    async def check_ready(self, timeout: float = 90) -> CommandResponse:
        code = """
import json
import os
import pyautogui

size = pyautogui.size()
print(json.dumps({
    "display": os.environ.get("DISPLAY"),
    "width": size.width,
    "height": size.height,
}))
""".strip()
        return await self._run_python(code, timeout=timeout)

    async def screenshot(self, path: str | None = None, timeout: float = 90) -> GuiScreenshot:
        screenshot_path = path or f"{DEFAULT_SCREENSHOT_DIR}/rock-gui-screenshot-{time.time_ns()}.png"
        script = f"""
set -euo pipefail
path={shlex.quote(screenshot_path)}
parent="$(dirname "${{path}}")"
mkdir -p "${{parent}}"
DISPLAY={shlex.quote(self.display)} scrot "${{path}}"
python3 - <<'PY'
import base64

path = {json.dumps(screenshot_path)}
with open(path, "rb") as file:
    print(base64.b64encode(file.read()).decode("ascii"))
PY
""".strip()
        response = await self._run_shell(script, timeout=timeout)
        if response.exit_code != 0:
            return GuiScreenshot(content=b"", mime_type="image/png", path=screenshot_path, response=response)

        encoded = response.stdout.strip().splitlines()[-1] if response.stdout.strip() else ""
        content = base64.b64decode(encoded) if encoded else b""
        return GuiScreenshot(content=content, mime_type="image/png", path=screenshot_path, response=response)

    async def click(self, x: int, y: int, timeout: float = 90) -> CommandResponse:
        self._validate_xy(x, y)
        return await self._call(f"pyautogui.click({x}, {y})", timeout=timeout)

    async def right_click(self, x: int, y: int, timeout: float = 90) -> CommandResponse:
        self._validate_xy(x, y)
        return await self._call(f"pyautogui.rightClick({x}, {y})", timeout=timeout)

    async def double_click(self, x: int, y: int, timeout: float = 90) -> CommandResponse:
        self._validate_xy(x, y)
        return await self._call(f"pyautogui.doubleClick({x}, {y})", timeout=timeout)

    async def move_to(self, x: int, y: int, timeout: float = 90) -> CommandResponse:
        self._validate_xy(x, y)
        return await self._call(f"pyautogui.moveTo({x}, {y})", timeout=timeout)

    async def drag_to(self, x: int, y: int, duration: float = 0.5, timeout: float = 90) -> CommandResponse:
        self._validate_xy(x, y)
        if duration < 0:
            raise ValueError("duration must be >= 0")
        return await self._call(f"pyautogui.dragTo({x}, {y}, duration={duration})", timeout=timeout)

    async def typewrite(self, text: str, timeout: float = 90) -> CommandResponse:
        return await self._call(f"pyautogui.typewrite({json.dumps(text)})", timeout=timeout)

    async def press(self, key: str, timeout: float = 90) -> CommandResponse:
        self._validate_key(key)
        return await self._call(f"pyautogui.press({json.dumps(key)})", timeout=timeout)

    async def key_down(self, key: str, timeout: float = 90) -> CommandResponse:
        self._validate_key(key)
        return await self._call(f"pyautogui.keyDown({json.dumps(key)})", timeout=timeout)

    async def key_up(self, key: str, timeout: float = 90) -> CommandResponse:
        self._validate_key(key)
        return await self._call(f"pyautogui.keyUp({json.dumps(key)})", timeout=timeout)

    async def hotkey(self, *keys: str, timeout: float = 90) -> CommandResponse:
        if not keys:
            raise ValueError("hotkey requires at least one key")
        for key in keys:
            self._validate_key(key)
        args = ", ".join(json.dumps(key) for key in keys)
        return await self._call(f"pyautogui.hotkey({args})", timeout=timeout)

    async def scroll(
        self,
        clicks: int,
        x: int | None = None,
        y: int | None = None,
        timeout: float = 90,
    ) -> CommandResponse:
        if x is None and y is None:
            return await self._call(f"pyautogui.scroll({clicks})", timeout=timeout)
        if x is None or y is None:
            raise ValueError("x and y must be provided together")
        self._validate_xy(x, y)
        return await self._call(f"pyautogui.scroll({clicks}, x={x}, y={y})", timeout=timeout)

    async def _call(self, expression: str, timeout: float = 90) -> CommandResponse:
        code = f"""
import pyautogui

{expression}
print("ok")
""".strip()
        return await self._run_python(code, timeout=timeout)

    async def _run_python(self, code: str, timeout: float = 90) -> CommandResponse:
        cmd = f"DISPLAY={shlex.quote(self.display)} python3 - <<'PY'\n{code}\nPY"
        return await self._run_shell(cmd, timeout=timeout)

    async def _run_shell(self, cmd: str, timeout: float = 90) -> CommandResponse:
        return await self._sandbox.execute(Command(command=["bash", "-lc", cmd], timeout=timeout))

    @staticmethod
    def _validate_xy(x: int, y: int) -> None:
        if x < 0:
            raise ValueError("x must be >= 0")
        if y < 0:
            raise ValueError("y must be >= 0")

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key:
            raise ValueError("key must not be empty")
