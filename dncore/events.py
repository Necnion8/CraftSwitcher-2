from typing import TYPE_CHECKING

from dncore.event import Event

if TYPE_CHECKING:
    from dncore.plugin import Plugin

__all__ = [
    "PreShutdownEvent",
]


class PreShutdownEvent(Event):
    def __init__(self):
        self._worker_messages = {}  # type: dict[Plugin, str]

    def set_message(self, owner: "Plugin", message: str):
        self._worker_messages[owner] = message

    def clear_message(self, owner: "Plugin"):
        self._worker_messages.pop(owner, None)

    @property
    def messages(self):
        return self._worker_messages
