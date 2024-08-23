from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
    from pathlib import Path

__all__ = [
    "FileEventType",
    "FileTaskResult",
    "FileTask",
]


class FileEventType(Enum):
    COPY = "copy"
    MOVE = "move"
    DELETE = "delete"
    UPDATE = "update"
    CREATE = "create"


class FileTaskResult(Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class FileTask(object):
    def __init__(self, task_id: int, event_type: FileEventType, src: "Path", dst: "Path | None", fut: "asyncio.Future"):
        self.id = task_id
        self.type = event_type
        self.src = src
        self.dst = dst
        self.fut = fut
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

    def __await__(self):
        return self.fut.__await__()
