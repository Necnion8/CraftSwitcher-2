import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SV, SB

__all__ = [
    "InstallerInfo",
    "LoaderInfo",
    "VersionInfo",
    "ServerVersion",
    "FabricServerDownloader",
]


class InstallerInfo(BaseModel):
    version: str
    stable: bool


class LoaderInfo(BaseModel):
    build: int
    stable: bool
    version: str


class VersionInfo(BaseModel):
    version: str
    stable: bool


class ServerVersion(ServerMCVersion):
    def __init__(self, info: VersionInfo, downloader: "FabricServerDownloader"):
        super().__init__(info.version, None)
        self.info = info
        self.downloader = downloader

    async def _list_builds(self) -> list[SB]:
        loaders = await self.downloader._list_loaders()
        installers = await self.downloader._list_installers()

        if not installers:
            return []

        installer = installers[-1]
        builds = []

        for loader in loaders:
            if not loader.stable:
                continue

            dl_url = f"https://meta.fabricmc.net/v2/versions/loader" \
                     f"/{self.mc_version}/{loader.version}/{installer.version}" \
                     f"/server/jar"

            builds.append(ServerBuild(
                self.mc_version,
                f"loader.{loader.version}-installer.{installer.version}",
                download_url=dl_url,
            ))
        return builds


class FabricServerDownloader(ServerDownloader):
    def __init__(self):
        super().__init__()
        self._loaders = None  # type: list[LoaderInfo] | None
        self._installers = None  # type: list[InstallerInfo] | None

    def clear_cache(self):
        super().clear_cache()
        self._loaders = None
        self._installers = None

    async def _list_versions(self) -> list[SV]:
        url = "https://meta.fabricmc.net/v2/versions/game"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            info = await res.json()

        versions = []
        for entry in reversed(info):
            info = VersionInfo.model_validate(entry)
            if info.stable:
                versions.append(ServerVersion(info, self))
        return versions

    async def _list_loaders(self) -> list[LoaderInfo]:
        if self._loaders is None:
            url = "https://meta.fabricmc.net/v2/versions/loader"
            async with aiohttp.request("GET", url) as res:
                res.raise_for_status()
                info = await res.json()

            self._loaders = []
            for entry in reversed(info):
                info = LoaderInfo.model_validate(entry)
                if info.stable:
                    self._loaders.append(info)
        return self._loaders

    async def _list_installers(self) -> list[InstallerInfo]:
        if self._installers is None:
            url = "https://meta.fabricmc.net/v2/versions/installer"
            async with aiohttp.request("GET", url) as res:
                res.raise_for_status()
                info = await res.json()

            self._installers = []
            for entry in reversed(info):
                info = InstallerInfo.model_validate(entry)
                if info.stable:
                    self._installers.append(info)
        return self._installers
