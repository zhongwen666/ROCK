import asyncio
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psutil
from typing_extensions import Self

from rock.actions import (
    AbstractSandbox,
    CloseResponse,
    CloseSessionResponse,
    CommandResponse,
    CreateSessionResponse,
    EnvCloseResponse,
    EnvListResponse,
    EnvMakeResponse,
    EnvResetResponse,
    EnvStepResponse,
    IsAliveResponse,
    LocalSandboxRuntimeConfig,
    Observation,
    ReadFileRequest,
    ReadFileResponse,
    UploadRequest,
    UploadResponse,
    WriteFileRequest,
    WriteFileResponse,
)
from rock.admin.proto.request import SandboxAction as Action
from rock.admin.proto.request import SandboxCloseSessionRequest as CloseSessionRequest
from rock.admin.proto.request import SandboxCommand as Command
from rock.admin.proto.request import SandboxCreateBashSessionRequest as CreateBashSessionRequest
from rock.admin.proto.request import SandboxCreateSessionRequest as CreateSessionRequest
from rock.admin.proto.request import SandboxReadFileRequest as ReadFileRequest
from rock.admin.proto.request import SandboxWriteFileRequest as WriteFileRequest
from rock.logger import init_logger
from rock.rocklet.exceptions import (
    CommandTimeoutError,
    NonZeroExitCodeError,
    SessionDoesNotExistError,
    SessionExistsError,
)
from rock.rocklet.platforms import PlatformAdapter, Session, get_platform_adapter

# Backward-compat re-exports: external callers historically imported these
# names from `rock.rocklet.local_sandbox`. Keep them working.
_back_compat: list[str] = ["LocalSandboxRuntime", "Session", "PlatformAdapter"]
try:
    # PEP 484 explicit re-export form: `X as X` tells type checkers (Pylance/
    # mypy) that the import is intentional, while the `_back_compat.append`
    # below makes it discoverable via `__all__`.
    from rock.rocklet.platforms.linux import BashSession as BashSession  # noqa: F401

    _back_compat.append("BashSession")
except ImportError:
    # On platforms without pexpect/bashlex (e.g. Windows), BashSession is not
    # importable. This matches the pre-refactor behavior.
    pass
try:
    from rock.rocklet.platforms.windows import PowerShellSession as PowerShellSession  # noqa: F401

    _back_compat.append("PowerShellSession")
except ImportError:
    pass

__all__ = _back_compat


logger = init_logger("rock.actions.local")


