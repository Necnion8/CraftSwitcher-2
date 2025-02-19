from enum import Enum
from pathlib import Path
from typing import NamedTuple, Any

__all__ = [
    "ServerState",
    "ServerType",
    "SystemMemoryInfo",
    "SystemPerformanceInfo",
    "DiskUsageInfo",
    "ProcessInfo",
    "FileWatchInfo",
    "JavaExecutableInfo",
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

    @property
    def old_value(self):
        try:
            return _SERVER_STATE_OLD_VALUE.index(self)
        except ValueError:
            return -1

    @classmethod
    def of_old_value(cls, int_value: int):
        if 0 <= int_value < len(_SERVER_STATE_OLD_VALUE):
            try:
                return _SERVER_STATE_OLD_VALUE[int_value]
            except IndexError:
                pass
        return cls.UNKNOWN


_SERVER_STATE_VALUE = {
    ServerState.UNKNOWN: -1,
    ServerState.STOPPED: 0,
    ServerState.STOPPING: 1,
    ServerState.STARTING: 2,
    ServerState.STARTED: 3,
    ServerState.RUNNING: 3,
}

_SERVER_STATE_OLD_VALUE = [
    ServerState.STOPPED,
    ServerState.STARTED,
    ServerState.STARTING,
    ServerState.STOPPING,
    ServerState.RUNNING,
]


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
    SPONGE_VANILLA = "sponge_vanilla"
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
    QUILT = "quilt"
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
    ServerType.SPONGE_VANILLA: _ServerType("sponge_vanilla", "stop", False, False),
    ServerType.SPIGOT: _ServerType("spigot", "stop", False, False),
    ServerType.PAPER: _ServerType("paper", "stop", False, False),
    ServerType.PURPUR: _ServerType("purpur", "stop", False, False),
    ServerType.FOLIA: _ServerType("folia", "stop", False, False),
    ServerType.FORGE: _ServerType("forge", "stop", False, True),
    ServerType.NEO_FORGE: _ServerType("neo_forge", "stop", False, True),
    ServerType.MOHIST: _ServerType("mohist", "stop", False, True),
    ServerType.YOUER: _ServerType("youer", "stop", False, True),
    ServerType.FABRIC: _ServerType("fabric", "stop", False, True),
    ServerType.QUILT: _ServerType("quilt", "stop", False, True),
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
    cpu_count: int


class DiskUsageInfo(NamedTuple):
    total_bytes: int
    used_bytes: int
    free_bytes: int


class ProcessInfo(NamedTuple):
    cpu_usage: float
    memory_used_size: int
    memory_virtual_used_size: int


class FileWatchInfo(NamedTuple):
    path: Path
    owner: Any


class JavaExecutableInfo(NamedTuple):
    path: Path
    runtime_version: str
    java_home_path: str | None
    java_major_version: int
    specification_version: str | None = None
    class_version: int | None = None
    vendor: str | None = None
    vendor_version: str | None = None
    is_jdk: bool = False
