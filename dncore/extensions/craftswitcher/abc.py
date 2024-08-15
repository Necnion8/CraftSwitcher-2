from enum import Enum
from typing import NamedTuple

__all__ = [
    "ServerState",
    "ServerType",
    "SystemMemoryInfo",
]


class ServerState(Enum):
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTED = "started"
    STARTING = "starting"
    STOPPING = "stopping"
    RUNNING = "running"

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN

    @property
    def is_running(self):
        return self not in (ServerState.STOPPED, ServerState.UNKNOWN, )


class ServerType(Enum):
    class Spec:
        def __init__(self, name: str, stop_command: str | None, is_proxy: bool, is_modded: bool):
            self.name = name
            self.stop_command = stop_command
            self.is_proxy = is_proxy
            self.is_modded = is_modded

    UNKNOWN = Spec("unknown", None, False, False)
    CUSTOM = Spec("custom", None, False, False)
    VANILLA = Spec("vanilla", "stop", False, False)
    SPIGOT = Spec("spigot", "stop", False, False)
    PAPER = Spec("paper", "stop", False, False)
    FORGE = Spec("forge", "stop", False, True)
    NEO_FORGE = Spec("neo_forge", "stop", False, True)
    FABRIC = Spec("fabric", "stop", False, True)
    BUNGEECORD = Spec("bungeecord", "end", True, False)
    WATERFALL = Spec("waterfall", "end", True, False)
    VELOCITY = Spec("velocity", "end", True, False)

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN

    @classmethod
    def defaults(cls):
        return cls.UNKNOWN


class SystemMemoryInfo(NamedTuple):
    total_bytes: int
    available_bytes: int


class ProcessInfo(NamedTuple):
    cpu_usage: float
    memory_used_size: int
    memory_used_total_size: int

