import datetime
from pathlib import Path
from typing import TypeVar, Generic

__all__ = [
    "ServerFile",
    "ServerMCVersion",
    "ServerDownloader",
]


class ServerFile(object):
    def __init__(self, mc_version: str, build: str, download_url: str = None, downloaded_path: Path = None,
                 *, java_major_version: int = None, updated_datetime: datetime.datetime = None):
        self.mc_version = mc_version
        self.build = build
        self.download_url = download_url
        self.downloaded_path = downloaded_path
        self.java_major_version = java_major_version
        self.updated_datetime = updated_datetime

    # noinspection PyMethodMayBeStatic
    def is_require_build(self):
        return False


class ServerMCVersion(object):
    def __init__(self, mc_version: str, builds: "list[ServerFile] | None"):
        self.mc_version = mc_version
        self.builds = builds

    def clear_cache(self):
        self.builds = None

    async def _list_builds(self) -> list[ServerFile]:
        raise NotImplementedError

    async def list_builds(self) -> list[ServerFile]:
        if self.builds is None:
            self.builds = (await self._list_builds()) or []
        return self.builds


T = TypeVar("T", bound=ServerMCVersion)


class ServerDownloader(Generic[T]):
    def __init__(self):
        self.versions = None  # type: list[T] | None

    def clear_cache(self):
        self.versions = None

    async def _list_versions(self) -> list[T]:
        raise NotImplementedError

    async def list_versions(self) -> list[T]:
        if self.versions is None:
            self.versions = (await self._list_versions()) or []
        return self.versions
