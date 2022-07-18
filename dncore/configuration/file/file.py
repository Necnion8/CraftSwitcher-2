from abc import ABC
from pathlib import Path
from typing import Any, List, NamedTuple

from dncore.abc import ObjectSerializable
from dncore.configuration import ConfigValues, ConfigValueEntry

__all__ = ["FileDriver", "ParseError", "ConfigFileDriver"]


class ParseError(NamedTuple):
    key: str
    entry: ConfigValueEntry
    error: Exception


class FileDriver:
    def __init__(self, path: Path):
        self.path = path

    def load(self):
        raise NotImplementedError

    def save(self, data: Any | ObjectSerializable):
        raise NotImplementedError


class ConfigFileDriver(FileDriver, ABC):
    def load_to(self, config: ConfigValues) -> List[ParseError]:
        raise NotImplementedError

    def save_from(self, config: ConfigValues) -> List[ParseError]:
        raise NotImplementedError
