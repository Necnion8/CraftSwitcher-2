from logging import getLogger
from typing import Literal

from fastapi import Depends, APIRouter

from .common import *

log = getLogger(__name__)
api = APIRouter(
    prefix="/debug",
    tags=["Debug", ],
    dependencies=[Depends(get_authorized_user), ],
)


@api.get("/reload")
async def _reload():
    from dncore import DNCoreAPI

    async def _async():
        try:
            await DNCoreAPI.plugins().reload_plugin(DNCoreAPI.get_plugin_info("CraftSwitcher"))
        except Exception as e:
            log.warning("Failed to reload by debug", exc_info=e)

    inst.loop.create_task(_async())
    return True


@api.get("/test")
async def _test(arg: Literal["1", "2", "3", "4", "5", "6", "7", "8", "9"] = "1"):
    return await inst._test(arg)
