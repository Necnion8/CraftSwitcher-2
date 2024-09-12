import datetime
from pathlib import Path
from typing import TypeVar, Generic

__all__ = [
    "ServerBuild",
    "ServerMCVersion",
    "ServerDownloader",
]


class ServerBuild(object):
    def __init__(self, mc_version: str, build: str, download_url: str = None, downloaded_path: Path = None,
                 *, java_major_version: int = None, updated_datetime: datetime.datetime = None, recommended=False):
        self.mc_version = mc_version
        self.build = build
        self.download_url = download_url
        self.downloaded_path = downloaded_path
        self.java_major_version = java_major_version
        self.updated_datetime = updated_datetime
        self.recommended = recommended
        #
        self._loaded = False

    # noinspection PyMethodMayBeStatic
    def is_require_build(self):
        """
        ビルドが必要ならTrue
        """
        return False

    # noinspection PyMethodMayBeStatic
    def is_loaded_info(self):
        """
        全ての情報を読み込んでいるならTrue
        """
        return True

    async def fetch_info(self) -> bool:
        if not self._loaded:
            self._loaded = await self._fetch_info()
        return self._loaded

    async def _fetch_info(self) -> bool:
        return False


SB = TypeVar("SB", bound=ServerBuild)


class ServerMCVersion(Generic[SB]):
    def __init__(self, mc_version: str, builds: "list[SF] | None"):
        self.mc_version = mc_version
        self.builds = builds

    def clear_cache(self):
        self.builds = None

    async def _list_builds(self) -> list[SB]:
        raise NotImplementedError

    async def list_builds(self) -> list[SB]:
        if self.builds is None:
            self.builds = (await self._list_builds()) or []
        return self.builds


SV = TypeVar("SV", bound=ServerMCVersion)


class ServerDownloader(Generic[SV]):
    def __init__(self):
        self.versions = None  # type: list[SV] | None

    def clear_cache(self):
        self.versions = None

    async def _list_versions(self) -> list[SV]:
        raise NotImplementedError

    async def list_versions(self) -> list[SV]:
        if self.versions is None:
            self.versions = (await self._list_versions()) or []
        return self.versions
