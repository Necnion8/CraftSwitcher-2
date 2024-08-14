from typing import TYPE_CHECKING

from dncore.event import Event, Cancellable
from dncore.extensions.craftswitcher.abc import ServerState

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher.serverprocess import ServerProcess

__all__ = [
    "ServerEvent",
    "ServerChangeStateEvent",
    "ServerPreStartEvent",
    "ServerLaunchOptionBuildEvent",
]


class ServerEvent:
    def __init__(self, server: "ServerProcess"):
        self.server = server


class ServerChangeStateEvent(Event, ServerEvent):
    def __init__(self, server: "ServerProcess", old_state: ServerState):
        super().__init__(server=server)
        self.old_state = old_state


class ServerPreStartEvent(Event, ServerEvent, Cancellable):
    _cancelled_reason: str | None

    @property
    def cancelled_reason(self) -> str | None:
        return getattr(self, "_cancelled_reason", None)

    @cancelled_reason.setter
    def cancelled_reason(self, reason: str):
        setattr(self, "_cancelled_reason", reason)
        self.cancelled = True


class ServerLaunchOptionBuildEvent(Event, ServerEvent):
    def __init__(self, server: "ServerProcess", args: list[str], *, is_generated: bool):
        super().__init__(server=server)
        self.args = list(args)
        self.__orig_args = args
        self.is_generated = is_generated

    @property
    def orig_args(self):
        return list(self.__orig_args)
