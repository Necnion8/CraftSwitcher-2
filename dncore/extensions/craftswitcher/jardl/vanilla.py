import datetime

import aiohttp
from pydantic import BaseModel

from .jardl import ServerMCVersion, ServerBuild, ServerDownloader


class Version(BaseModel):
    id: str
    type: str
    url: str
    time: datetime.datetime


class VersionManifest(BaseModel):
    versions: list[Version]


class JavaVersion(BaseModel):
    component: str
    majorVersion: int


class DownloadEntry(BaseModel):
    sha1: str
    size: int
    url: str


class VersionDownloads(BaseModel):
    server: DownloadEntry | None = None


class VersionInfo(BaseModel):
    id: str
    type: str
    downloads: VersionDownloads | None = None
    javaVersion: JavaVersion


class VanillaVersion(ServerMCVersion):
    def __init__(self, mc_version: str, version: "Version"):
        super().__init__(mc_version, None)
        self.info = version

    async def _list_builds(self) -> "list[ServerBuild]":
        async with aiohttp.request("GET", self.info.url) as res:
            res.raise_for_status()
            info = VersionInfo.model_validate_json(await res.json())
            updated = self.info.time
            dl_server = info.downloads.server
            if dl_server:
                java_ver = info.javaVersion and info.javaVersion.majorVersion or None
                return [ServerBuild(
                    info.id, "latest", dl_server.url,
                    java_major_version=java_ver, updated_datetime=updated)]
        return []


class VanillaServerDownloader(ServerDownloader[VanillaVersion]):
    async def _list_versions(self) -> list[VanillaVersion]:
        async with aiohttp.request("GET", "https://launchermeta.mojang.com/mc/game/version_manifest.json") as res:
            res.raise_for_status()
            info = VersionManifest.model_validate_json(await res.json())
            return [VanillaVersion(ver.id, ver) for ver in info.versions]
