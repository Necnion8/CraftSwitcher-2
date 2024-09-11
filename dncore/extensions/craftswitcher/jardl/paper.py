import datetime

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerFile


class PaperInfo(BaseModel):
    project_id: str
    project_name: str
    versions: list[str]


class BuildDownload(BaseModel):
    name: str
    sha256: str


class BuildDownloads(BaseModel):
    application: BuildDownload | None


class PaperBuildInfo(BaseModel):
    build: int
    time: datetime.datetime
    channel: str
    downloads: BuildDownloads


class PaperBuildsInfo(BaseModel):
    project_id: str
    project_name: str
    version: str
    builds: list[PaperBuildInfo]


#


class PaperBuild(ServerFile):
    def __init__(self, builds: "PaperBuildsInfo", info: PaperBuildInfo):
        dl_url = f"https://api.papermc.io/v2/projects/paper" \
                 f"/versions/{builds.version}" \
                 f"/builds/{info.build}" \
                 f"/downloads/{info.downloads.application.name}"
        super().__init__(builds.version, str(info.build), dl_url, updated_datetime=info.time, )


class PaperVersion(ServerMCVersion[PaperBuild]):
    def __init__(self, mc_version: str):
        super().__init__(mc_version, None)

    async def _list_builds(self) -> list[PaperBuild]:
        url = f"https://api.papermc.io/v2/projects/paper/versions/{self.mc_version}/builds"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            info = PaperBuildsInfo.model_validate_json(await res.json())
            return [PaperBuild(info, build) for build in info.builds]


class PaperServerDownloader(ServerDownloader[PaperVersion]):
    async def _list_versions(self) -> list[PaperVersion]:
        async with aiohttp.request("GET", "https://api.papermc.io/v2/projects/paper") as res:
            res.raise_for_status()
            info = PaperInfo.model_validate_json(await res.json())
            return [PaperVersion(ver) for ver in info.versions]
