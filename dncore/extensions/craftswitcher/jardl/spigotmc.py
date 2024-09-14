import re

import aiohttp

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SV

__all__ = [
    "SpigotBuild",
    "SpigotServerDownloader",
]
VERSIONS_URL = "https://hub.spigotmc.org/versions/"
VERSION_PATTERN = re.compile(rb"<a href=\"(?P<v>\d+\.\d+(\.\d+)?)\.json\">")


class SpigotBuild(ServerBuild):
    def is_require_build(self):
        return True


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
                SpigotBuild(ver, "latest", download_url=dl_url),
            ])
            _versions.append(version)

        _versions.sort(key=lambda v: [int(i) for i in re.findall(r"\d+", v.mc_version)])
        return _versions
