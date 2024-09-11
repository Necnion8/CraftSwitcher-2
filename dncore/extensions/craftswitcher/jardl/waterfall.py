import datetime

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerFile


class WaterfallInfo(BaseModel):
    project_id: str
    project_name: str
    versions: list[str]


class BuildDownload(BaseModel):
    name: str
    sha256: str


class BuildDownloads(BaseModel):
    application: BuildDownload | None


class WaterfallBuildInfo(BaseModel):
    build: int
    time: datetime.datetime
    channel: str
    downloads: BuildDownloads


class WaterfallBuildsInfo(BaseModel):
    project_id: str
    project_name: str
    version: str
    builds: list[WaterfallBuildInfo]


#


class WaterfallBuild(ServerFile):
    def __init__(self, builds: "WaterfallBuildsInfo", info: WaterfallBuildInfo):
        dl_url = f"https://api.papermc.io/v2/projects/waterfall" \
                 f"/versions/{builds.version}" \
                 f"/builds/{info.build}" \
                 f"/downloads/{info.downloads.application.name}"
        super().__init__(builds.version, str(info.build), dl_url, updated_datetime=info.time, )


class WaterfallVersion(ServerMCVersion[WaterfallBuild]):
    def __init__(self, mc_version: str):
        super().__init__(mc_version, None)

    async def _list_builds(self) -> list[WaterfallBuild]:
        url = f"https://api.papermc.io/v2/projects/waterfall/versions/{self.mc_version}/builds"
        async with aiohttp.request("GET", url) as res:
            res.raise_for_status()
            info = WaterfallBuildsInfo.model_validate_json(await res.json())
            return [WaterfallBuild(info, build) for build in info.builds]


class WaterfallServerDownloader(ServerDownloader[WaterfallVersion]):
    async def _list_versions(self) -> list[WaterfallVersion]:
        async with aiohttp.request("GET", "https://api.papermc.io/v2/projects/waterfall") as res:
            res.raise_for_status()
            info = WaterfallInfo.model_validate_json(await res.json())
            return [WaterfallVersion(ver) for ver in info.versions]
