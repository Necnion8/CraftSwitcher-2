import asyncio
import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ..files import FileTask, FileEventType

if TYPE_CHECKING:
    from ..serverprocess import ServerProcess

__all__ = [
    "SnapshotStatus",
    "FileInfo",
    "FileDifference",
    "BackupTask",
]


class SnapshotStatus(Enum):
    DELETE = -1
    LINK = 0
    CREATE = 1
    UPDATE = 2


class FileInfo(NamedTuple):
    size: int
    update: datetime.datetime

    def __eq__(self, other: "FileInfo"):
        return self.size == other.size and self.update == other.update


class FileDifference(NamedTuple):
    path: Path
    old_info: FileInfo | None
    new_info: FileInfo | None
    status: SnapshotStatus


class BackupTask(FileTask[int]):
    def __init__(self, task_id: int, src: "Path", fut: "asyncio.Future[int]",
                 server: "ServerProcess", comments: str | None):
        super().__init__(task_id, FileEventType.BACKUP, src, None, fut, server)
        self.comments = comments
