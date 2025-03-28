from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import HTTPException, WebSocket, APIRouter, Depends
from fastapi.exceptions import WebSocketException
from fastapi.requests import HTTPConnection

from dncore.extensions.craftswitcher.abc import ServerType
from dncore.extensions.craftswitcher.jardl import ServerMCVersion, ServerDownloader
from dncore.extensions.craftswitcher.publicapi import APIErrorCode

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import CraftSwitcher
    from dncore.extensions.craftswitcher.fileback import Backupper
    from dncore.extensions.craftswitcher.database import SwitcherDatabase
    from dncore.extensions.craftswitcher.files import FileManager
    from dncore.extensions.craftswitcher.serverprocess import ServerProcessList
    from dncore.extensions.craftswitcher.publicapi import APIHandler

__all__ = [
    "inst",
    "db",
    "backups",
    "servers",
    "files",
    "api_handler",
    "get_authorized_user",
    "get_authorized_user_ws",
    "getserver",
    "realpath",
    "getdownloader",
    "getversion",
    "getbuild",
]

inst: "CraftSwitcher"
db: "SwitcherDatabase"
backups: "Backupper"
servers: "ServerProcessList"
files: "FileManager"
api_handler: "APIHandler"


async def get_authorized_user(connection: HTTPConnection):
    try:
        token = connection.cookies["session"]
    except KeyError:
        pass
    else:
        user = await db.get_user_by_valid_token(token)
        if user:
            return user

    raise APIErrorCode.INVALID_AUTHENTICATION_CREDENTIALS.of("Invalid authentication credentials", 401)


async def get_authorized_user_ws(websocket: WebSocket):
    try:
        return await get_authorized_user(websocket)
    except HTTPException as e:
        raise WebSocketException(1008) from e


def getserver(server_id: str):
    try:
        server = servers[server_id.lower()]
    except KeyError:
        raise APIErrorCode.SERVER_NOT_FOUND.of("Server not found", 404)

    if server is None:
        raise APIErrorCode.SERVER_NOT_LOADED.of("Server config not loaded", 404)
    return server


def realpath(swi_path: str, root_dir: Path = None):
    try:
        return files.realpath(swi_path, root_dir=root_dir)
    except ValueError:
        raise APIErrorCode.NOT_ALLOWED_PATH.of(f"Unable to access: {swi_path}")


def getdownloader(server_type: ServerType):
    try:
        return inst.server_downloaders[server_type][-1]
    except (KeyError, IndexError):
        raise APIErrorCode.NO_AVAILABLE_SERVER_TYPE.of("Not available downloader", 404)


async def getversion(version: str, downloader: ServerDownloader = Depends(getdownloader)):
    for ver in await downloader.list_versions():
        if ver.mc_version == version:
            return ver
    raise APIErrorCode.NOT_EXISTS_SERVER_VERSION.of("No found version", 404)


async def getbuild(build: str, version: ServerMCVersion = Depends(getversion)):
    for b in await version.list_builds():
        if b.build == build:
            return b
    raise APIErrorCode.NOT_EXISTS_SERVER_BUILD.of("No found build", 404)


#

def create_api_handlers(
    _handler: "APIHandler",
    _inst: "CraftSwitcher",
    _db: "SwitcherDatabase",
    _backups: "Backupper",
    _servers: "ServerProcessList",
    _files: "FileManager",
):
    global inst, db, backups, servers, files, api_handler
    inst = _inst
    db = _db
    backups = _backups
    servers = _servers
    files = _files
    api_handler = _handler

    from . import _app, _user, _server, _file, _backup, _jardl, _plugins, _debug

    api = APIRouter(prefix="/api")
    api.include_router(_app.no_auth_api)
    api.include_router(_app.api)
    api.include_router(_user.no_auth_api)
    api.include_router(_user.api)
    api.include_router(_server.api)
    api.include_router(_file.api)
    api.include_router(_backup.api)
    api.include_router(_jardl.api)
    api.include_router(_plugins.api)
    api.include_router(_debug.api)
    return api
