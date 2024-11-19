import datetime
from enum import Enum
from pathlib import Path
from typing import TypeVar, Generic, TYPE_CHECKING

from dncore.extensions.craftswitcher.abc import ServerType
from dncore.extensions.craftswitcher.utils import getinst

__all__ = [
    "ServerBuildStatus",
    "ServerBuilder",
    "ServerBuild",
    "ServerMCVersion",
    "ServerDownloader",
    "defaults",
]

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess
    from dncore.extensions.craftswitcher.config import ServerConfig


class ServerBuildStatus(Enum):
    STANDBY = "standby"
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"

    def is_running(self):
        return self in (ServerBuildStatus.PENDING, )


# noinspection PyMethodMayBeStatic
class ServerBuilder(object):
    class Parameters(object):
        def __init__(self, cwd: Path, env: dict[str, str], ):
            self.cwd = cwd
            self.env = env
            self.args = []  # type: list[str]

    def __init__(self, server_type: ServerType, build: "ServerBuild",
                 server: "ServerProcess", java_preset: "JavaPreset | None"):
        self.server_type = server_type
        self.build = build
        self.server = server
        self.java_preset = java_preset
        self._state = ServerBuildStatus.STANDBY
        self.jar_filename = None  # type: str | None
        self.work_dir = server.directory / build.work_dir if build.work_dir else None

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state: ServerBuildStatus):
        self._state = new_state

    async def _call(self, params: Parameters):
        raise NotImplementedError

    async def _read(self, data: str):
        pass

    async def _error(self, exception: Exception):
        self.state = ServerBuildStatus.FAILED

    async def _exited(self, return_code: int) -> ServerBuildStatus:
        self.state = state = ServerBuildStatus.SUCCESS if return_code == 0 else ServerBuildStatus.FAILED
        return state

    async def _clean(self):
        if self.work_dir:
            await getinst().files.delete(self.work_dir, self.server)

    def apply_server_jar(self, config: "ServerConfig") -> bool:
        jar_filename = self.jar_filename
        if jar_filename:
            config.type = self.server_type
            config.enable_launch_command = False
            config.launch_option.jar_file = jar_filename
            config.save()
            return True
        return False


class ServerBuild(object):
    def __init__(self, mc_version: str, build: str, download_url: str = None, download_filename: str = None,
                 downloaded_path: Path = None,
                 *, java_major_version: int = None, updated_datetime: datetime.datetime = None, recommended=False,
                 work_dir: str = None, require_jdk: bool = None, ):
        self.mc_version = mc_version
        self.build = build
        self.download_url = download_url
        self.download_filename = download_filename
        self.downloaded_path = downloaded_path
        self.java_major_version = java_major_version
        self.require_jdk = require_jdk
        self.updated_datetime = updated_datetime
        self.recommended = recommended
        self.work_dir = work_dir
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

    async def setup_builder(self, server: "ServerProcess", downloaded_path: Path,
                            *, java_preset: "JavaPreset | None") -> ServerBuilder:
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
    from .quiltmc import QuiltServerDownloader
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
        ServerType.QUILT: QuiltServerDownloader(),
        ServerType.SPIGOT: SpigotServerDownloader(),
        ServerType.VANILLA: VanillaServerDownloader(),
    }
