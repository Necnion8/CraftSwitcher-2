import asyncio
import datetime
import mimetypes
import os
import shutil
import time
from collections import defaultdict
from logging import getLogger
from pathlib import Path
from typing import Coroutine, TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dncore.event import EventListener, onevent
from . import utilscreen as screen
from .abc import ServerState, ServerType, FileWatchInfo, JavaExecutableInfo
from .config import SwitcherConfig, ServerConfig, JavaPresetConfig
from .database import SwitcherDatabase
from .database.model import User
from .errors import ServerProcessingError, NoDownloadFile
from .event import *
from .ext import SwitcherExtensionManager
from .fileback import Backupper
from .files import FileManager
from .files.event import *
from .files.event import WatchdogEvent
from .jardl import ServerDownloader, ServerBuild
from .publicapi import UvicornServer, APIHandler, WebSocketClient
from .publicapi.event import *
from .publicapi.model import FileInfo, FileTask, ServerStatusInfo
from .publicapi.server import FallbackStaticFiles
from .repomov1 import ReportModuleServer
from .serverprocess import ServerProcessList, ServerProcess
from .utiljava import JavaPreset, check_java_executable
from .utils import *

if TYPE_CHECKING:
    from dncore.plugin import PluginInfo

log = getLogger(__name__)
__version__ = "2.0.0"


def fix_mimetypes():
    mimetypes.add_type('application/javascript', '.js')
    mimetypes.add_type('text/css', '.css')
    mimetypes.add_type('image/svg+xml', '.svg')


