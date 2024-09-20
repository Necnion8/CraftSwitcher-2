import platform
import re
from logging import getLogger

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, ServerBuilder, SV, SB
from ..abc import ServerType
from ..config import ServerConfig

__all__ = [
    "VersionMetaInfo",
    "ForgeBuild",
    "ForgeServerDownloader",
]


log = getLogger(__name__)

INDEX_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/maven-metadata.json"
PROMO_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FILES_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/{version}/meta.json"
DOWNLOAD_URL = "https://maven.minecraftforge.net/net/minecraftforge/forge/{version}/{filename}"


# MEMO: 1.12.2-14.23.5.2851 から --installServer [File] が使える。(常にカレントではなく)
# MEMO: 1.17 から run.sh, .bat が生成されるようになった


class ForgeBuilder(ServerBuilder):
    _mc_version_int: tuple[int]

    @property
    def mc_version_int(self):
        try:
            return self._mc_version_int
        except AttributeError:
            m = re.search(r"^(?P<a>\d+)\.(?P<b>\d+)(\.(?P<c>\d+))?", self.build.mc_version)
            if m:
                self._mc_version_int = ver = tuple(int(v) for v in m.groupdict().values() if v is not None)
                return ver
        raise ValueError("No matches for x.x.x version pattern: '%s'", self.build.mc_version)

    def compare_version_or_higher(self, a: int, b: int, c: int = None):
        try:
            ver = self.mc_version_int
        except ValueError:
            return True  # defaults
        return ((a, b) if c is None else (a, b, c)) <= ver

    @property
    def build_root_dir(self):
        return self.server.directory

    async def _call(self, params: ServerBuilder.Parameters):
        params.cwd = self.build_root_dir
        params.args = [
            self.server.config.launch_option.java_executable,
            "-jar",
            str(self.build.downloaded_path),
            "--installServer",
        ]

    def apply_server_jar(self, config: "ServerConfig") -> bool:
        config.type = self.server_type
        if self.compare_version_or_higher(1, 17):
            config.enable_launch_command = True

            try:
                win_bat_filename = self.generate_fixed_run_bat().name
            except Exception as e:
                log.warning(f"Failed to generate fixed run.bat: {e}")
                win_bat_filename = "run.bat"

            if platform.system() == "Windows":  # TODO: ビルド環境に依存するのではなく、鯖を起動する環境に依存するべき
                config.launch_command = f"cmd.exe /C {win_bat_filename} $SERVER_ARGS"
            else:
                config.launch_command = "bash run.sh $SERVER_ARGS"

            config.save()
            return True

        # old version
        mc_ver = self.mc_version_int  # no raise
        build_ver = self.build.build

        if mc_ver < (1, 7):  # 1.5 ~ 1.6
            filename = f"minecraftforge-{build_ver}.jar"
        elif mc_ver < (1, 12):  # 1.7 ~ 1.11
            filename = f"forge-{build_ver}-universal.jar"
        else:  # 1.12 ~ 1.16
            filename = f"forge-{build_ver}.jar"

        if not (self.server.directory / filename).is_file():
            log.warning("Expected file name does not exist: %s", filename)

        self.jar_filename = filename
        return super().apply_server_jar(config)

    def generate_fixed_run_bat(self):
        """
        run.bat をもとに PAUSE コマンドを除外したバッチを生成する
        """
        bat_file = self.build_root_dir / "run.bat"
        fix_bat_file = self.build_root_dir / "run_nopause.bat"

        content = ""
        with bat_file.open("r") as f:
            for line in f:
                content += re.sub("^( *)(pause.*)$", r"\1rem \2", line, re.IGNORECASE)
        with fix_bat_file.open("w") as f:
            f.write(content)
        return fix_bat_file


#


class VersionMetaInfo(BaseModel):
    classifiers: dict[str, dict]


class ForgeBuild(ServerBuild):
    def is_require_build(self):
        return True

    def is_loaded_info(self):
        return self._loaded

    async def _fetch_info(self) -> bool:
        async with aiohttp.request("GET", FILES_URL.format(version=self.build)) as res:
            res.raise_for_status()
            info = VersionMetaInfo.model_validate(await res.json())

        try:
            info.classifiers["installer"]["jar"]
        except KeyError:
            pass
        else:
            filename = f"forge-{self.build}-installer.jar"
            self.download_url = DOWNLOAD_URL.format(version=self.build, filename=filename)
        return True

    async def setup_builder(self, server, downloaded_path) -> ForgeBuilder:
        return ForgeBuilder(ServerType.FORGE, self, server)


class ForgeServerDownloader(ServerDownloader):
    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", INDEX_URL) as res:
            res.raise_for_status()
            vers = await res.json()  # type: dict
        if type(vers) != dict:
            raise ValueError("no dict data received")

        try:
            async with aiohttp.request("GET", PROMO_URL) as res:
                res.raise_for_status()
                promos = await res.json()
            if type(promos) != dict:
                raise ValueError("no dict data received")
            promos = promos["promos"]
            if type(promos) != dict:
                raise ValueError("no dict data received")
        except Exception as e:
            log.warning(f"Exception in fetch promos: {e}")
            promos = {}

        versions = []  # type: list[SV]
        for ver, forge_versions in vers.items():
            recommended_forge_version = promos.get(f"{ver}-recommended") or None
            builds = []  # type: list[SB]
            for forge_version in forge_versions:
                recommended = forge_version == f"{ver}-{recommended_forge_version}"
                b = ForgeBuild(ver, forge_version, recommended=recommended, work_dir=".forge-installer")
                builds.append(b)

            v = ServerMCVersion(ver, builds)
            versions.append(v)

        return versions
