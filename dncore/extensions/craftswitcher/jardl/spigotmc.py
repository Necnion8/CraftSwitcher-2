import re
from logging import getLogger
from pathlib import Path

import aiohttp

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, ServerBuilder, SV
from ..abc import ServerType
from ..utiljava import JavaPreset

__all__ = [
    "SpigotBuild",
    "SpigotServerDownloader",
]
VERSIONS_URL = "https://hub.spigotmc.org/versions/"
VERSION_PATTERN = re.compile(rb"<a href=\"(?P<v>\d+\.\d+(\.\d+)?)\.json\">")
BUILD_SAVED_PATTERN = re.compile(r"^\r?\n? *- Saved as (.*\.jar)\r?\n?$")
log = getLogger(__name__)


class SpigotBuilder(ServerBuilder):
    _saved_name: str | None

    async def _call(self, params: ServerBuilder.Parameters):
        self.jar_filename = None
        java_executable = (self.java_preset and self.java_preset.executable) or self.server.get_java_executable()
        params.cwd = self.build.downloaded_path.parent
        params.args = [
            java_executable,
            "-jar",
            str(self.build.downloaded_path.name),
            "--compile", "SPIGOT",
            "--rev", self.build.mc_version,
            # "--output-dir", str(self.server.directory),  # なぜか最後でエラーになるので
            "--output-dir", "..",
        ]

    async def _read(self, data: str):
        m = BUILD_SAVED_PATTERN.search(data)
        if m:
            self.jar_filename = Path(m.group(1)).name

    async def _exited(self, return_code: int):
        if return_code == 0 and not self.jar_filename:
            log.warning("Output jar file name not found in build log: bug?")
        return await super()._exited(return_code)


class SpigotBuild(ServerBuild):
    def is_require_build(self):
        return True

    async def setup_builder(self, server, downloaded_path, *, java_preset: JavaPreset | None) -> SpigotBuilder:
        return SpigotBuilder(ServerType.SPIGOT, self, server, java_preset)


class SpigotServerDownloader(ServerDownloader):
    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", VERSIONS_URL) as res:
            res.raise_for_status()
            content = await res.content.read()

        dl_url = "https://hub.spigotmc.org/jenkins/job/BuildTools/lastSuccessfulBuild/artifact/target/BuildTools.jar"
        _versions = []
        for match in VERSION_PATTERN.finditer(content):
            ver = match.group("v").decode("utf-8")
            version = ServerMCVersion(ver, [
                SpigotBuild(ver, "latest", download_url=dl_url, work_dir=".spigot-builder", require_jdk=True),
            ])
            _versions.append(version)

        _versions.sort(key=lambda v: [int(i) for i in re.findall(r"\d+", v.mc_version)])
        return _versions
