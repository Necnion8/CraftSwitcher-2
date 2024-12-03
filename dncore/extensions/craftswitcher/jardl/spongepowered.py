from logging import getLogger

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SB, SV

__all__ = [
    "ProjectInfo",
    "ProjectVersionInfo",
    "ProjectVersionsPartInfo",
    "ProjectBuildInfo",
    "ProjectBuild",
    "ProjectVersion",
    "SpongeVanillaDownloader",
]
log = getLogger(__name__)


class ProjectInfo(BaseModel):
    class Tags(BaseModel):
        # api: list[str]
        minecraft: list[str]
        # forge: list[str]
        # neo: list[str]

    class Tag(BaseModel):
        # api: str
        minecraft: str

    displayName: str
    tags: Tags


class ProjectVersionInfo(BaseModel):
    tagValues: ProjectInfo.Tag
    recommended: bool


class ProjectVersionsPartInfo(BaseModel):
    artifacts: dict[str, ProjectVersionInfo]
    offset: int
    limit: int
    size: int


class ProjectBuildInfo(BaseModel):
    class Asset(BaseModel):
        classifier: str
        downloadUrl: str
        extension: str

    assets: list[Asset]


#


class ProjectBuild(ServerBuild):
    def __init__(self, version_info: "ProjectVersion", build_name: str, build_info: "ProjectVersionInfo"):
        super().__init__(
            mc_version=version_info.mc_version,
            build=build_name,
            recommended=build_info.recommended or False,
        )
        self.version_info = version_info
        self._info = None  # type: ProjectBuildInfo | None

    def is_loaded_info(self):
        return bool(self._info)

    async def _fetch_info(self):
        url = self.version_info.version_api_base + f"/{self.build}"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            self._info = ProjectBuildInfo.model_validate(await res.json())

            self.download_url = None
            for asset in self._info.assets:
                if asset.classifier == "universal":
                    self.download_url = asset.downloadUrl
                    break
            else:
                log.warning("universal asset not found: in %s", self.build)

            return True


# https://dl-api.spongepowered.org/v2/groups/org.spongepowered/artifacts/spongevanilla/versions?tags=minecraft:1.20.6&limit=26
class ProjectVersion(ServerMCVersion[ProjectBuild]):
    def __init__(self, artifact: "SpongeVanillaDownloader", mc_version: str):
        super().__init__(mc_version, None)
        self.artifact_info = artifact
        self.project_id = artifact.project_id

    @property
    def version_api_base(self):
        return self.artifact_info.project_api_base + "/versions"

    async def _list_builds(self) -> list[SB]:
        items = []
        offset = 0
        limit = 25
        total = None

        for n in range(2):  # latest 2
            url = self.version_api_base + "?" + ("&".join((
                f"tags=minecraft:{self.mc_version}",
                f"limit={limit}",
                f"offset={offset}",
            )))
            log.debug("fetching builds (%s/%s)", offset, total or "?")
            async with aiohttp.request("GET", url) as res:
                res.raise_for_status()
                info = ProjectVersionsPartInfo.model_validate(await res.json())

                items.extend(
                    ProjectBuild(self, b_name, b_info)
                    for b_name, b_info in info.artifacts.items()
                )

                total = info.size
                if total <= offset:
                    break
                offset += limit

        log.debug("fetched %s builds", len(items))
        items.reverse()
        return items


class SpongeVanillaDownloader(ServerDownloader[ProjectVersion]):
    api_base = "https://dl-api.spongepowered.org/v2/groups/org.spongepowered"
    project_id = "spongevanilla"

    @property
    def project_api_base(self):
        return f"{self.api_base}/artifacts/{self.project_id}"

    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", self.project_api_base) as res:
            res.raise_for_status()
            info = ProjectInfo.model_validate(await res.json())
            return [
                ProjectVersion(self, ver)
                for ver in reversed(info.tags.minecraft)
                if "-" not in ver
            ]  # exclude x.x-rc or x.x-pre
