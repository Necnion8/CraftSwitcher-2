from logging import getLogger

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, ServerBuilder, SV
from ..abc import ServerType
from ..config import ServerConfig

__all__ = [
    "GameVersionEntry",
    "LoaderVersionEntry",
    "InstallerVersionEntry",
    "VersionsInfo",
    "ServerInstaller",
    "LoaderVersion",
    "GameVersion",
    "QuiltServerDownloader",
]
log = getLogger(__name__)


class GameVersionEntry(BaseModel):
    version: str
    stable: bool


class LoaderVersionEntry(BaseModel):
    build: int
    version: str


class InstallerVersionEntry(BaseModel):
    url: str
    version: str


class VersionsInfo(BaseModel):
    game: list[GameVersionEntry]
    loader: list[LoaderVersionEntry]
    installer: list[InstallerVersionEntry]

#


class ServerInstaller(ServerBuilder):
    async def _call(self, params: ServerBuilder.Parameters):
        params.cwd = self.work_dir
        params.args = [
            self.server.config.launch_option.java_executable,
            "-jar",
            str(self.build.downloaded_path),
            "install",
            "server", self.build.mc_version,
            "--download-server",
            f"--install-dir=\"{self.server.directory}\"",
        ]

    def apply_server_jar(self, config: "ServerConfig") -> bool:
        self.jar_filename = "quilt-server-launch.jar"
        return super().apply_server_jar(config)


class LoaderVersion(ServerBuild):
    def is_require_build(self):
        return True

    async def setup_builder(self, server, downloaded_path) -> ServerBuilder:
        return ServerInstaller(ServerType.QUILT, self, server)


class GameVersion(ServerMCVersion[LoaderVersion]):
    def __init__(self, versions_info: VersionsInfo, mc_version: str, installer_version: InstallerVersionEntry = None):
        builds = [
            LoaderVersion(
                mc_version, loader_v.version,
                installer_version and installer_version.url or None, work_dir=".quilt-installer",
            ) for loader_v in reversed(versions_info.loader)
        ]
        super().__init__(mc_version, builds)
        self.versions_info = versions_info


class QuiltServerDownloader(ServerDownloader[GameVersion]):
    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", "https://meta.quiltmc.org/v3/versions") as res:
            res.raise_for_status()
            info = VersionsInfo.model_validate(await res.json())

            latest_installer = None  # type: InstallerVersionEntry | None
            for installer_v in info.installer:
                if installer_v.version.split(".")[0] != "0":  # 0.x only
                    continue
                latest_installer = installer_v
                break

            if not latest_installer:
                log.warning("Not found installer 0.x")

            return [
                GameVersion(info, game_v.version, latest_installer)
                for game_v in reversed(info.game) if game_v.stable
            ]