class LocalSandboxRuntime(AbstractSandbox):
    def __init__(self, *, executor: ThreadPoolExecutor | None = None, **kwargs: Any):
        """A Runtime that runs locally and actually executes commands in a shell.
        If you are deploying to Modal/Fargate/etc., this class will be running within the docker container
        on Modal/Fargate/etc.

        Args:
            **kwargs: Keyword arguments (see `LocalSandboxConfig` for details).
        """
        self._config = LocalSandboxRuntimeConfig(**kwargs)
        self._sessions: dict[str, Session] = {}
        # Set up logger
        self.command_logger = init_logger("command", "command.log")
        self._executor = executor
        self._gem_envs: dict[str, Any] = {}
        self._platform: PlatformAdapter = get_platform_adapter()

    @classmethod
    def from_config(cls, config: LocalSandboxRuntimeConfig) -> Self:
        return cls(**config.model_dump())

    @property
    def sessions(self) -> dict[str, Session]:
        return self._sessions

    async def is_alive(self, *, timeout: float | None = None) -> IsAliveResponse:
        """Checks if the runtime is alive."""
        return IsAliveResponse(is_alive=True)

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """Creates a new session.

        Delegates to the platform adapter's `build_bash_session`, which selects
        BashSession on Linux/macOS and PowerShellSession on Windows.
        """
        if request.session in self.sessions:
            msg = f"session {request.session} already exists"
            raise SessionExistsError(msg)
        if isinstance(request, CreateBashSessionRequest):
            session = self._platform.build_bash_session(request)
        else:
            msg = f"unknown session type: {request!r}"
            raise ValueError(msg)
        self.sessions[request.session] = session
        self.command_logger.info(f"[create_session]:{request.session} (platform={self._platform.name})")
        return await session.start()

    async def run_in_session(self, action: Action) -> Observation:
        """Runs a command in a session."""
        if action.session not in self.sessions:
            msg = f"session {action.session!r} does not exist"
            raise SessionDoesNotExistError(msg)
        self.command_logger.info(f"[run_in_session input][{action.session}]:{action.command}")
        observation = await self.sessions[action.session].run(action)
        if observation.output:
            self.command_logger.info(f"[run_in_session output][{action.session}]:{observation.output}")
        if observation.exit_code:
            self.command_logger.info(f"[run_in_session exit_code][{action.session}]:{observation.exit_code}")
        if observation.failure_reason:
            self.command_logger.info(f"[run_in_session failure_reason][{action.session}]:{observation.failure_reason}")
        return observation

    async def close_session(self, request: CloseSessionRequest) -> CloseSessionResponse:
        """Closes a shell session."""
        if request.session not in self.sessions:
            msg = f"session {request.session!r} does not exist"
            raise SessionDoesNotExistError(msg)
        out = await self.sessions[request.session].close()
        del self.sessions[request.session]
        self.command_logger.info(f"[close_session]:{request.session}")
        return out

    async def execute(self, command: Command) -> CommandResponse:
        """Executes a command (independent of any shell session).

        Raises:
            CommandTimeoutError: If the command times out.
            NonZeroExitCodeError: If the command has a non-zero exit code and `check` is True.
        """
        self.command_logger.info(f"[execute input]:{command.command}")
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(self._executor, self._run_subprocess_blocking, command)
            r = CommandResponse(
                stdout=result.stdout.decode(errors="backslashreplace"),
                stderr=result.stderr.decode(errors="backslashreplace"),
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired as e:
            msg = f"Timeout ({command.timeout}s) exceeded while running command"
            raise CommandTimeoutError(msg) from e
        if command.check and result.returncode != 0:
            msg = (
                f"Command {command.command!r} failed with exit code {result.returncode}. "
                f"Stdout:\n{r.stdout!r}\nStderr:\n{r.stderr!r}"
            )
            if command.error_msg:
                msg = f"{command.error_msg}: {msg}"
            raise NonZeroExitCodeError(msg)
        if r.stdout:
            self.command_logger.info(f"[execute stdout]:{r.stdout}")
        if r.stderr:
            self.command_logger.info(f"[execute stderr]:{r.stderr}")
        return r

    def _run_subprocess_blocking(self, command: Command):
        # This is synchronous blocking code
        return subprocess.run(
            command.command,
            shell=command.shell,
            timeout=command.timeout,
            env=command.env,
            capture_output=True,
            cwd=command.cwd,
        )

    async def read_file(self, request: ReadFileRequest) -> ReadFileResponse:
        """Reads a file"""
        self.command_logger.info(f"[read_file input]: {request.path}")
        content = Path(request.path).read_text(encoding=request.encoding, errors=request.errors)
        self.command_logger.info(f"[read_file output]: {content[:1000]}")
        return ReadFileResponse(content=content)

    async def write_file(self, request: WriteFileRequest) -> WriteFileResponse:
        """Writes a file"""
        self.command_logger.info(f"[write_file input]: {request.path}")
        self.command_logger.info(f"[write_file content]: {request.content[:1000]}")
        Path(request.path).parent.mkdir(parents=True, exist_ok=True)
        Path(request.path).write_text(request.content)
        return WriteFileResponse(success=True)

    async def upload(self, request: UploadRequest) -> UploadResponse:
        """Uploads a file"""
        self.command_logger.info(f"[upload source]: {request.source_path}")
        self.command_logger.info(f"[upload target]: {request.target_path}")
        if Path(request.source_path).is_dir():
            shutil.copytree(request.source_path, request.target_path)
        else:
            shutil.copy(request.source_path, request.target_path)
        self.command_logger.info("[upload output]: upload success!")
        return UploadResponse()

    async def close(self) -> CloseResponse:
        """Closes the runtime."""
        for session in self.sessions.values():
            await session.close()
        return CloseResponse()

    async def get_statistics(self):
        cpu_percent: float = psutil.cpu_percent()
        mem_percent: float = psutil.virtual_memory().percent
        disk_path = self._platform.disk_root_path
        disk_percent: float = psutil.disk_usage(disk_path).percent
        net_io: int = psutil.net_io_counters().bytes_recv + psutil.net_io_counters().bytes_sent
        return {
            "cpu": cpu_percent,
            "mem": mem_percent,
            "disk": disk_percent,
            "net": net_io,
        }

    def env_make(self, env_id: str, sandbox_id: str) -> EnvMakeResponse:
        """
        Make gem env
        """
        import gem

        env = gem.make(env_id)
        self._gem_envs[sandbox_id] = env
        return EnvMakeResponse(sandbox_id=sandbox_id)

    def env_step(self, sandbox_id: str, action: str) -> EnvStepResponse:
        """
        Step gem env
        """
        env = self._gem_envs[sandbox_id]
        observation, reward, terminated, truncated, info = env.step(action)
        return EnvStepResponse(
            observation=observation,
            reward=reward,
            terminated=terminated,
            truncated=truncated,
            info=info,
        )

    def env_reset(self, sandbox_id: str, seed: int | None = None) -> EnvResetResponse:
        """
        Reset gem env
        """
        env = self._gem_envs[sandbox_id]
        observation, info = env.reset(seed=seed)
        return EnvResetResponse(observation=observation, info=info)

    def env_close(self, sandbox_id: str) -> EnvCloseResponse:
        """
        Close gem env
        """
        del self._gem_envs[sandbox_id]
        return EnvCloseResponse(sandbox_id=sandbox_id)

    def env_list(self) -> EnvListResponse:
        """
        List gem env
        """
        from gem.envs.registration import ENV_REGISTRY

        return EnvListResponse(env_id=list(ENV_REGISTRY))
