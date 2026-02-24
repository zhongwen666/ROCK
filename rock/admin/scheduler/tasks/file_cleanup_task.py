# rock/admin/scheduler/tasks/file_cleanup_task.py
from rock.admin.proto.request import SandboxCommand as Command
from rock.admin.scheduler.task_base import BaseTask, IdempotencyType, TaskStatusEnum
from rock.common.constants import SCHEDULER_LOG_NAME
from rock.logger import init_logger
from rock.sandbox.remote_sandbox import RemoteSandboxRuntime
from rock.utils.format import parse_size_to_bytes

logger = init_logger(name="file_cleanup", file_name=SCHEDULER_LOG_NAME)


class FileCleanupTask(BaseTask):
    """Scheduled task for cleaning up files based on modification time and file size,
    and removing empty directories afterwards."""

    def __init__(
        self,
        interval_seconds: int = 86400,
        target_dirs: list[str] | None = None,
        max_age_seconds: int = 604800,
        max_file_size: str = "1G",
    ):
        """
        Initialize file cleanup task.

        Args:
            interval_seconds: Execution interval in seconds, default 24 hours
            target_dirs: List of directories to clean up
            max_age_seconds: Max file age in seconds since last modification, default 7 days
            max_file_size: Max file size threshold (e.g. "500M", "1G"), files exceeding this will be removed
        """
        super().__init__(
            type="file_cleanup",
            interval_seconds=interval_seconds,
            idempotency=IdempotencyType.IDEMPOTENT,
        )
        self.target_dirs = target_dirs or []
        self.max_age_seconds = max_age_seconds
        self.max_file_size = max_file_size

    @classmethod
    def from_config(cls, task_config) -> "FileCleanupTask":
        """Create task instance from config."""
        params = task_config.params
        target_dirs = params.get("target_dirs", [])
        max_age_seconds = params.get("max_age_seconds", 604800)
        max_file_size = params.get("max_file_size", "1G")
        return cls(
            interval_seconds=task_config.interval_seconds,
            target_dirs=target_dirs,
            max_age_seconds=max_age_seconds,
            max_file_size=max_file_size,
        )

    def _build_cleanup_command(self, target_dir: str) -> str:
        """Build the shell command for cleaning up files in a single directory.

        The command performs two steps:
        1. Delete files matching either condition: older than max_age_seconds OR larger than max_file_size
        2. Remove empty directories left behind

        Args:
            target_dir: The directory path to clean

        Returns:
            Shell command string
        """
        size_bytes = parse_size_to_bytes(self.max_file_size)
        # find uses -size with 'c' suffix for bytes
        size_find_expr = f"-size +{size_bytes}c"

        # Step 1: Delete files older than max_age_seconds OR exceeding max_file_size
        # Step 2: Remove empty directories (bottom-up with -depth)
        command = (
            f'if [ -d "{target_dir}" ]; then '
            f'find "{target_dir}" -type f '
            f"\\( -mmin +{self.max_age_seconds // 60} -o {size_find_expr} \\) "
            f"-delete 2>/dev/null; "
            f'find "{target_dir}" -depth -type d -empty -delete 2>/dev/null; '
            f'echo "cleanup_done"; '
            f'else echo "dir_not_found"; fi'
        )
        return command

    async def run_action(self, runtime: RemoteSandboxRuntime) -> dict:
        """Run file cleanup action on the worker.

        Iterates over all configured target directories, deletes qualifying files,
        and removes empty directories.

        Args:
            runtime: RemoteSandboxRuntime instance for the worker

        Returns:
            Result dict with cleanup details
        """
        if not self.target_dirs:
            logger.warning("No target directories configured for file cleanup task")
            return {"status": TaskStatusEnum.SUCCESS, "message": "no target directories configured"}

        results = {}
        has_error = False

        for target_dir in self.target_dirs:
            try:
                command = self._build_cleanup_command(target_dir)
                result = await runtime.execute(Command(command=command, shell=True))
                output = result.stdout.strip() if result.stdout else ""
                results[target_dir] = {
                    "exit_code": result.exit_code,
                    "output": output,
                }
                if result.exit_code != 0:
                    has_error = True
                    logger.error(f"File cleanup failed for directory '{target_dir}': exit_code={result.exit_code}")
                else:
                    logger.info(f"File cleanup completed for directory '{target_dir}': {output}")
            except Exception as e:
                has_error = True
                results[target_dir] = {"error": str(e)}
                logger.error(f"File cleanup exception for directory '{target_dir}': {e}")

        status = TaskStatusEnum.FAILED if has_error else TaskStatusEnum.SUCCESS
        return {
            "status": status,
            "target_dirs": self.target_dirs,
            "max_age_seconds": self.max_age_seconds,
            "max_file_size": self.max_file_size,
            "details": results,
        }
