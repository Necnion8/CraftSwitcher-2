from typing import TYPE_CHECKING

from dncore.event import Event, Cancellable
from dncore.extensions.craftswitcher.abc import ServerState

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher.ext import ExtensionInfo
    from dncore.extensions.craftswitcher.serverprocess import ServerProcess

__all__ = [
    "ServerEvent",
    "ServerChangeStateEvent",
    "ServerPreStartEvent",
    "ServerBuildPreStartEvent",
    "ServerLaunchOptionBuildEvent",
    "ServerCreatedEvent",
    "ServerDeletedEvent",
    "ServerProcessReadEvent",
    "ServerProcessReadLinesEvent",
    "ServerScreenAttachPreEvent",
    "ServerScreenAttachEvent",
    "SwitcherInitializedEvent",
    "SwitcherShutdownEvent",
    "SwitcherConfigLoadedEvent",
    "SwitcherServersLoadedEvent",
    "SwitcherServersReloadedEvent",
    "SwitcherServersUnloadEvent",
    "ExtensionEvent",
    "SwitcherExtensionAddEvent",
    "SwitcherExtensionRemoveEvent",
]


class ServerEvent:
    def __init__(self, server: "ServerProcess"):
        self.server = server


class ServerChangeStateEvent(Event, ServerEvent):
    def __init__(self, server: "ServerProcess", old_state: ServerState):
        super().__init__(server=server)
        self.old_state = old_state
        self.new_state: ServerState = server.state


class ServerPreStartEvent(Event, ServerEvent, Cancellable):
    _cancelled_reason: str | None

    @property
    def cancelled_reason(self) -> str | None:
        return getattr(self, "_cancelled_reason", None)

    @cancelled_reason.setter
    def cancelled_reason(self, reason: str):
        setattr(self, "_cancelled_reason", reason)
        self.cancelled = True


class ServerBuildPreStartEvent(Event, ServerEvent):
    pass


class ServerLaunchOptionBuildEvent(Event, ServerEvent):
    def __init__(self, server: "ServerProcess", args: list[str], *, is_generated: bool):
        super().__init__(server=server)
        self.args = list(args)
        self.__orig_args = args
        self.is_generated = is_generated

    @property
    def orig_args(self):
        return list(self.__orig_args)


class ServerCreatedEvent(Event, ServerEvent):
    pass


class ServerDeletedEvent(Event, ServerEvent):
    pass


class ServerProcessReadEvent(Event, ServerEvent):
    def __init__(self, server: "ServerProcess", data: str):
        super().__init__(server)
        self.data = data


class ServerProcessReadLinesEvent(Event, ServerEvent):
    """
    プロセスから読み取った出力から改行コード(\\\\n)で終わる行ごとに処理します
    """
    def __init__(self, server: "ServerProcess", lines: list[str]):
        super().__init__(server)
        self.lines = lines


class ServerScreenAttachPreEvent(Event, ServerEvent):
    def __init__(self, server: "ServerProcess", session_name: str):
        super().__init__(server)
        self.session_name = session_name


class ServerScreenAttachEvent(Event, ServerEvent):
    def __init__(self, server: "ServerProcess", session_name: str, result: bool):
        super().__init__(server)
        self.session_name = session_name
        self.result = result


class SwitcherInitializedEvent(Event):
    pass


class SwitcherShutdownEvent(Event):
    pass


class SwitcherConfigLoadedEvent(Event):
    pass


class SwitcherServersLoadedEvent(Event):
    pass


class SwitcherServersReloadedEvent(Event):
    def __init__(self,
                 remove: "dict[str, ServerProcess]",
                 update: "dict[str, ServerProcess]",
                 new: "dict[str, ServerProcess | None]",
                 ):
        self.removed = remove
        self.updated = update
        self.added = new


class SwitcherServersUnloadEvent(Event):
    pass


class ExtensionEvent:
    def __init__(self, extension: "ExtensionInfo"):
        self.extension = extension


class SwitcherExtensionAddEvent(Event, ExtensionEvent):
    pass


class SwitcherExtensionRemoveEvent(Event, ExtensionEvent):
    pass
