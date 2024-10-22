from enum import Enum

__all__ = [
    "SnapshotStatus",
]


class SnapshotStatus(Enum):
    DELETE = -1
    LINK = 0
    CREATE = 1
    UPDATE = 2
