from logging import getLogger

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SV, SB

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
            info = VersionMetaInfo.model_validate_json(await res.json())

        try:
            info["installer"]["jar"]
        except KeyError:
            pass

        filename = f"forge-{self.build}-installer.jar"
        self.download_url = DOWNLOAD_URL.format(version=self.build, filename=filename)
        return True


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
                b = ForgeBuild(ver, forge_version, recommended=recommended)
                builds.append(b)

            v = ServerMCVersion(ver, builds)
            versions.append(v)

        return versions
