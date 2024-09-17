from pathlib import Path
from typing import TYPE_CHECKING

from dncore.event import Event
from .abc import FileTask

if TYPE_CHECKING:
    from watchdog.events import FileSystemEvent

__all__ = [
    "FileTaskStartEvent",
    "FileTaskEndEvent",
    "WatchdogCreatedEvent",
    "WatchdogDeletedEvent",
    "WatchdogModifiedEvent",
    "WatchdogMovedEvent",
]


class FileTaskStartEvent(Event):
    def __init__(self, task: FileTask):
        self.task = task


class FileTaskEndEvent(Event):
    def __init__(self, task: FileTask, error: Exception | None):
        self.task = task
        self.error = error


class WatchdogEvent:
    def __init__(self, swi_path: str | None, real_path: Path, event: "FileSystemEvent"):
        self.swi_path = swi_path
        self.real_path = real_path
        self.event = event


class WatchdogCreatedEvent(Event, WatchdogEvent):
    pass


class WatchdogDeletedEvent(Event, WatchdogEvent):
    pass


class WatchdogModifiedEvent(Event, WatchdogEvent):
    pass


class WatchdogMovedEvent(Event, WatchdogEvent):
    def __init__(self, swi_path: str | None, real_path: Path, event: "FileSystemEvent",
                 dst_swi_path: str | None, dst_real_path: Path, ):
        super().__init__(swi_path, real_path, event)
        self.dst_swi_path = dst_swi_path
        self.dst_real_path = dst_real_path
