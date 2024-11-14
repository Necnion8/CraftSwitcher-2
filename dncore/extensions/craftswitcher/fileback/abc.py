import asyncio
import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from ..files import FileTask, FileEventType

if TYPE_CHECKING:
    from ..serverprocess import ServerProcess

__all__ = [
    "FileType",
    "SnapshotStatus",
    "SnapshotFileErrorType",
    "FileInfo",
    "FileDifference",
    "BackupTask",
]


class FileType(Enum):
    FILE = 0
    DIRECTORY = 1


class SnapshotStatus(Enum):
    DELETE = -1
    NO_CHANGE = 0
    UPDATE = 1
    CREATE = 2


class SnapshotFileErrorType(Enum):
    UNKNOWN = -1
    SCAN = 0
    CREATE_DIRECTORY = 1
    CREATE_LINK = 2
    COPY_FILE = 3


class FileInfo(NamedTuple):
    size: int
    modified_datetime: datetime.datetime
    is_dir: bool

    def __eq__(self, other: "FileInfo"):
        if self.is_dir != other.is_dir:
            return False
        if self.is_dir and other.is_dir:
            return True
        return self.size == other.size and self.modified_datetime == other.modified_datetime


class FileDifference(NamedTuple):
    path: str
    old_info: FileInfo | None
    new_info: FileInfo | None
    status: SnapshotStatus


class BackupTask(FileTask[int]):
    def __init__(self, task_id: int, src: "Path", fut: "asyncio.Future[int]",
                 server: "ServerProcess", comments: str | None):
        super().__init__(task_id, FileEventType.BACKUP, src, None, fut, server)
        self.comments = comments
