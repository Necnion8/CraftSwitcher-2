import aiohttp
from pydantic import BaseModel

from .jardl import ServerDownloader, ServerMCVersion, ServerBuild, SV
from ..utils import get_user_agent


class BuildInfo(BaseModel):
    number: int
    url: str


class JenkinsInfo(BaseModel):
    name: str
    displayName: str
    description: str | None
    url: str
    builds: list[BuildInfo]


class BungeeCordDownloader(ServerDownloader):
    async def _list_versions(self) -> list[SV]:
        url = "https://ci.md-5.net/job/BungeeCord/api/json"
        headers = {"User-Agent": get_user_agent(), }
        async with aiohttp.request("GET", url, headers=headers) as res:
            res.raise_for_status()
            info = JenkinsInfo.model_validate(await res.json())

        def get_url(b: BuildInfo):
            return f"https://ci.md-5.net/job/BungeeCord/{b.number}/artifact/bootstrap/target/BungeeCord.jar"

        return [ServerMCVersion("latest", [
            ServerBuild("latest", str(b.number), get_url(b))
            for b in reversed(info.builds)
        ])]
