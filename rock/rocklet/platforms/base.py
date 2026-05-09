from abc import ABC, abstractmethod

from rock.actions import (
    CloseSessionResponse,
    CreateSessionResponse,
    Observation,
)
from rock.admin.proto.request import SandboxAction as Action
from rock.admin.proto.request import SandboxCreateBashSessionRequest as CreateBashSessionRequest


class Session(ABC):
    """Abstract command session inside a sandbox.

    Concrete implementations (BashSession on POSIX, PowerShellSession on Windows,
    AdbShellSession on Android in the future) all conform to this contract.

    Signatures intentionally use the wide discriminated types
    (Action / Observation / CreateSessionResponse / CloseSessionResponse) to
    match the original Session ABC verbatim — concrete subclasses narrow them
    to their specific action/response types.
    """

    @abstractmethod
    async def start(self) -> CreateSessionResponse:
        ...

    @abstractmethod
    async def run(self, action: Action) -> Observation:
        ...

    @abstractmethod
    async def close(self) -> CloseSessionResponse:
        ...


class PlatformAdapter(ABC):
    """Encapsulates everything that differs between OS platforms in Rocklet's
    local sandbox runtime. One instance per process (cached by
    `get_platform_adapter()`).
    """

    name: str
    """Short identifier, e.g. 'linux', 'windows', 'android'. Used in logs."""

    disk_root_path: str
    """Root path used by `psutil.disk_usage()` in get_statistics()."""

    @abstractmethod
    def build_bash_session(self, request: CreateBashSessionRequest) -> Session:
        """Construct the platform's default command session for the request.

        Linux/macOS -> BashSession, Windows -> PowerShellSession,
        future Android -> AdbShellSession.
        """
