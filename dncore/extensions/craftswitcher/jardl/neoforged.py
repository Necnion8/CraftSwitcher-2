import platform
import re
from logging import getLogger

import aiohttp

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, ServerBuilder, SV
from ..abc import ServerType
from ..config import ServerConfig

VERSIONS_URL = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
DOWNLOAD_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/"
log = getLogger(__name__)


class NeoForgeBuilder(ServerBuilder):
    @property
    def build_root_dir(self):
        return self.server.directory

    async def _call(self, params: ServerBuilder.Parameters):
        params.cwd = self.build_root_dir
        params.args = [
            self.server.get_java_executable(),
            "-jar",
            str(self.build.downloaded_path),
            "--install-server",
        ]

    def apply_server_jar(self, config: "ServerConfig") -> bool:
        config.type = self.server_type
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


def get_mcversion(loader_version: str):
    b, c, *_ = loader_version.split(".", 2)
    mc_ver = f"1.{b}.{c}"
    if mc_ver.endswith(".0"):
        mc_ver = mc_ver[:-2]
    return mc_ver


class NeoForgeBuild(ServerBuild):
    def is_require_build(self):
        return True

    async def setup_builder(self, server, downloaded_path) -> NeoForgeBuilder:
        return NeoForgeBuilder(ServerType.NEO_FORGE, self, server)


class NeoForgeServerDownloader(ServerDownloader):
    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", VERSIONS_URL) as res:
            res.raise_for_status()
            versions = (await res.json())["versions"]  # type: list[str]

        _versions = {}  # type: dict[str, SV]
        for version in versions:
            mc_ver = get_mcversion(version)
            try:
                _ver = _versions[mc_ver]
            except KeyError:
                _ver = _versions[mc_ver] = ServerMCVersion(mc_ver, [])

            dl_url = DOWNLOAD_URL.format(version=version) + f"neoforge-{version}-installer.jar"
            _ver.builds.append(NeoForgeBuild(mc_ver, version, dl_url, work_dir=".neoforge-installer"))

        return list(_versions.values())
