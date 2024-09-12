import aiohttp

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SV

VERSIONS_URL = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
DOWNLOAD_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/"


class NeoForgeBuild(ServerBuild):
    def is_require_build(self):
        return True


class NeoForgeServerDownloader(ServerDownloader):
    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", VERSIONS_URL) as res:
            res.raise_for_status()
            versions = (await res.json())["versions"]  # type: list[str]

        _versions = {}  # type: dict[str, SV]
        for version in versions:
            a, b, *_ = version.split(".", 2)
            mc_ver = f"1.{a}.{b}"
            if mc_ver.endswith(".0"):
                mc_ver = mc_ver[:-2]

            try:
                _ver = _versions[mc_ver]
            except KeyError:
                _ver = _versions[mc_ver] = ServerMCVersion(mc_ver, [])

            dl_url = DOWNLOAD_URL.format(version=reversed) + f"neoforge-{version}-installer.jar"
            _ver.builds.append(NeoForgeBuild(mc_ver, version, dl_url))

        return list(_versions.values())
