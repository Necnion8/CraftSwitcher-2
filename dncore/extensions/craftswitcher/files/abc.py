import asyncio
from enum import Enum
from typing import TYPE_CHECKING, TypeVar, Generator, Any, Generic
from uuid import UUID

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
        self._progress = None  # type: float | None
        self.result = FileTaskResult.PENDING

    @property
    def progress(self) -> float | None:
        if self.fut.done():
            return 1.0
        return self._progress

    @progress.setter
    def progress(self, value: float | None):
        self._progress = value

    def __await__(self) -> Generator[Any, None, _T]:
        return self.fut.__await__()


class BackupTask(FileTask[UUID]):
    def __init__(self, task_id: int, src: "Path", fut: "asyncio.Future[UUID]",
                 server: "ServerProcess", comments: str | None, backup_type: BackupType, backup_id: UUID):
        super().__init__(task_id, FileEventType.BACKUP, src, None, fut, server)
        self.comments = comments
        self.backup_type = backup_type
        self.backup_id = backup_id
