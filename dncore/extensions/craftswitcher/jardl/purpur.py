import datetime

import aiohttp
from pydantic import BaseModel, field_serializer, field_validator

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SB, SV


class ProjectInfo(BaseModel):
    project: str
    versions: list[str]


class ProjectBuildInfo(BaseModel):
    project: str
    version: str
    build: int
    timestamp: datetime.datetime
    md5: str

    @field_serializer("timestamp")
    def serialize_timestamp(self, timestamp: datetime.datetime) -> int:
        return int(timestamp.timestamp() * 1000)

    @field_validator("timestamp")
    def validate_timestamp(self, value: int):
        return datetime.datetime.fromtimestamp(value / 1000)


class BuildListInfo(BaseModel):
    latest: str
    all: list[str]


class ProjectBuildsInfo(BaseModel):
    project: str
    version: str
    builds: BuildListInfo


#


class ProjectBuild(ServerBuild):
    def __init__(self, builds: "ProjectBuildsInfo", build: str):
        dl_url = f"https://api.purpurmc.org/v2/{builds.project}/{builds.version}/{self.build}/download"
        super().__init__(builds.version, build, download_url=dl_url)
        self.builds = builds

    def is_loaded_info(self):
        return self._loaded

    async def _fetch_info(self):
        url = f"https://api.purpurmc.org/v2/{self.builds.project}/{self.builds.version}/{self.build}"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            info = ProjectBuildInfo.model_validate_json(await res.json())
            self.updated_datetime = info.timestamp
            return True


class ProjectVersion(ServerMCVersion[ProjectBuild]):
    def __init__(self, project_id: str, mc_version: str):
        super().__init__(mc_version, None)
        self.project_id = project_id

    async def _list_builds(self) -> list[SB]:
        url = f"https://api.purpurmc.org/v2/{self.project_id}/{self.mc_version}"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            info = ProjectBuildsInfo.model_validate_json(await res.json())
            return [ProjectBuild(info, build) for build in info.builds.all]


class PurpurServerDownloader(ServerDownloader[ProjectVersion]):
    project_id = "purpur"

    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", f"https://api.purpurmc.org/v2/{self.project_id}") as res:
            res.raise_for_status()
            info = ProjectInfo.model_validate_json(await res.json())
            return [ProjectVersion(self.project_id, ver) for ver in info.versions]
