import datetime

import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SB, SV
from ..utils import get_user_agent

__all__ = [
    "ProjectInfo",
    "BuildDownload",
    "ProjectBuildInfo",
    "ProjectBuild",
    "ProjectVersion",
    "PaperServerDownloader",
    "WaterfallServerDownloader",
    "VelocityServerDownloader",
    "FoliaServerDownloader",
]


class ProjectInfo(BaseModel):
    class _Project(BaseModel):
        id: str
        name: str

    project: _Project
    versions: dict[str, list[str]]


class BuildDownload(BaseModel):
    name: str
    sha256: str


class ProjectBuildInfo(BaseModel):
    class _Download(BaseModel):
        name: str
        checksums: dict[str, str]
        size: int
        url: str

    id: int
    time: datetime.datetime
    channel: str
    downloads: dict[str, _Download]


#


class ProjectBuild(ServerBuild):
    def __init__(self, mc_version: str, info: "ProjectBuildInfo"):
        download_url = info.downloads["server:default"].url
        filename = info.downloads["server:default"].name
        super().__init__(mc_version, str(info.id), download_url, filename, updated_datetime=info.time, )


class ProjectVersion(ServerMCVersion[ProjectBuild]):
    def __init__(self, project_id: str, mc_version: str):
        super().__init__(mc_version, None)
        self.project_id = project_id

    async def _list_builds(self) -> list[SB]:
        url = f"https://fill.papermc.io/v3/projects/{self.project_id}/versions/{self.mc_version}/builds"
        headers = {"User-Agent": get_user_agent(), }
        async with aiohttp.request("GET", url, headers=headers) as res:
            res.raise_for_status()
            builds = [ProjectBuildInfo.model_validate(b) for b in await res.json()]
            return [ProjectBuild(self.mc_version, build)
                    for build in builds if "server:default" in build.downloads]


class PaperServerDownloader(ServerDownloader[ProjectVersion]):
    project_id = "paper"

    async def _list_versions(self) -> list[SV]:
        url = f"https://fill.papermc.io/v3/projects/{self.project_id}"
        headers = {"User-Agent": get_user_agent(), }
        async with aiohttp.request("GET", url, headers=headers) as res:
            res.raise_for_status()
            info = ProjectInfo.model_validate(await res.json())
            return [ProjectVersion(self.project_id, ver) for vers in reversed(info.versions.values()) for ver in vers]


class WaterfallServerDownloader(PaperServerDownloader):
    project_id = "waterfall"


class VelocityServerDownloader(PaperServerDownloader):
    project_id = "velocity"


class FoliaServerDownloader(PaperServerDownloader):
    project_id = "folia"
