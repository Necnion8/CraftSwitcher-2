import asyncio
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ..files import FileTask, FileEventType

if TYPE_CHECKING:
    from ..serverprocess import ServerProcess

__all__ = [
    "SnapshotStatus",
    "BackupTask",
]


class SnapshotStatus(Enum):
    DELETE = -1
    LINK = 0
    CREATE = 1
    UPDATE = 2


class BackupTask(FileTask[int]):
    def __init__(self, task_id: int, src: "Path", fut: "asyncio.Future[int]",
                 server: "ServerProcess", comments: str | None):
        super().__init__(task_id, FileEventType.BACKUP, src, None, fut, server)
        self.comments = comments
