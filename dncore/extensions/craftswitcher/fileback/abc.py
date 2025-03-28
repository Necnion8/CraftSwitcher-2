import datetime
from enum import Enum
from typing import NamedTuple

__all__ = [
    "FileType",
    "SnapshotStatus",
    "BackupFileErrorType",
    "FileInfo",
    "FileDifference",
]


class FileType(Enum):
    FILE = 0
    DIRECTORY = 1


class SnapshotStatus(Enum):
    DELETE = -1
    NO_CHANGE = 0
    UPDATE = 1
    CREATE = 2


class BackupFileErrorType(Enum):
    UNKNOWN = -1
    SCAN = 0
    CREATE_DIRECTORY = 1
    CREATE_LINK = 2
    COPY_FILE = 3
    EXISTS_CHECK = 4


class FileInfo(NamedTuple):
    size: int
    modified_datetime: datetime.datetime
    is_dir: bool

    def __eq__(self, other: "FileInfo"):
        if self.is_dir != other.is_dir:
            return False
        if (self.is_dir and other.is_dir) or self.size == other.size:
            return True
        dt = self.modified_datetime
        other_dt = other.modified_datetime
        if dt == other_dt:
            return True
        if dt.microsecond == 0 or other_dt.microsecond == 0:
            return int(dt.timestamp()) == int(other_dt.timestamp())
        return False


class FileDifference(NamedTuple):
    path: str
    old_info: FileInfo | None
    new_info: FileInfo | None
    status: SnapshotStatus