class CraftSwitcher(EventListener):
    _inst: "CraftSwitcher"
    SERVER_CONFIG_FILE_NAME = "swi.server.yml"

    def __init__(self, loop: asyncio.AbstractEventLoop, config_file: Path, *,
                 plugin_info: "PluginInfo" = None, web_root_dir: Path = None, extensions: SwitcherExtensionManager):
        self.loop = loop
        self.config = SwitcherConfig(config_file)
        self.database = db = SwitcherDatabase(config_file.parent)
        self.servers = ServerProcessList()
        self.files = FileManager(self.loop, Path("./minecraft_servers"))
        self.repomo_server = ReportModuleServer(loop)
        self.backups = None  # type: Backupper | None
        self.extensions = extensions
        # jardl
        self.server_downloaders = defaultdict(list)  # type: dict[ServerType, list[ServerDownloader]]
        # java
        self.java_presets = []  # type: list[JavaPreset]
        """プリセット設定済みor自動的にセットされたプリセット"""
        self.java_detections = []  # type: list[JavaExecutableInfo]
        """自動検出されたJavaのリスト"""
        # api
        global __version__
        __version__ = str(plugin_info.version.numbers) if plugin_info else __version__
        api = FastAPI(
            title="CraftSwitcher",
            version=__version__,
        )
        api.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
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

        if web_root_dir:
            api.mount("/", FallbackStaticFiles(directory=web_root_dir, html=True, check_dir=False), name="static")

        #
        self._initialized = False
        self._directory_changed_servers = set()  # type: set[str]  # 停止後にディレクトリを更新するサーバー
        self._remove_servers = set()  # type: set[str]  # 停止後に削除するサーバー
        self._watch_files = defaultdict(set)  # type: dict[Path, set[FileWatchInfo]]
        self._scan_java_task = None  # type: asyncio.Task | None
        #
        self._files_task_broadcast_loop = AsyncCallTimer(self._files_task_broadcast_loop, .5, .5)
        self._perfmon_broadcast_loop = AsyncCallTimer(self._perfmon_broadcast_loop, .5, .5)
        self.add_default_server_downloaders()

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
        if self.backups is None:
            backups_dir = Path(self.config.backup.backups_directory)
            trash_dir = Path(self.config.backup.trash_files_directory)
            self.backups = Backupper(
                self.loop, config=self.config.backup, database=self.database, files=self.files,
                backups_dir=backups_dir,
                trash_dir=trash_dir,
            )

        self.print_welcome()

        await self.files.start()
        await self.start_api_server()
        await self.repomo_server.open()

        await self._perfmon_broadcast_loop.start()
        call_event(SwitcherInitializedEvent())

        if screen.is_available():
            try:
                await self.reattach_server_screens()
            except Exception as e:
                log.exception("Exception in attach server screens", exc_info=e)

        if not await self.database.get_users():
            log.info("Creating admin user")
            user = await self.add_user("admin", "abc")
            log.info("  login    : admin")
            log.info("  password : abc")

        asyncio.create_task(self.scan_java_executables())

    async def _test(self):
        root_dir = self.files.root_dir
        server_dir = root_dir / "paper1_8"
        plugins_dir = server_dir / "plugins"
        plugins = [plugins_dir / "ItemRecall.jar", plugins_dir / "LuckPerms.jar", ]
        out_file = root_dir / "test.zip"

        if out_file.is_file():
            os.remove(out_file)

        # configuration
        zip_out = out_file
        zip_root = server_dir
        zip_target = [*plugins, root_dir / "paper1_21" / "eula.txt"]
        # configuration

        zip_target = zip_target if isinstance(zip_target, list) else [zip_target]
        log.info("START MAKE ARCHIVE")
        # log.debug(f"  output: {zip_out.relative_to(root_dir)}")
        log.debug(f"  root  : {zip_root.relative_to(root_dir)}")
        log.debug(f"  target: {', '.join(map(lambda p: str(p.relative_to(root_dir)), zip_target))}")

        task = await self.files.make_archive(zip_out, zip_root, zip_target)
        await task

        log.info("COMPLETED")

        for entry in await self.files.list_archive(zip_out):
            log.debug(f"- {entry.filename}")

        #

    async def shutdown(self):
        if not self._initialized:
            return
        log.info("Shutdown CraftSwitcher")

        await call_event(SwitcherShutdownEvent())

        try:
            try:
                await self.shutdown_all_servers(exclude_screen=self.config.screen.enable_keep_server_on_shutdown)
            except Exception as e:
                log.warning("Exception in shutdown servers", exc_info=e)

            try:
                await self.repomo_server.close()
            except Exception as e:
                log.warning("Exception in close repomo", exc_info=e)

            try:
                await self.close_api_server()
            except Exception as e:
                log.warning("Exception in close api server", exc_info=e)

            try:
                self.clear_file_watch()
                await self.files.shutdown()
            except Exception as e:
                log.warning("Exception in shutdown file manager", exc_info=e)

            try:
                await self.database.close()
            except Exception as e:
                log.warning("Exception in close database", exc_info=e)

            extensions = dict(self.extensions.extensions)
            self.extensions.extensions.clear()
            waits = [asyncio.shield(call_event(SwitcherExtensionRemoveEvent(i))) for i in extensions.values()]
            if waits:
                await asyncio.wait(waits)

            try:
                self.unload_servers()
            except ValueError as e:
                log.warning(f"Failed to unload_servers: {e}")

            AsyncCallTimer.cancel_all_timers()

        finally:
            try:
                del CraftSwitcher._inst
            except AttributeError:
                pass
            self._initialized = False

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
        self._directory_changed_servers.clear()
        self._remove_servers.clear()

        for server_id, _server_dir in self.config.servers.items():
            server_id = safe_server_id(server_id)
            if server_id in self.servers:
                log.warning("Already exists server id!: %s", server_id)
                continue

            server = None  # type: ServerProcess | None
            server_dir, config = self._init_server_directory(server_id, _server_dir)
            if server_dir and config:
                server = self._init_server(server_id, server_dir, config)

            self.servers[server_id] = server

        log.info("Loaded %s server", len(self.servers))
        call_event(SwitcherServersLoadedEvent())

    def resize_logs_size(self):
        lines = self.config.max_console_lines_in_memory

        for server in self.servers.values():
            if not server:
                continue

            server._logs = server._create_logs_list(lines)

    def _init_server_directory(self, server_id: str, swi_directory: str):
        try:
            server_dir = self.files.realpath(swi_directory)
        except ValueError:
            log.warning("Not allowed path: %s: %s", server_id, swi_directory)
            return None, None

        server_config_path = server_dir / self.SERVER_CONFIG_FILE_NAME
        config = ServerConfig(server_config_path)
        config.source_id = generate_uuid().hex

        if not server_config_path.is_file():
            log.warning("Not exists server config: %s", server_dir)
            return None, None

        try:
            config.load()
        except Exception as e:
            log.error("Error in load server config: %s: %s", server_id, str(e))
            return None, None

        return server_dir, config

    def _init_server(self, server_id: str, server_dir: Path, config: ServerConfig):
        if config.source_id is None:
            config.source_id = generate_uuid().hex
            config.save()
            log.error(f"[{server_id}] Invalid source_id. Reset to: {config.source_id!r}")

        return ServerProcess(
            self.loop,
            directory=server_dir,
            server_id=server_id,
            config=config,
            global_config=self.config.server_defaults,
            repomo_config=self.config.repomo,
            max_logs_line=self.config.max_console_lines_in_memory,
        )

    def reload_servers(self):
        log.debug("Loading servers")

        new_servers = {safe_server_id(k): d for k, d in self.config.servers.items()}
        new_ids = set(new_servers.keys())
        old_ids = set(self.servers.keys())

        # remove old
        removes = {
            server_id: self.servers[server_id]
            for server_id in old_ids if server_id not in new_ids
        }
        for server_id, server in dict(removes).items():
            if server and server.state.is_running:  # ignore
                log.debug("Ignore server remove: not stopped: (%s)", server.state.name)
                removes.pop(server_id)
                self._remove_servers.add(server_id)
            else:
                try:
                    self.delete_server(server or server_id)
                except ValueError:
                    pass  # ignored 404

        # update
        updates = {
            server_id: self.servers[server_id]
            for server_id in old_ids if server_id in new_ids
        }
        for server_id, server in updates.items():
            if server:
                if server.state.is_running:
                    log.debug("Ignore server.directory update: not stopped: (%s)", server.state.name)
                    self._directory_changed_servers.add(server_id)
                else:
                    _server_dir = new_servers[server_id]
                    server_dir, config = self._init_server_directory(server_id, _server_dir)
                    if server_dir and config:
                        server.directory = server_dir
                        server.config = config

        # add new
        news = {}  # type: dict[str, ServerProcess | None]
        for server_id, _server_dir in new_servers.items():
            if server_id in old_ids:
                continue

            server = None  # type: ServerProcess | None
            server_dir, config = self._init_server_directory(server_id, _server_dir)
            if server_dir and config:
                server = self._init_server(server_id, server_dir, config)

            self.servers[server_id] = server
            news[server_id] = server

            if server:
                log.info("Server created: %s", server_id)
                call_event(ServerCreatedEvent(server))
            else:
                log.info("Server added: %s", server_id)

        log.info("Loaded %s server", len(self.servers))
        call_event(SwitcherServersReloadedEvent(removes, updates, news))

    async def shutdown_all_servers(self, *, exclude_screen=False):
        async def _shutdown(s: ServerProcess):
            if exclude_screen:
                if s.screen_session_name and s.state != ServerState.BUILD:  # ビルド中なら無視せず終了
                    try:
                        await s.detach_screen()
                    except Exception as e:
                        log.warning("Exception in detach server (ignored)", exc_info=e)
                    return

            if s.state.is_running:
                try:
                    try:
                        await s.stop()
                    except ServerProcessingError:
                        await s.kill()
                except Exception as e:
                    log.exception("Exception in server shutdown (ignored)", exc_info=e)
                try:
                    await s.wait_for_shutdown()
                except asyncio.TimeoutError:
                    log.warning("Shutdown expired: %s", s.id)
                    try:
                        await s.kill()
                    except Exception as e:
                        log.warning("Exception in server.kill()", exc_info=e)

            await s.clean_builder()

        if servers := [_shutdown(s) for s in self.servers.values() if s]:
            log.info("Shutting down all servers")
            await asyncio.wait(servers)

    def unload_servers(self):
        """
        サーバーリストを空にします

        :except ValueError: 起動しているサーバーがある場合
        """
        if not self.servers:
            return

        if any(not s.screen_session_name and s.state.is_running for s in self.servers.values() if s):
            raise ValueError("Contains not stopped server")

        call_event(SwitcherServersUnloadEvent())
        self.servers.clear()

    async def reattach_server_screens(self):
        screen_names = screen.list_names()

        for server in self.servers.values():
            if not server:
                continue

            screen_name = self.screen_session_name_of(server)
            if screen_name in screen_names:
                try:
                    await server.attach_to_screen_session(screen_name)
                except Exception as e:
                    log.warning("Failed to attach to %s server screen", server.id, exc_info=e)

    # server downloader

    def add_default_server_downloaders(self):
        from .jardl import defaults
        for type_, downloader in defaults().items():
            self.add_server_downloader(type_, downloader)

    def add_server_downloader(self, type_: ServerType, downloader: ServerDownloader):
        if downloader not in self.server_downloaders[type_]:
            self.server_downloaders[type_].append(downloader)

    def remove_server_downloader(self, downloader: ServerDownloader):
        for type_, downloaders in self.server_downloaders.items():
            try:
                downloaders.remove(downloader)
            except ValueError:
                pass

    async def get_java_version_from_server_type(self, server_type: ServerType, server_version: str) -> int | None:
        if server_type.spec.is_proxy:
            return {
                # https://docs.papermc.io/velocity/getting-started#installing-java
                ServerType.VELOCITY: 17,
                # https://www.spigotmc.org/wiki/bungeecord-installation/#installing-bungeecord-on-linux
                ServerType.BUNGEECORD: 8,
                ServerType.WATERFALL: 8,

            }.get(server_type)

        else:
            try:
                downloader = self.server_downloaders[ServerType.VANILLA][0]
            except (KeyError, IndexError):
                return

            for ver in await downloader.list_versions():
                if ver.mc_version != server_version:
                    continue

                for build in reversed(await ver.list_builds()):
                    if major_version := build.java_major_version:
                        return major_version
                break

        return None

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

    def get_ws_clients_by_watchdog_event(self, event: WatchdogEvent):
        clients = set()
        for watches in self._watch_files.values():
            for watch in watches:
                if isinstance(watch.owner, WebSocketClient) and (
                        watch.path == event.real_path.parent
                        or (isinstance(event, WatchdogMovedEvent) and watch.path == event.dst_real_path.parent)
                ):
                    clients.add(watch.owner)
        return clients

    def add_file_watch(self, path: Path, owner: Any) -> FileWatchInfo:
        """
        指定されたパスをファイルシステムイベント監視リストに加えます
        """
        self.files.add_watch(path)
        watches = self._watch_files[path]
        info = FileWatchInfo(path, owner)
        watches.add(info)
        return info

    def remove_file_watch(self, watch: FileWatchInfo):
        """
        指定されたパスをファイルシステムイベント監視リストから削除します
        """
        watches = self._watch_files[watch.path]
        watches.discard(watch)
        if not watches:
            self._watch_files.pop(watch.path)
            self.files.remove_watch(watch.path)

    def clear_file_watch(self):
        for path in self._watch_files.keys():
            self.files.remove_watch(path)
        self._watch_files.clear()

    def get_watches(self, path: Path) -> set[FileWatchInfo]:
        if path in self._watch_files:
            return set(self._watch_files[path])
        return set()

    def get_watched_paths(self) -> set[Path]:
        return set(self._watch_files.keys())

    def screen_session_name_of(self, server: "ServerProcess"):
        return self.config.screen.session_name_prefix + server.id

    # java

    def get_java_preset(self, name: str) -> JavaPreset | None:
        for preset in self.java_presets:
            if preset.name == name:
                return preset

    async def add_java_preset(self, name: str, executable: str | Path | JavaExecutableInfo) -> JavaPreset:
        """
        指定されたJavaコマンドをテストし、指定された名でプリセットを保存してリストに加えます

        設定に含まれていない同じ名前のプリセットは上書きされます (自動検出によるプリセットなど)

        :except ValueError: すでに設定されているプリセット名
        """
        if any(c.name == name for c in self.config.java.presets):
            raise ValueError(f"Already exists name: {name}")
        self.remove_java_preset(name)  # 競合名を全て削除

        config = JavaPresetConfig()
        config.name = name

        if isinstance(executable, JavaExecutableInfo):
            config.executable = str(executable.path)
            info = executable
        else:
            try:
                info = await check_java_executable(Path(executable))
            except Exception as e:
                log.warning(f"Error in check java: {executable!r}: {e}")
                info = None
            config.executable = str(info and info.path or executable)

        preset = JavaPreset(config.name, config.executable, info, config)
        self.java_presets.append(preset)

        self.config.java.presets.append(config)
        self.config.save()
        return preset

    def remove_java_preset(self, name: str) -> bool:
        """
        指定された名のプリセットを設定とプリセットリストから削除します
        """
        _changed = False
        # remove in config
        for config in list(self.config.java.presets):
            if config.name == name:
                self.config.java.presets.remove(config)
                _changed = True

        if _changed:
            self.config.save()

        # remove preset
        for preset in list(self.java_presets):
            if preset.name == name:
                self.java_presets.remove(preset)
                _changed = True

        return _changed

    async def scan_java_executables(self):
        task = self._scan_java_task
        if not task or task.done():
            self._scan_java_task = task = asyncio.create_task(self._scan_java_executables())
        return await asyncio.shield(task)

    async def _scan_java_executables(self):
        log.debug("Checking java executables")
        exe_name = "java.exe" if is_windows() else "java"
        perf_time = time.perf_counter()

        _check_java_type = JavaExecutableInfo | None, JavaPresetConfig | None
        sem = asyncio.Semaphore(3)
        tasks = []  # type: list[Coroutine[None, None, _check_java_type]]

        async def check_java(_path: Path, _config: JavaPresetConfig | None) -> _check_java_type:
            async with sem:
                try:
                    return await check_java_executable(_path), _config
                except Exception as e:
                    log.warning(f"Error in check java: {_path!r}: {e}")
            return None, _config

        # default java
        default_java_info = None  # type: JavaExecutableInfo | None
        if default_java := shutil.which("java"):
            if (default_java := Path(default_java).resolve()).exists():
                default_java_info = (await check_java(default_java, None))[0]

        # preset java
        for preset_c in self.config.java.presets:
            tasks.append(check_java(Path(shutil.which(preset_c.executable) or preset_c.executable), preset_c))

        # detection java
        for search_dir in self.config.java.auto_detection_paths:
            if not (search_dir_path := Path(search_dir)).exists():
                continue
            for child in search_dir_path.glob(f"*/bin/{exe_name}"):  # type: Path
                if (child := child.resolve()).is_file():
                    tasks.append(check_java(child, None))

        # check
        presets = {}  # type: dict[str, JavaPreset]
        names = set()
        detections = {}  # type: dict[str, JavaExecutableInfo]

        if tasks:
            log.debug("Testing %s java executables", len(tasks))
            for info, config in await asyncio.gather(*tasks):  # type: JavaExecutableInfo | None, JavaPresetConfig | None
                if not info:
                    # 設定済みand利用不可
                    if config:
                        presets[config.executable] = JavaPreset(config.name, config.executable, None, config)
                        names.add(config.name)

                elif str(info.path.absolute()) not in presets:
                    # 自動検出(名前あたり１つ)
                    if not config:
                        detections[str(info.path.absolute())] = info
                        name = f"java-{info.java_major_version}"
                        if name in names:
                            continue
                        executable = str(info.path)
                    else:
                        # 設定済み
                        name = config.name
                        executable = config.executable

                    presets[str(info.path.absolute())] = JavaPreset(name, executable, info, config)
                    names.add(name)

        # update list
        self.java_presets.clear()
        self.java_presets.extend(presets.values())
        if default_java_info:
            self.java_presets.insert(0, JavaPreset("default", "java", default_java_info, None))
        self.java_detections.clear()
        self.java_detections.extend(detections.values())

        perf_time = round((time.perf_counter() - perf_time) * 1000)
        major_vers = sorted(set(p.major_version for p in presets.values() if p.info))
        log.info("Java versions found (available presets: %s): %s",
                 sum(bool(p.info) for p in presets.values()), ", ".join(map(str, major_vers)))
        log.debug("processing time: %sms", perf_time)

    # server api

    def create_server_config(self, server_directory: str | Path, jar_file=""):
        """
        指定されたサーバーディレクトリで :class:`ServerConfig` を作成します
        """
        config_path = Path(server_directory) / self.SERVER_CONFIG_FILE_NAME
        config = ServerConfig(config_path)
        config.source_id = generate_uuid().hex
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

    def create_server(self, server_id: str, directory: str | Path, config: ServerConfig,
                      *, set_creation_date=True, set_accept_eula: bool = None, ):
        """
        サーバーを作成し、CraftSwitcherに追加されます。

        この操作により、サーバーディレクトリにサーバー設定ファイルが保存されます。

        :except ValueError: 既に存在するID
        :except NotADirectoryError: 親ディレクトリが存在しない
        """
        server_id = safe_server_id(server_id)
        if server_id in self.servers:
            raise ValueError("Already exists server id")

        directory = Path(directory)
        if not directory.is_dir():
            if not directory.parent.is_dir():
                raise NotADirectoryError(str(directory))
            directory.mkdir()

        config.source_id = generate_uuid().hex
        server = self._init_server(server_id, directory, config)

        if set_creation_date:
            config.created_at = datetime_now()

        if set_accept_eula is not None:
            server.set_eula_accept(set_accept_eula or False)

        config.save(force=True)
        self.servers.append(server)
        self.config.servers[server_id] = self.files.swipath(directory)
        self.config.save()

        log.info("Server created: %s", server_id)
        call_event(ServerCreatedEvent(server))
        return server

    def delete_server(self, server: str | ServerProcess, *, delete_server_config=False):
        """
        サーバーを削除します。サーバーは停止している必要があります。
        """
        if not isinstance(server, ServerProcess):
            try:
                _server = self.servers[server]
            except KeyError:
                raise ValueError(f"Not exists server {server}")

            if not _server:
                # not loaded
                self._remove_server(server)
                log.info("Server deleted: %s (not loaded, silent)", server)
                self.config.save()
                return

            server = _server

        if server.state.is_running:
            raise RuntimeError("Server is running")

        self._remove_server(server.id)

        log.info("Server deleted: %s", server.id)
        call_event(ServerDeletedEvent(server))

        if delete_server_config:
            config_path = server.directory / self.SERVER_CONFIG_FILE_NAME
            if config_path.is_file():
                try:
                    os.remove(config_path)
                except OSError as e:
                    log.warning("Failed to delete server_config: %s: %s", str(e), str(config_path))

        self.config.save()

    def _remove_server(self, server_id: str):
        self._directory_changed_servers.discard(server_id)
        self._remove_servers.discard(server_id)
        self.servers.pop(server_id, None)
        self.config.servers.pop(server_id, None)

    async def download_server_jar(self, server: ServerProcess, jar_build: ServerBuild, server_type: ServerType,
                                  ) -> FileTask:
        """
        ビルド情報を元に、サーバーファイルまたはインストールファイルをダウンロードします。

        ビルドが必要なときのみ、指定されたサーバーにビルダーオブジェクトを設定されます。

        ダウンロードURLが見つからない場合は :class:`NoDownloadFile` エラーが発生します
        """
        try:
            if not jar_build.download_url:
                if not jar_build.is_loaded_info():
                    await jar_build.fetch_info()
        except Exception as e:
            raise NoDownloadFile("No available download url: jar_build.fetch_info() error") from e

        if not jar_build.download_url:
            raise NoDownloadFile("No available download url")

        filename = jar_build.download_filename

        if not filename:
            filename = await self.files.fetch_download_filename(jar_build.download_url)
        if not filename:
            filename = "builder.jar" if jar_build.is_require_build() else "server.jar"

        download_dir = jar_build.work_dir
        cwd = server.directory / download_dir if download_dir else server.directory
        dst = cwd / filename
        if cwd.exists():
            _loop = 0
            while dst.exists():
                _loop += 1
                name, *suf = filename.rsplit(".", 1)
                dst = cwd / ".".join([f"{name}-{_loop}", *suf])
        else:
            cwd.mkdir(exist_ok=True, parents=True)

        dst_swi = self.files.swipath(dst, root_dir=server.directory)
        task = self.files.download(jar_build.download_url, dst, server, dst_swi_path=dst_swi)

        async def _callback(f: asyncio.Future):
            exc = f.exception()
            if exc:
                log.warning("Failed to download server", exc_info=exc)
                return

            jar_build.downloaded_path = dst
            if jar_build.is_require_build():
                server.builder = await jar_build.setup_builder(server, dst)

            else:
                config = server._config
                config.type = server_type
                config.enable_launch_command = False
                config.launch_option.jar_file = dst.name
                config.save()

        task.fut.add_done_callback(lambda f: asyncio.create_task(_callback(f)))
        return task

    def get_server_status(self, server: ServerProcess):
        if not server.state.is_running:
            return None

        report = self.repomo_server.get_status(server.id)

        total = report and report.total_memory
        free = report and report.free_memory

        return ServerStatusInfo(
            id=server.id,
            process=ServerStatusInfo.Process(
                cpu_usage=p_info.cpu_usage,
                mem_used=p_info.memory_used_size,
                mem_virtual_used=p_info.memory_virtual_used_size,
            ) if (p_info := server.get_perf_info()) else None,
            jvm=ServerStatusInfo.JVM(
                cpu_usage=None if (val := report.cpu_usage) is None else val * 100,
                mem_used=None if total is None or free is None else total - free,
                mem_total=None if total is None else total,
            ) if report else None,
            game=ServerStatusInfo.Game(
                ticks=None if (val := report.tps) is None else val,
                max_players=None if (val := report.max_players) is None else val,
                online_players=None if (val := report.players) is None else len(val),
                players=None if report.players is None else [
                    ServerStatusInfo.Game.Player(
                        uuid=str(p_uuid),
                        name=p_name,
                    ) for p_uuid, p_name in report.players.items()
                ],
            ) if report else None,
        )

    # public api

    async def start_api_server(self, *, force=False):
        config = self.config.api_server
        if not (config.enable or force):
            log.debug("Disabled API Server")
            return

        try:
            ssl_key_file = config.ssl_keyfile or None
            ssl_cert_file = config.ssl_certfile or None

            if ssl_key_file:
                if not Path(ssl_key_file).is_file():
                    log.warning("SSL key file not exists: %s", Path(ssl_key_file).absolute())
                if not Path(ssl_cert_file).is_file():
                    log.warning("SSL cert file not exists: %s", Path(ssl_cert_file).absolute())

            await self.api_server.start(
                self.api_handler.router,
                host=config.bind_host,
                port=config.bind_port,
                ssl_keyfile=config.ssl_keyfile or None,
                ssl_certfile=config.ssl_certfile or None,
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

        progress_data = dict(
            type="progress",
            progress_type="performance",
            time=int(now.timestamp() * 1000),
            system=dict(
                cpu=dict(
                    usage=sys_perf.cpu_usage,
                    count=sys_perf.cpu_count,
                ),
                memory=dict(
                    total=sys_mem.total_bytes,
                    available=sys_mem.available_bytes,
                    swap_total=sys_mem.swap_total_bytes,
                    swap_available=sys_mem.swap_available_bytes,
                ),
            ),
            servers=[
                self.get_server_status(s).model_dump(mode="json")
                for s in self.servers.values()
                if s and s.state.is_running
            ],
        )
        await self.api_handler.broadcast_websocket(progress_data)

    # events

    @onevent(monitor=True)
    async def on_server_created(self, event: ServerCreatedEvent):
        await self.repomo_server.handle_on_server_add(event.server.id)

    @onevent(monitor=True)
    async def on_server_deleted(self, event: ServerDeletedEvent):
        await self.repomo_server.handle_on_server_remove(event.server.id)

    @onevent(monitor=True)
    async def on_change_state(self, event: ServerChangeStateEvent):
        server = event.server

        await self.repomo_server.handle_on_server_state_update(server.id, event.new_state)

        if server.state is ServerState.STOPPED:
            # queue removes
            if server.id in self._remove_servers:
                self.delete_server(server)
                return

            # queue dir update
            elif server.id in self._directory_changed_servers:
                self._directory_changed_servers.discard(server.id)
                try:
                    _server_dir = self.config.servers[server.id]
                except KeyError:
                    pass
                else:
                    server_dir, config = self._init_server_directory(server.id, _server_dir)
                    if server_dir and config:
                        server.directory = server_dir
                        server.config = config

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

    @onevent(monitor=True)
    async def _ws_on_switcher_config_loaded(self, _: SwitcherConfigLoadedEvent):
        event_data = dict(
            type="event",
            event_type="switcher_config_loaded",
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_switcher_servers_loaded(self, _: SwitcherServersLoadedEvent):
        event_data = dict(
            type="event",
            event_type="switcher_servers_loaded",
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_switcher_servers_reloaded(self, _: SwitcherServersReloadedEvent):
        event_data = dict(
            type="event",
            event_type="switcher_servers_reloaded",
        )
        await self.api_handler.broadcast_websocket(event_data)

    @onevent(monitor=True)
    async def _ws_on_file_created(self, event: WatchdogCreatedEvent):
        if not event.swi_path:
            return

        clients = self.get_ws_clients_by_watchdog_event(event)
        if not clients:
            return

        event_data = dict(
            type="event",
            event_type="file_created",
            src=event.swi_path,
            file_info=self.create_file_info(event.real_path).model_dump_json(),
        )
        await self.api_handler.broadcast_websocket(event_data, clients=clients)

    @onevent(monitor=True)
    async def _ws_on_file_deleted(self, event: WatchdogDeletedEvent):
        if not event.swi_path:
            return

        clients = self.get_ws_clients_by_watchdog_event(event)
        if not clients:
            return

        event_data = dict(
            type="event",
            event_type="file_deleted",
            src=event.swi_path,
        )
        await self.api_handler.broadcast_websocket(event_data, clients=clients)

    @onevent(monitor=True)
    async def _ws_on_file_modified(self, event: WatchdogModifiedEvent):
        if not event.swi_path:
            return

        clients = self.get_ws_clients_by_watchdog_event(event)
        if not clients:
            return

        event_data = dict(
            type="event",
            event_type="file_modified",
            src=event.swi_path,
            file_info=self.create_file_info(event.real_path).model_dump_json(),
        )
        await self.api_handler.broadcast_websocket(event_data, clients=clients)

    @onevent(monitor=True)
    async def _ws_on_file_moved(self, event: WatchdogMovedEvent):
        if event.swi_path is None and event.dst_swi_path is None:
            return

        clients = self.get_ws_clients_by_watchdog_event(event)
        if not clients:
            return

        event_data = dict(
            type="event",
            event_type="file_moved",
            src=event.swi_path or None,
            dst=event.dst_swi_path or None,
            file_info=self.create_file_info(event.dst_real_path).model_dump_json(),
        )
        await self.api_handler.broadcast_websocket(event_data, clients=clients)


def getinst() -> "CraftSwitcher":
    try:
        return CraftSwitcher._inst
    except AttributeError:
        raise RuntimeError("CraftSwitcher is not instanced")


fix_mimetypes()
