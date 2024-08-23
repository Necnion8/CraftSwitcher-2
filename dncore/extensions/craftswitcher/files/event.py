from dncore.event import Event
from .abc import FileTask

__all__ = [
    "FileTaskStartEvent",
    "FileTaskEndEvent",
]


class FileTaskStartEvent(Event):
    def __init__(self, task: FileTask):
        self.task = task


class FileTaskEndEvent(Event):
    def __init__(self, task: FileTask, error: Exception | None):
        self.task = task
        self.error = error
