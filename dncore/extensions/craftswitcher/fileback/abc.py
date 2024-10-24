import asyncio
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

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


class BackupTask(object):
    def __init__(self, server: "ServerProcess", source_dir: Path, comments: str | None, task: asyncio.Future):
        self.server = server
        self.source_dir = source_dir
        self.comments = comments
        self.task = task
        self._progress = 0.0

    @property
    def progress(self):
        return 1.0 if self.task.done() else self._progress

    @progress.setter
    def progress(self, value: float):
        self._progress = value

    def __await__(self):
        return self.task.__await__()
