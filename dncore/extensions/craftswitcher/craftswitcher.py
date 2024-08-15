import asyncio
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from dncore.event import EventListener, onevent
from .abc import ServerState
from .config import SwitcherConfig, ServerConfig
from .event import ServerChangeStateEvent
from .serverprocess import ServerProcessList, ServerProcess
from .publicapi import UvicornServer, APIHandler

if TYPE_CHECKING:
    from dncore.plugin import PluginInfo

log = getLogger(__name__)
__version__ = "2.0.0"


class CraftSwitcher(EventListener):
    _inst: "CraftSwitcher"
    SERVER_CONFIG_FILE_NAME = "swi.server.yml"

    def __init__(self, loop: asyncio.AbstractEventLoop, config_file: Path, *, plugin_info: "PluginInfo" = None):
        self.loop = loop
        self.config = SwitcherConfig(config_file)
        self.servers = ServerProcessList()
        # api
        api = FastAPI(
            title="CraftSwitcher",
            version=str(plugin_info.version.numbers) if plugin_info else __version__,
        )

        @api.on_event("startup")
        async def _startup():
            for log_name in ("uvicorn", "uvicorn.access"):
                _log = getLogger(log_name)
                _log.handlers.clear()
                for handler in getLogger("dncore").handlers:
                    _log.addHandler(handler)

        self.api_server = UvicornServer()
        self.api_handler = APIHandler(self, api)
        #
        self._initialized = False

    def load_config(self):
        log.debug("Loading config")
        self.config.load()

    def load_servers(self):
        if self.servers:
            raise RuntimeError("server list is not empty")

        log.debug("Loading servers")
        for server_id, server_dir in self.config.servers.items():
            server_id = server_id.lower()
            if server_id in self.servers:
                log.warning("Already exists server id!: %s", server_id)
                continue

            server_dir = Path(server_dir)

            server = None  # type: ServerProcess | None
            server_config_path = server_dir / self.SERVER_CONFIG_FILE_NAME
            config = ServerConfig(server_config_path)

            if server_config_path.is_file():
                try:
                    config.load()
                except Exception as e:
                    log.error("Error in load server config: %s: %s", server_id, str(e))

                else:
                    server = ServerProcess(
                        self.loop,
                        directory=server_dir,
                        server_id=server_id,
                        config=config,
                        global_config=self.config.server_defaults,
                    )
            else:
                log.warning("Not exists server config: %s", server_dir)

            self.servers[server_id] = server

        log.info("Loaded %s server", len(self.servers))

    async def shutdown_all_servers(self):
        async def _shutdown(s: ServerProcess):
            if s.state.is_running:
                try:
                    await s.stop()
                except Exception as e:
                    log.exception("Exception in server shutdown (ignored)", exc_info=e)
                try:
                    await s.wait_for_shutdown()
                except asyncio.TimeoutError:
                    log.warning("Shutdown expired: %s", s.id)
                    # await s.kill()

        if self.servers:
            log.info("Shutdown server all!")
            await asyncio.wait([_shutdown(s) for s in self.servers.values()])

    def unload_servers(self):
        if not self.servers:
            return

        if any(s.state.is_running for s in self.servers.values()):
            raise ValueError("Contains not stopped server")

        self.servers.clear()

    # public api

    async def start_api_server(self):
        config = self.config.api_server
        try:
            await self.api_server.start(
                self.api_handler.router,
                host=config.bind_host,
                port=config.bind_port,
            )
        except RuntimeError as e:
            log.warning(f"Failed to start api server: {e}")

    async def close_api_server(self):
        await self.api_server.shutdown()

    #

    async def init(self):
        if self._initialized:
            raise RuntimeError("Already initialized")

        log.info("Initializing CraftSwitcher")
        self._initialized = True
        CraftSwitcher._inst = self

        self.load_config()
        self.load_servers()
        await self.start_api_server()

    async def shutdown(self):
        if not self._initialized:
            return
        log.info("Shutdown CraftSwitcher")
        try:
            del CraftSwitcher._inst
        except AttributeError:
            pass
        self._initialized = False

        try:
            await self.shutdown_all_servers()
            await self.close_api_server()

        finally:
            self.unload_servers()

    # events

    @onevent(monitor=True)
    async def on_change_state(self, event: ServerChangeStateEvent):
        server = event.server

        # restart flag
        if server.shutdown_to_restart and server.state is ServerState.STOPPED:
            delay = 1
            log.info("Restart %s server after %s seconds", server.id, delay)
            await asyncio.sleep(delay)
            server.shutdown_to_restart = False
            await server.start()


def getinst() -> "CraftSwitcher":
    try:
        return CraftSwitcher._inst
    except AttributeError:
        raise RuntimeError("CraftSwitcher is not instanced")
