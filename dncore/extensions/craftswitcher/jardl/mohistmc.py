import datetime

import aiohttp
from pydantic import BaseModel, field_validator, field_serializer

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SV, SB

__all__ = [
    "BuildInfo",
    "VersionBuildsInfo",
    "ProjectVersionsInfo",
    "VersionBuild",
    "ProjectVersion",
    "MohistServerDownloader",
    "BannerServerDownloader",
    "YouerServerDownloader",
]


class BuildInfo(BaseModel):
    number: int
    forgeVersion: str
    fileMd5: str
    createdAt: datetime.datetime

    @field_serializer("createdAt")
    def serialize_timestamp(self, timestamp: datetime.datetime) -> int:
        return int(timestamp.timestamp() * 1000)

    @classmethod
    @field_validator("createdAt")
    def validate_timestamp(cls, value: int):
        return datetime.datetime.fromtimestamp(value / 1000)


class VersionBuildsInfo(BaseModel):
    projectName: str
    projectVersion: str
    builds: list[BuildInfo]


class ProjectVersionsInfo(BaseModel):
    versions: list[str]


#


class VersionBuild(ServerBuild):
    def __init__(self, mc_version: str, project_id: str, info: BuildInfo):
        dl_url = f"https://mohistmc.com/api/v2/projects/{project_id}/{mc_version}/builds/{info.number}/download"
        super().__init__(mc_version, str(info.number), dl_url, updated_datetime=info.createdAt)
        self.project_id = project_id


class ProjectVersion(ServerMCVersion):
    def __init__(self, mc_version: str, project_id: str):
        super().__init__(mc_version, None)
        self.project_id = project_id

    async def _list_builds(self) -> list[SB]:
        url = f"https://mohistmc.com/api/v2/projects/{self.project_id}/{self.mc_version}/builds"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            builds = VersionBuildsInfo.model_validate(await res.json())

        return [VersionBuild(builds.projectVersion, builds.projectName, build) for build in builds.builds]


class MohistServerDownloader(ServerDownloader[ProjectVersion]):
    project_id = "mohist"

    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", f"https://mohistmc.com/api/v2/projects/{self.project_id}") as res:
            res.raise_for_status()
            vers = ProjectVersionsInfo.model_validate(await res.json())

        return [ProjectVersion(ver, self.project_id) for ver in vers.versions]


class BannerServerDownloader(MohistServerDownloader):
    project_id = "banner"


class YouerServerDownloader(MohistServerDownloader):
    project_id = "youer"
