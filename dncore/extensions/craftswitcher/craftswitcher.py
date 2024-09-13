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
from .database.model import User
from .event import *
from .ext import SwitcherExtensionManager
from .files import FileManager
from .files.event import *
from .publicapi import UvicornServer, APIHandler
from .publicapi.event import *
from .publicapi.model import FileInfo, FileTask
from .serverprocess import ServerProcessList, ServerProcess
from .utils import call_event, datetime_now, safe_server_id, AsyncCallTimer, system_memory, system_perf

if TYPE_CHECKING:
    from dncore.plugin import PluginInfo

log = getLogger(__name__)
__version__ = "2.0.0"


class CraftSwitcher(EventListener):
    _inst: "CraftSwitcher"
    SERVER_CONFIG_FILE_NAME = "swi.server.yml"

    def __init__(self, loop: asyncio.AbstractEventLoop, config_file: Path, *,
                 plugin_info: "PluginInfo" = None, extensions: SwitcherExtensionManager):
        self.loop = loop
        self.config = SwitcherConfig(config_file)
        self.database = db = SwitcherDatabase(config_file.parent)
        self.servers = ServerProcessList()
        self.files = FileManager(self.loop, Path("./minecraft_servers"))
        self.extensions = extensions
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
        self.api_handler = APIHandler(self, api, db)
        #
        self._initialized = False
        #
        self._files_task_broadcast_loop = AsyncCallTimer(self._files_task_broadcast_loop, .5, .5)
        self._perfmon_broadcast_loop = AsyncCallTimer(self._perfmon_broadcast_loop, .5, .5)

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

        await self._perfmon_broadcast_loop.start()
        call_event(SwitcherInitializedEvent())

        if not await self.database.get_users():
            log.info("Creating admin user")
            user = await self.add_user("admin", "abc")
            log.info("  login    : admin")
            log.info("  password : abc")

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

        extensions = dict(self.extensions.extensions)
        self.extensions.extensions.clear()
        waits = [asyncio.shield(call_event(SwitcherExtensionRemoveEvent(i))) for i in extensions.values()]
        if waits:
            await asyncio.wait(waits)

        self.unload_servers()
        AsyncCallTimer.cancel_all_timers()

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

        for _id, val in dict(self.config.servers).items():
            _safe_id = safe_server_id(_id)
            if _id != _safe_id:
                self.config.servers[_safe_id] = val

        call_event(SwitcherConfigLoadedEvent())

    def load_servers(self):
        if self.servers:
            raise RuntimeError("server list is not empty")
        log.debug("Loading servers")
        for server_id, _server_dir in self.config.servers.items():
            server_id = safe_server_id(server_id)
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

    def create_file_info(self, realpath: Path, *, root_dir: Path = None):
        """
        指定されたパスの :class:`FileInfo` を返します
        """
        stats = realpath.stat()

        swipath = self.files.swipath(realpath, force=True, root_dir=root_dir)
        swipath_by_root = self.files.swipath(realpath, force=True) if root_dir else swipath
        try:
            match_server_id = None
            for _server_id, _server_dir in self.config.servers.items():
                if _server_dir == swipath_by_root:
                    match_server_id = _server_id
                    break
        except KeyError:
            match_server_id = None

        is_server_dir = realpath.is_dir() and (realpath / self.SERVER_CONFIG_FILE_NAME).is_file()

        return FileInfo(
            name="" if swipath == "/" else realpath.name,
            path=self.files.swipath(realpath.parent, force=True, root_dir=root_dir),
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

        rootDirが変更されているか、rootDir元に属さないサーバーである場合は :class:`ValueError` を発生させます
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
        server_id = safe_server_id(server_id)
        if server_id in self.servers:
            raise ValueError("Already exists server id")

        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(str(directory))
        server = ServerProcess(self.loop, directory, server_id, config, self.config.server_defaults)

        if set_creation_date:
            config.created_at = datetime_now()

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

    # user

    async def add_user(self, name: str, unhashed_password: str, **kwargs) -> int:

        users = {u.name: u for u in await self.database.get_users()}
        if name in users:
            raise ValueError("Already exists user name")

        password = self.database.generate_hash(unhashed_password)
        user = User(name=name, password=password, **kwargs)
        return await self.database.add_user(user)

    async def create_user(self, name: str, password: str):
        pass

    # task

    async def _files_task_broadcast_loop(self):
        if not self.files.tasks:
            return False

        progress_data = dict(
            type="progress",
            progress_type="file_task",
            tasks=[FileTask.create(task).model_dump(mode="json") for task in self.files.tasks],
        )
        await self.api_handler.broadcast_websocket(progress_data)

    async def _perfmon_broadcast_loop(self):
        now = datetime.datetime.now()

        sys_mem = system_memory(swap=True)
        sys_perf = system_perf()

        servers_info = {}
        for server in self.servers.values():
            if not server or not server.perfmon:
                continue
            servers_info[server] = server.perfmon.info()

        progress_data = dict(
            type="progress",
            progress_type="performance",
            time=int(now.timestamp() * 1000),
            system=dict(
                cpu=dict(
                    usage=sys_perf.cpu_usage,
                ),
                memory=dict(
                    total=sys_mem.total_bytes,
                    available=sys_mem.available_bytes,
                    swap_total=sys_mem.swap_total_bytes,
                    swap_available=sys_mem.swap_available_bytes,
                ),
            ),
            servers=[
                dict(
                    id=s.id,
                    process=dict(
                        cpu_usage=i.cpu_usage,
                        mem_used=i.memory_used_size,
                        mem_virtual_used=i.memory_virtual_used_size,
                    ),
                    jvm=dict(  # TODO: impl jvm perf info
                        cpu_usage=-1,
                        mem_used=-1,
                        mem_total=-1,
                    ),
                    game=dict(
                        ticks=-1,
                    ),
                )
                for s, i in servers_info.items()
            ],
        )
        await self.api_handler.broadcast_websocket(progress_data)

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

    @onevent(monitor=True)
    async def on_file_task_start(self, _: FileTaskStartEvent):
        if self.files.tasks:
            await self._files_task_broadcast_loop.start()

    # events ws broadcast

    @onevent(monitor=True)
    async def _ws_on_change_state(self, event: ServerChangeStateEvent):
        event_data = dict(
            type="event",
            event_type="server_change_state",
            server=event.server.id,
            new_state=event.new_state.value,
            old_state=event.old_state.value,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_file_task_start(self, event: FileTaskStartEvent):
        task = event.task
        event_data = dict(
            type="event",
            event_type="file_task_start",
            task=FileTask.create(task).model_dump(mode="json"),
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_file_task_end(self, event: FileTaskEndEvent):
        task = event.task
        event_data = dict(
            type="event",
            event_type="file_task_end",
            task=FileTask.create(task).model_dump(mode="json"),
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

    @onevent(monitor=True)
    async def _ws_on_server_process_read(self, event: ServerProcessReadEvent):
        event_data = dict(
            type="event",
            event_type="server_process_read",
            server=event.server.id,
            data=event.data
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_extension_add(self, event: SwitcherExtensionAddEvent):
        event_data = dict(
            type="event",
            event_type="extension_add",
            extension=event.extension.name,
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_extension_remove(self, event: SwitcherExtensionRemoveEvent):
        event_data = dict(
            type="event",
            event_type="extension_remove",
            extension=event.extension.name,
        )
        await self.api_handler.broadcast_websocket(event_data)


def getinst() -> "CraftSwitcher":
    try:
        return CraftSwitcher._inst
    except AttributeError:
        raise RuntimeError("CraftSwitcher is not instanced")
