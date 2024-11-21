import asyncio
from enum import Enum
from typing import TYPE_CHECKING, TypeVar, Generator, Any, Generic

if TYPE_CHECKING:
    from pathlib import Path
    from dncore.extensions.craftswitcher import ServerProcess

__all__ = [
    "FileEventType",
    "FileTaskResult",
    "FileTask",
    "BackupType",
    "BackupTask",
]
_T = TypeVar("_T")


class FileEventType(Enum):
    COPY = "copy"
    MOVE = "move"
    DELETE = "delete"
    UPDATE = "update"
    CREATE = "create"
    EXTRACT_ARCHIVE = "extract_archive"
    CREATE_ARCHIVE = "create_archive"
    DOWNLOAD = "download"
    BACKUP = "backup"
    RESTORE_BACKUP = "restore_backup"


class FileTaskResult(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class BackupType(Enum):
    FULL = "full"
    SNAPSHOT = "snapshot"


class FileTask(Generic[_T]):
    def __init__(self, task_id: int, event_type: FileEventType, src: "Path", dst: "Path | None",
                 fut: "asyncio.Future[_T]",
                 server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None):
        self.id = task_id
        self.type = event_type
        self.src = src
        self.dst = dst
        self.fut = fut
        self.src_swi_path = src_swi_path
        self.dst_swi_path = dst_swi_path
        self.server = server
        self._progress = 0.0
        self.result = FileTaskResult.PENDING

    @property
    def progress(self):
        if self.fut.done():
            return 1.0
        return self._progress

    @progress.setter
    def progress(self, value: float):
        self._progress = value

    def __await__(self) -> Generator[Any, None, _T]:
        return self.fut.__await__()


class BackupTask(FileTask[int]):
    def __init__(self, task_id: int, src: "Path", fut: "asyncio.Future[int]",
                 server: "ServerProcess", comments: str | None, backup_type: BackupType):
        super().__init__(task_id, FileEventType.BACKUP, src, None, fut, server)
        self.comments = comments
        self.backup_type = backup_type

    @property
    def backup_id(self) -> int | None:
        try:
            return self.fut.result() if self.fut.done() else None
        except (asyncio.InvalidStateError, asyncio.CancelledError, Exception, ):
            pass
