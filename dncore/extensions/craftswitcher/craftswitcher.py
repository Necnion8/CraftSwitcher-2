import asyncio
import datetime
import os
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from dncore.event import EventListener, onevent
from .abc import ServerState
from .config import SwitcherConfig, ServerConfig
from .database import SwitcherDatabase
from .event import *
from .files import FileManager
from .files.event import *
from .publicapi import UvicornServer, APIHandler
from .publicapi.event import *
from .publicapi.model import FileInfo
from .serverprocess import ServerProcessList, ServerProcess
from .utils import call_event

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
        self.database = SwitcherDatabase(config_file.parent)
        self.servers = ServerProcessList()
        self.files = FileManager(self.loop, Path("./minecraft_servers"))
        # api
        global __version__
        __version__ = str(plugin_info.version.numbers) if plugin_info else __version__
        api = FastAPI(
            title="CraftSwitcher",
            version=__version__,
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

    def print_welcome(self):
        log.info("=" * 50)
        log.info("")
        log.info("  ##*  CraftSwitcher v" + __version__ + "  *##")
        log.info("")
        if self.config.api_server.enable:
            log.info("  - API Bind    : %s:%s", self.config.api_server.bind_host, self.config.api_server.bind_port)
        else:
            log.info("  - API Bind    : DISABLED")

        log.info("")
        log.info("  - Root Directory:")
        log.info("       %s", self.files.root_dir)

        log.info("")
        log.info("  - Server List : %s servers", len(self.servers))
        for server_id, server_ in self.servers.items():
            if server_:
                log.info("     - %s", server_id)
            else:
                log.warning("     - %s  (NOT LOADED)", server_id)

        log.info("")
        log.info("=" * 50)

    # property

    @property
    def servers_real_path(self):
        return self.files.realpath(self.config.servers_location, force=True)

    # api

    async def init(self):
        if self._initialized:
            raise RuntimeError("Already initialized")

        log.info("Initializing CraftSwitcher")
        self._initialized = True
        CraftSwitcher._inst = self

        self.load_config()
        self.load_servers()

        await self.database.connect()

        self.print_welcome()

        await self.start_api_server()

        call_event(SwitcherInitializedEvent())

    async def shutdown(self):
        if not self._initialized:
            return
        log.info("Shutdown CraftSwitcher")

        await call_event(SwitcherShutdownEvent())

        try:
            del CraftSwitcher._inst
        except AttributeError:
            pass
        self._initialized = False

        try:
            await self.shutdown_all_servers()
        except Exception as e:
            log.warning("Exception in shutdown servers", exc_info=e)

        try:
            await self.close_api_server()
        except Exception as e:
            log.warning("Exception in close api server", exc_info=e)

        try:
            await self.database.close()
        except Exception as e:
            log.warning("Exception in close database", exc_info=e)

        self.unload_servers()

    def load_config(self):
        log.debug("Loading config")
        self.config.load()
        self.files.root_dir = root_dir = Path(self.config.root_directory).resolve()

        if not root_dir.is_dir():
            if root_dir.parent.is_dir():  # 親フォルダがあるなら静かに作成する
                root_dir.mkdir()
                log.info("Created root directory: %s", root_dir)
            else:
                log.warning("Root directory does not exist! -> %s", root_dir)

        call_event(SwitcherConfigLoadedEvent())

    def load_servers(self):
        if self.servers:
            raise RuntimeError("server list is not empty")
        log.debug("Loading servers")
        for server_id, _server_dir in self.config.servers.items():
            server_id = server_id.lower()
            if server_id in self.servers:
                log.warning("Already exists server id!: %s", server_id)
                continue

            server = None  # type: ServerProcess | None
            try:
                server_dir = self.files.realpath(_server_dir)
            except ValueError:
                log.warning("Not allowed path: %s: %s", server_id, _server_dir)

            else:
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
        call_event(SwitcherServersLoadedEvent())

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
            await asyncio.wait([_shutdown(s) for s in self.servers.values() if s])

    def unload_servers(self):
        """
        サーバーリストを空にします

        :except ValueError: 起動しているサーバーがある場合
        """
        if not self.servers:
            return

        if any(s.state.is_running for s in self.servers.values() if s):
            raise ValueError("Contains not stopped server")

        call_event(SwitcherServersUnloadEvent())
        self.servers.clear()

    # util

    def create_file_info(self, realpath: Path):
        """
        指定されたパスの :class:`FileInfo` を返します
        """
        stats = realpath.stat()

        swipath = self.files.swipath(realpath, force=True)
        try:
            match_server_id = None
            for _server_id, _server_dir in self.config.servers.items():
                if _server_dir == swipath:
                    match_server_id = _server_id
                    break
        except KeyError:
            match_server_id = None

        is_server_dir = realpath.is_dir() and (realpath / self.SERVER_CONFIG_FILE_NAME).is_file()

        return FileInfo(
            name="" if swipath == "/" else realpath.name,
            path=self.files.swipath(realpath.parent, force=True),
            is_dir=realpath.is_dir(),
            size=stats.st_size if realpath.is_file() else -1,
            modify_time=int(stats.st_mtime),
            create_time=int(stats.st_ctime),
            is_server_dir=is_server_dir,
            registered_server_id=match_server_id,
        )

    def swipath_server(self, server: ServerProcess):
        """
        指定されたサーバーのSWIパスを返します

        システムパス外である場合は :class:`ValueError` を発生させます
        """
        return self.files.swipath(server.directory)

    # server api

    def create_server_config(self, server_directory: str | Path, jar_file=""):
        """
        指定されたサーバーディレクトリで :class:`ServerConfig` を作成します
        """
        config_path = Path(server_directory) / self.SERVER_CONFIG_FILE_NAME
        config = ServerConfig(config_path)
        config.launch_option.jar_file = jar_file
        return config

    def import_server_config(self, server_directory: str):
        """
        構成済みのサーバーディレクトリから :class:`ServerConfig` を読み込み、作成します。
        """
        config_path = Path(server_directory) / self.SERVER_CONFIG_FILE_NAME
        if not config_path.is_file():
            raise FileNotFoundError(str(config_path))
        config = ServerConfig(config_path)
        config.load(save_defaults=False)
        return config

    def create_server(self, server_id: str, directory: str | Path, config: ServerConfig, *, set_creation_date=True):
        """
        サーバーを作成し、CraftSwitcherに追加されます。

        この操作により、サーバーディレクトリにサーバー設定ファイルが保存されます。

        既に存在するIDの場合は :class:`ValueError` を。

        directoryが存在しない場合は :class:`NotADirectoryError` を発生させます。
        """
        server_id = server_id.lower()
        if server_id in self.servers:
            raise ValueError("Already exists server id")

        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(str(directory))
        server = ServerProcess(self.loop, directory, server_id, config, self.config.server_defaults)

        if set_creation_date:
            config.created_at = datetime.datetime.today()

        config.save(force=True)
        self.servers.append(server)
        self.config.servers[server_id] = self.files.swipath(directory)
        self.config.save()

        call_event(ServerCreatedEvent(server))
        return server

    def delete_server(self, server: ServerProcess, *, delete_server_config=False):
        """
        サーバーを削除します。サーバーは停止している必要があります。
        """
        if server.state.is_running:
            raise RuntimeError("Server is running")

        self.servers.pop(server.id, None)
        self.config.servers.pop(server.id, None)

        call_event(ServerDeletedEvent(server))

        if delete_server_config:
            config_path = server.directory / self.SERVER_CONFIG_FILE_NAME
            if config_path.is_file():
                try:
                    os.remove(config_path)
                except OSError as e:
                    log.warning("Failed to delete server_config: %s: %s", str(e), str(config_path))

        self.config.save()

    # public api

    async def start_api_server(self, *, force=False):
        config = self.config.api_server
        if not (config.enable or force):
            log.debug("Disabled API Server")
            return

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

    # events ws broadcast

    @onevent(monitor=True)
    async def _ws_on_change_state(self, event: ServerChangeStateEvent):
        event_data = dict(
            type="event",
            event_type="server_change_state",
            server=event.server.id,
            new_state=event.new_state.name,
            old_state=event.old_state.name,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_file_task_start(self, event: FileTaskStartEvent):
        task = event.task
        src = self.files.swipath(task.src)
        dst = self.files.swipath(task.dst) if task.dst else None
        event_data = dict(
            type="event",
            event_type="file_task_start",
            task_id=task.id,
            task_type=task.type.name,
            src=src,
            dst=dst,
            result=task.result.name,
            progress=task.progress,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_file_task_end(self, event: FileTaskEndEvent):
        task = event.task
        src = self.files.swipath(task.src)
        dst = self.files.swipath(task.dst) if task.dst else None
        event_data = dict(
            type="event",
            event_type="file_task_end",
            task_id=task.id,
            task_type=task.type.name,
            src=src,
            dst=dst,
            result=task.result.name,
            progress=task.progress,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_websocket_client_connect(self, event: WebSocketClientConnectEvent):
        event_data = dict(
            type="event",
            event_type="websocket_client_connect",
            client_id=event.client.id,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_websocket_client_disconnect(self, event: WebSocketClientDisconnectEvent):
        event_data = dict(
            type="event",
            event_type="websocket_client_disconnect",
            client_id=event.client.id,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_server_created(self, event: ServerCreatedEvent):
        event_data = dict(
            type="event",
            event_type="server_created",
            server=event.server.id,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_server_deleted(self, event: ServerDeletedEvent):
        event_data = dict(
            type="event",
            event_type="server_deleted",
            server=event.server.id,
        )
        await self.api_handler.broadcast_websocket(event_data)


def getinst() -> "CraftSwitcher":
    try:
        return CraftSwitcher._inst
    except AttributeError:
        raise RuntimeError("CraftSwitcher is not instanced")
