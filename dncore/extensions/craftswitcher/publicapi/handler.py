import asyncio
from logging import getLogger
from typing import TYPE_CHECKING, Iterable

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import JSONResponse

from dncore.extensions.craftswitcher.files import FileManager
from dncore.extensions.craftswitcher.publicapi import APIError, WebSocketClient
from dncore.extensions.craftswitcher.publicapi.event import *
from dncore.extensions.craftswitcher.publicapi.handlers import create_api_handlers
from dncore.extensions.craftswitcher.utils import call_event

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import CraftSwitcher
    from dncore.extensions.craftswitcher.serverprocess import ServerProcessList

log = getLogger(__name__)


class APIHandler(object):
    inst: "CraftSwitcher"
    servers: "ServerProcessList"
    files: "FileManager"

    def __init__(self, inst: "CraftSwitcher"):
        self.inst = inst
        self.servers = inst.servers
        self.files = inst.files
        self._websocket_clients = set()  # type: set[WebSocketClient]

    def set_handlers(self, api: FastAPI):
        api.include_router(create_api_handlers(
            self,
            self.inst,
            self.inst.database,
            self.inst.backups,
            self.inst.servers,
            self.inst.files,
        ))

        @api.exception_handler(HTTPException)
        def _on_api_error(_, exc: HTTPException):
            return JSONResponse(status_code=exc.status_code, content=dict(
                error=exc.detail,
                error_code=exc.code if isinstance(exc, APIError) else -1,
            ))

        @api.exception_handler(500)
        def _on_internal_exception_handler(_, __: Exception):
            return JSONResponse(status_code=500, content=dict(
                error="Internal Server Error",
                error_code=-1,
            ))

    # websocket

    @property
    def ws_clients(self):
        return self._websocket_clients

    async def broadcast_websocket(self, data, *, clients: Iterable[WebSocketClient] = None):
        tasks = [
            client.websocket.send_json(data)
            for client in (self.ws_clients if clients is None else clients)
        ]

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _ws_handler(self, websocket: WebSocket):
        await websocket.accept()

        client = WebSocketClient(websocket)
        log.debug("Connected WebSocket Client #%s", client.id)
        call_event(WebSocketClientConnectEvent(client))
        self._websocket_clients.add(client)

        try:
            async for data in websocket.iter_json():
                log.debug("WS#%s -> %s", client.id, data)

                try:
                    request_type = data["type"]
                except KeyError as e:
                    log.debug("WS#%s : No '%s' specified for data", client.id, e)
                    continue

                if request_type == "server_process_write":
                    try:
                        server_id = data["server"]
                        write_data = data["data"]
                    except KeyError as e:
                        log.debug("WS#%s : No '%s' specified for data", client.id, e)
                        continue

                    try:
                        server = self.servers[server_id]
                    except KeyError:
                        log.debug("WS#%s : Unknown server: %s", client.id, server_id)
                        continue
                    if server and server.state.is_running:
                        try:
                            server.wrapper.write(write_data)
                        except Exception as e:
                            server.log.warning(
                                "Exception in write to server process by WS#%s", client.id, exc_info=e)
                    else:
                        log.debug("WS#%s : Failed to write to process", client.id)

                elif request_type == "server_process_set_term_size":
                    try:
                        server_id = data["server"]
                        cols = int(data["cols"])
                        rows = int(data["rows"])
                    except KeyError as e:
                        log.debug("WS#%s : No '%s' specified for data", client.id, e)
                        continue
                    except ValueError as e:
                        log.debug("WS#%s : Not int '%s'", client.id, e)
                        continue

                    try:
                        server = self.servers[server_id]
                    except KeyError:
                        log.debug("WS#%s : Unknown server: %s", client.id, server_id)
                        continue
                    if server:
                        try:
                            server.set_term_size(cols, rows)
                        except Exception as e:
                            server.log.warning(
                                "Exception in set term size to server by WS#%s", client.id, exc_info=e)
                    else:
                        log.debug("WS#%s : Failed to set term size: Not loaded server", client.id)

                elif request_type == "add_watchdog_path":
                    try:
                        path = data["path"]
                    except KeyError as e:
                        log.debug("WS#%s : No '%s' specified for data", client.id, e)
                        continue

                    try:
                        realpath = self.files.realpath(path)
                    except ValueError:
                        log.debug("WS#%s : Not allowed path", client.id)
                        continue  # unsafe
                    client.watch_files[realpath] = self.inst.add_file_watch(realpath, client)

                elif request_type == "remove_watchdog_path":
                    try:
                        path = data["path"]
                    except KeyError as e:
                        log.debug("WS#%s : No '%s' specified for data", client.id, e)
                        continue

                    try:
                        realpath = self.files.realpath(path)
                    except ValueError:
                        log.debug("WS#%s : Not allowed path", client.id)
                        continue  # unsafe
                    try:
                        watch_info = client.watch_files.pop(realpath)
                    except KeyError:
                        log.debug("WS#%s : No watch path", client.id)
                        continue
                    self.inst.remove_file_watch(watch_info)

        finally:
            for watch in client.watch_files.values():
                self.inst.remove_file_watch(watch)
            client.watch_files.clear()

            self._websocket_clients.discard(client)
            call_event(WebSocketClientDisconnectEvent(client))
            log.debug("Disconnect WebSocket Client #%s", client.id)
