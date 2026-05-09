"""Platform adapters for Rocklet's local sandbox runtime.

This subpackage centralizes all OS-specific differences (which Session
implementation to use, where the disk root is, etc.) behind a single
`PlatformAdapter` abstraction. The concrete adapter for the current OS is
chosen lazily by `get_platform_adapter()`.

Adding a new platform (e.g. Android):
    1. Create `platforms/<name>.py` with a `Session` subclass and a
       `<Name>PlatformAdapter(PlatformAdapter)` class.
    2. Add a `case` arm below that lazy-imports and returns the new adapter.
    3. No other file needs to change.
"""

import sys
from functools import lru_cache

from rock.rocklet.exceptions import UnsupportedPlatformError

from .base import PlatformAdapter, Session

__all__ = ["PlatformAdapter", "Session", "get_platform_adapter"]


@lru_cache(maxsize=1)
def get_platform_adapter() -> PlatformAdapter:
    """Return the PlatformAdapter for the current OS (cached singleton).

    Lazy-imports the platform-specific module so that, e.g., pexpect is never
    loaded on Windows and the Windows-only modules are never executed on Linux.

    Raises:
        UnsupportedPlatformError: if sys.platform has no adapter.
    """
    match sys.platform:
        case "linux" | "darwin":
            from .linux import LinuxPlatformAdapter

            return LinuxPlatformAdapter()
        case "win32":
            from .windows import WindowsPlatformAdapter

            return WindowsPlatformAdapter()
        case other:
            raise UnsupportedPlatformError(f"No PlatformAdapter registered for sys.platform={other!r}")
