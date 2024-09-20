from enum import Enum
from pathlib import Path
from typing import NamedTuple, Any

__all__ = [
    "ServerState",
    "ServerType",
    "SystemMemoryInfo",
    "SystemPerformanceInfo",
    "ProcessInfo",
    "FileWatchInfo",
]


class ServerState(Enum):
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTED = "started"
    STARTING = "starting"
    STOPPING = "stopping"
    RUNNING = "running"
    BUILD = "build"

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN

    @property
    def is_running(self):
        return self not in (ServerState.STOPPED, ServerState.UNKNOWN, )

    def __lt__(self, other: "ServerState"):
        return _SERVER_STATE_VALUE.get(self, -1) < _SERVER_STATE_VALUE.get(other, -1)


_SERVER_STATE_VALUE = {
    ServerState.UNKNOWN: -1,
    ServerState.STOPPED: 0,
    ServerState.STOPPING: 1,
    ServerState.STARTING: 2,
    ServerState.STARTED: 3,
    ServerState.RUNNING: 3,
}


class _ServerType:
    def __init__(self, name: str, stop_command: str | None, is_proxy: bool, is_modded: bool):
        self.name = name
        self.stop_command = stop_command
        self.is_proxy = is_proxy
        self.is_modded = is_modded


class ServerType(Enum):
    UNKNOWN = "unknown"
    CUSTOM = "custom"
    VANILLA = "vanilla"
    # bukkit
    SPIGOT = "spigot"
    PAPER = "paper"
    PURPUR = "purpur"
    FOLIA = "folia"
    # forge
    FORGE = "forge"
    NEO_FORGE = "neo_forge"
    MOHIST = "mohist"
    YOUER = "youer"
    # fabric
    FABRIC = "fabric"
    BANNER = "banner"
    # proxy
    BUNGEECORD = "bungeecord"
    WATERFALL = "waterfall"
    VELOCITY = "velocity"

    @property
    def spec(self):
        return SERVER_TYPE_SPECS[self]

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN

    @classmethod
    def defaults(cls):
        return cls.UNKNOWN


SERVER_TYPE_SPECS = {
    ServerType.UNKNOWN: _ServerType("unknown", None, False, False),
    ServerType.CUSTOM: _ServerType("custom", None, False, False),
    ServerType.VANILLA: _ServerType("vanilla", "stop", False, False),
    ServerType.SPIGOT: _ServerType("spigot", "stop", False, False),
    ServerType.PAPER: _ServerType("paper", "stop", False, False),
    ServerType.PURPUR: _ServerType("purpur", "stop", False, False),
    ServerType.FOLIA: _ServerType("folia", "stop", False, False),
    ServerType.FORGE: _ServerType("forge", "stop", False, True),
    ServerType.NEO_FORGE: _ServerType("neo_forge", "stop", False, True),
    ServerType.MOHIST: _ServerType("mohist", "stop", False, True),
    ServerType.YOUER: _ServerType("youer", "stop", False, True),
    ServerType.FABRIC: _ServerType("fabric", "stop", False, True),
    ServerType.BANNER: _ServerType("banner", "stop", False, True),
    ServerType.BUNGEECORD: _ServerType("bungeecord", "end", True, False),
    ServerType.WATERFALL: _ServerType("waterfall", "end", True, False),
    ServerType.VELOCITY: _ServerType("velocity", "end", True, False),
}


class SystemMemoryInfo(NamedTuple):
    total_bytes: int
    available_bytes: int
    swap_total_bytes: int = -1
    swap_available_bytes: int = -1


class SystemPerformanceInfo(NamedTuple):
    cpu_usage: float


class ProcessInfo(NamedTuple):
    cpu_usage: float
    memory_used_size: int
    memory_virtual_used_size: int


class FileWatchInfo(NamedTuple):
    path: Path
    owner: Any
