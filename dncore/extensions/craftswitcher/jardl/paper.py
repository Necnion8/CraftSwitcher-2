import datetime

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SB, SV


class ProjectInfo(BaseModel):
    project_id: str
    project_name: str
    versions: list[str]


class BuildDownload(BaseModel):
    name: str
    sha256: str


class BuildDownloads(BaseModel):
    application: BuildDownload | None


class ProjectBuildInfo(BaseModel):
    build: int
    time: datetime.datetime
    channel: str
    downloads: BuildDownloads


class ProjectBuildsInfo(BaseModel):
    project_id: str
    project_name: str
    version: str
    builds: list[ProjectBuildInfo]


#


class ProjectBuild(ServerBuild):
    def __init__(self, builds: "ProjectBuildsInfo", info: ProjectBuildInfo):
        dl_url = f"https://api.papermc.io/v2/projects/{builds.project_id}" \
                 f"/versions/{builds.version}" \
                 f"/builds/{info.build}" \
                 f"/downloads/{info.downloads.application.name}"
        super().__init__(builds.version, str(info.build), dl_url, updated_datetime=info.time, )


class ProjectVersion(ServerMCVersion[ProjectBuild]):
    def __init__(self, project_id: str, mc_version: str):
        super().__init__(mc_version, None)
        self.project_id = project_id

    async def _list_builds(self) -> list[SB]:
        url = f"https://api.papermc.io/v2/projects/{self.project_id}/versions/{self.mc_version}/builds"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            info = ProjectBuildsInfo.model_validate_json(await res.json())
            return [ProjectBuild(info, build) for build in info.builds]


class PaperServerDownloader(ServerDownloader[ProjectVersion]):
    project_id = "paper"

    async def _list_versions(self) -> list[SV]:
        async with aiohttp.request("GET", f"https://api.papermc.io/v2/projects/{self.project_id}") as res:
            res.raise_for_status()
            info = ProjectInfo.model_validate_json(await res.json())
            return [ProjectVersion(self.project_id, ver) for ver in info.versions]
