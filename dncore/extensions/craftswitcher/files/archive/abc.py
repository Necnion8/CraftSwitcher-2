from typing import NamedTuple

__all__ = [
    "ArchiveProgress",
    "ArchiveFile",
]


class ArchiveProgress(NamedTuple):
    progress: float
    total_files: int = None
    total_size: int = None


class ArchiveFile(NamedTuple):
    filename: str
    size: int = None
    compressed_size: int = None
