import datetime
from pathlib import Path
from typing import TypeVar, Generic, TYPE_CHECKING

__all__ = [
    "ServerBuild",
    "ServerMCVersion",
    "ServerDownloader",
    "defaults",
]

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess


class ServerBuild(object):
    def __init__(self, mc_version: str, build: str, download_url: str = None, download_filename: str = None,
                 downloaded_path: Path = None,
                 *, java_major_version: int = None, updated_datetime: datetime.datetime = None, recommended=False):
        self.mc_version = mc_version
        self.build = build
        self.download_url = download_url
        self.download_filename = download_filename
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

    async def setup_builder(self, server: "ServerProcess", downloaded_path: Path):
        pass


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


def defaults():
    from ..abc import ServerType

    from .bungeecord import BungeeCordDownloader
    from .fabricmc import FabricServerDownloader
    from .minecraftforge import ForgeServerDownloader
    from .mohistmc import MohistServerDownloader, YouerServerDownloader, BannerServerDownloader
    from .neoforged import NeoForgeServerDownloader
    from .papermc import (
        PaperServerDownloader,
        WaterfallServerDownloader,
        FoliaServerDownloader,
        VelocityServerDownloader,
    )
    from .purpurmc import PurpurServerDownloader
    from .spigotmc import SpigotServerDownloader
    from .vanilla import VanillaServerDownloader

    return {
        ServerType.BUNGEECORD: BungeeCordDownloader(),
        ServerType.FABRIC: FabricServerDownloader(),
        ServerType.FORGE: ForgeServerDownloader(),
        ServerType.MOHIST: MohistServerDownloader(),
        ServerType.YOUER: YouerServerDownloader(),
        ServerType.BANNER: BannerServerDownloader(),
        ServerType.NEO_FORGE: NeoForgeServerDownloader(),
        ServerType.FOLIA: FoliaServerDownloader(),
        ServerType.PAPER: PaperServerDownloader(),
        ServerType.WATERFALL: WaterfallServerDownloader(),
        ServerType.VELOCITY: VelocityServerDownloader(),
        ServerType.PURPUR: PurpurServerDownloader(),
        ServerType.SPIGOT: SpigotServerDownloader(),
        ServerType.VANILLA: VanillaServerDownloader(),
    }
