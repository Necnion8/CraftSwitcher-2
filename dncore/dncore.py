import asyncio
import logging
import platform
import re
import signal
import sys
import time
from pathlib import Path
from typing import Optional, Callable, TypeVar, Sequence

import aiohttp
import colorlog
import discord

from dncore.abc import Version, IGNORE_FRAME
from dncore.appconfig import AppConfig
from dncore.appconfig.data import DataFile
from dncore.command import CommandManager
from dncore.configuration import ValueNotSet
from dncore.configuration.files import ConfigurationValueError, CnfErr
from dncore.discord import DiscordClient
from dncore.discord.commands import DNCoreCommands
from dncore.discord.events import DiscordInitializeEvent, DiscordClosingEvent
from dncore.discord.status import ActivityManager, Activity
from dncore.errors import RestartRequest
from dncore.event import EventManager
from dncore.plugin import PluginManager, Plugin, PluginInfo
from dncore.util.instance import call_event
from dncore.util.logger import DaysRotatingFileHandler, PackageNameInserter, RedirectStream, get_caller_logger

__version__ = "6.1.0"
__date__ = "2024/07/24"
version_info = Version.parse(__version__ + "/" + __date__[2:].replace("/", ""))
__all__ = ["DNCore", "__version__", "__date__", "version_info", "DNCoreAPI"]
log = logging.getLogger(__name__)
T = TypeVar("T")


# noinspection PyMethodMayBeStatic
class DNCore(object):
    def __init__(self, *, config_dir="config/", plugins_dir="plugins/"):
        self.loop = None  # type: Optional[asyncio.AbstractEventLoop]
        _core(self)

        self._restart = False
        self._init = False
        self._default_intents = discord.Intents.presences.flag
        self._last_shutdown_time = 0
        self.config_dir = Path(config_dir)
        self.plugins_dir = Path(plugins_dir)
        self.conn_act = None  # type: Optional[Activity]

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.config = AppConfig(self.config_dir / "config.yml", errors=CnfErr.RAISE)
        self.data = DataFile(self.config_dir / "data.yml")
        self.events = EventManager(self.loop)
        self.plugins = PluginManager(self.loop, self.plugins_dir)
        self.commands = CommandManager(self.loop, self.config_dir / "commands.yml")
        self.default_commands = None  # type: DNCoreCommands | None
        self.activity_manager = ActivityManager(self.loop)
        self.client = None  # type: Optional[DiscordClient]
        self.aio = aiohttp.ClientSession(loop=self.loop)

    @property
    def version(self):
        return version_info

    def run(self):
        if self._init:
            raise RuntimeError("already initialized")

        self._restart = False
        self._init = False

        Path("logs").mkdir(exist_ok=True)
        self._loggers()
        error = False
        try:
            log.info("Python %s | discord.py %s | dnCore v%s",
                     platform.python_version(), discord.__version__, str(__version__))

            start_at = time.perf_counter()
            if not self.loop.run_until_complete(self.startup()):
                error = True
                return 1

            end_at = time.perf_counter()
            init_time = (end_at - start_at) * 1000
            log.info(f"初期化完了 ({round(init_time)}ms) / dnCore Bot Client v{__version__}")

            if not self.config.debug.no_connect and self.config.discord.token:
                try:
                    self.loop.run_until_complete(self.connect(fail_to_shutdown=True))
                except discord.DiscordException as e:
                    log.error(f"Failed to connect to Discord:")
                    log.error(f"{type(e).__name__}: {e}")
                    error = True
                    return 1

        except (Exception,):
            log.exception(f"起動できません")
            error = True
            return 1

        finally:
            if error:
                try:
                    self.loop.run_until_complete(self.shutdown())
                except (Exception,) as ignored:
                    pass

        self.loop.create_task(self._empty())
        self._signals()
        self._init = True

        if self.config.debug.no_connect:
            log.warning("デバッグ no_connect が有効です")

        else:
            try:
                self.loop.run_until_complete(self.client.wait_until_ready())
                log.info(f"Discordに接続しました: {self.client.user}")

                guilds = self.client.guilds
                if guilds:
                    log.info("")
                    for guild in guilds:
                        log.info(f"- {guild.id}/{guild.name} - {guild.owner or guild.owner_id}")
                    log.info("")

            except asyncio.CancelledError:
                pass

        self.loop.run_forever()

        if self._restart:
            log.warning("Restarting")
            raise RestartRequest()

        log.info("Good-bye!")
        return 0

    async def startup(self):
        if self._init:
            raise RuntimeError("already initialized")

        self.config_dir.mkdir(exist_ok=True)
        self.plugins_dir.mkdir(exist_ok=True)

        try:
            self.config.load()

        except ConfigurationValueError as e:
            log.warning("設定ファイルに値エラーがあります")
            for s in e.stacks:
                log.warning(f"- ({s.entry.type.typename()}) {s.key:20} -> {s.error}",
                            exc_info=None if isinstance(s.error, ValueNotSet) else s.error)
            return False

        if not self.config.discord.token and not self.config.debug.no_connect:
            log.warning("Discordボットトークンを設定してください。(場所: config/config.yml -> discord.token)")
            return False

        self.data.load()
        self.update_logger_level()
        self.register_activities()
        self.commands.load_from_config()
        self.default_commands = DNCoreCommands()
        self.commands.register_class(self, self.default_commands, "__dncore__")
        self.events.register_listener(self, self.default_commands)

        self.plugins.load_plugins(ignore_names=self.config.plugin.disabled_plugins)
        await self.plugins.enable_plugins()

        actives, aliases = self.commands.remap()
        log.info(f"コマンド {actives}個を有効化しました。(別名: {aliases}個)")

        return True

    async def shutdown(self, *, restart=False):
        last_time = self._last_shutdown_time
        if last_time:
            if time.time() - last_time > 6:
                self._shutdown_force()
                return
        else:
            self._last_shutdown_time = time.time()

        try:
            await self._shutdown(restart=restart)

        finally:
            self.loop.stop()

    def _shutdown_force(self):
        log.error("FORCE SHUTDOWN TRIGGERED")
        try:
            pending = [
                t for t in asyncio.all_tasks(loop=self.loop)
                if t is not asyncio.current_task(loop=self.loop) and not t.done()
            ]
            log.error("Ignored %s tasks", len(pending))
        finally:
            self.loop.stop()

    async def _shutdown(self, *, restart: bool):
        self._restart = restart

        log.info("システムを停止中･･･")
        try:
            try:
                await self.disconnect()
            except Exception as e:
                log.error(f"Exception in disconnect: {e}")

            try:
                await self.plugins.disable_plugins()
            except Exception as e:
                log.exception(f"Exception in disable plugins: {e}")

            try:
                self.events.cleanup()
                self.commands.cleanup()
                self.activity_manager.cleanup()
            except Exception as e:
                log.exception(f"Exception in cleanup events and activities: {e}")

            try:
                await self.aio.close()
            except Exception as e:
                log.error(f"Exception in close aiohttp client: {e}")

            try:
                self.data.save(now=True)
            except Exception as e:
                log.exception(f"Exception in save data: {e}")

        finally:
            pending = [
                t for t in asyncio.all_tasks(loop=self.loop)
                if t is not asyncio.current_task(loop=self.loop) and not t.done()
            ]
            log.debug("Stopping %s tasks", len(pending))
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except (Exception,):
                    log.warning("Failed to cancel pending task", exc_info=True)

    async def _empty(self):
        while True:
            await asyncio.sleep(1)

    def _signals(self):
        def on_signal(s, _):
            log.debug("received %s signal", s)
            self.loop.create_task(self.shutdown())

        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGTERM, on_signal)

    def _loggers(self):
        root = logging.getLogger("dncore")
        if root.handlers:
            return

        root.setLevel(-1)

        prefix = "{log_color}[\033[90m{asctime}{log_color}] " \
                 "\033[90m{lineno:4} {log_color}| " \
                 "\033[90m{logname} {log_color}"

        orig_sys_stderr = sys.stderr  # by colorama
        sys.stdout = RedirectStream(sys.stdout, logging.getLogger("dncore.stdout-redirect").info)
        sys.stderr = RedirectStream(sys.stderr, logging.getLogger("dncore.stderr-redirect").error)

        sh = AppStreamLoggerHandler(stream=orig_sys_stderr)
        sh.addFilter(PackageNameInserter())
        # noinspection PyTypeChecker
        sh.setFormatter(colorlog.LevelFormatter(
            fmt=dict(DEBUG=f"{prefix}| D: {{message}}",
                     INFO=f"{prefix}| I: {{message}}",
                     WARNING=f"{prefix}| W: {{message}}",
                     ERROR=f"{prefix}| E: {{message}}",
                     CRITICAL=f"{prefix}| E: {{message}}"),
            log_colors=dict(DEBUG="purple", INFO="white", WARNING="yellow", ERROR="red", CRITICAL="red"),
            datefmt="%H:%M:%S", style="{", reset=True))
        root.addHandler(sh)

        fh = AppFileLoggerHandler("logs/latest.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            fmt="[{asctime}/{levelname}/{name}/{lineno}] {message}",
            datefmt="%Y-%m-%d/%H:%M:%S", style="{"))
        root.addHandler(fh)

    def _intents(self):
        intent_value = self._default_intents

        # by plugins
        for plugin in self.plugins.plugins.instances:
            intent_value |= plugin.use_intents

        # by config force
        force_intent = self.config.discord.force_intents
        for i_name in re.split("[, ]", force_intent):
            if i_name.lower() == "all":
                return discord.Intents.all().value

            i_value = discord.Intents.VALID_FLAGS.get(i_name.lower())
            if i_value:
                intent_value |= i_value
            elif i_name:
                log.warning(f"Unknown intent name: {i_name}")

        return discord.Intents(**{k: True for k, v in discord.Intents.VALID_FLAGS.items() if intent_value & v})

    def update_logger_level(self):
        logger = logging.getLogger("dncore")

        print_level = logging.getLevelName(self.config.logging.print_level.upper() or "INFO")
        if isinstance(print_level, str):
            print_level = logging.INFO

        file_level = logging.getLevelName(self.config.logging.file_level.upper() or "INFO")
        if isinstance(file_level, str):
            file_level = logging.INFO

        log.debug(f"Set logging level: print=%s, file=%s",
                  logging.getLevelName(print_level), logging.getLevelName(file_level))

        for handler in filter(lambda h: isinstance(h, AppStreamLoggerHandler), logger.handlers):
            handler.setLevel(print_level)

        for handler in filter(lambda h: isinstance(h, AppFileLoggerHandler), logger.handlers):
            handler.setLevel(file_level)

        for mod_name, level_name in self.config.logging.modules_level.items():
            if level_name:
                level = logging.getLevelName(level_name.upper())
                if isinstance(level, str):
                    log.warning(f"Unknown logging level: {level!r} (name: {mod_name})")
                else:
                    logging.getLogger(mod_name).setLevel(level)

    def register_activities(self):
        self.activity_manager.unregister_activity(owner=self)
        self.conn_act = None

        act_cnf = self.config.discord.activities.connecting
        if act_cnf:
            self.conn_act = act_cnf.create(1000)

        act_cnf = self.config.discord.activities.ready
        if act_cnf:
            act = act_cnf.create(0)
            self.activity_manager.register_activity(self, act)

    @property
    def connected_client(self):
        return self.client if self.client and self.client.is_ready() else None

    async def connect(self, *, reconnect=True, fail_to_shutdown=False):
        if self.client is not None and not reconnect:
            return

        token = self.config.discord.token
        if not token:
            log.warning("Discord token is empty")
            return

        try:
            first = True
            reconnect_delay = 1
            while True:
                await self.disconnect()

                if self.conn_act:
                    _activity = self.conn_act.get_formatted_activity()
                    _status = self.conn_act.status
                else:
                    _activity = None
                    _status = None

                self.client = DiscordClient(
                    loop=self.loop,
                    config=self.config.discord,
                    intents=self._intents(),
                    status=_status,
                    activity=_activity,
                )

                await call_event(DiscordInitializeEvent(self.client))

                try:
                    await self.client.login(token=token)

                except discord.DiscordServerError as e:
                    reconnect_delay = reconnect_delay * 2
                    if reconnect_delay > 900:
                        reconnect_delay = 900

                    if first:
                        first = False
                        log.warning(e)

                    log.warning(f"DiscordServerError, reconnect attempt in {reconnect_delay}s")
                    await asyncio.sleep(reconnect_delay)
                    continue

                break

        except Exception:
            try:
                await self.disconnect()
            except Exception as e:
                log.warning(f"Error in cancel login: {e}")
            raise

        async def _connect():
            try:
                await self.client.connect()

            except discord.DiscordException as ex:
                log.error(f"Error in connect to Discord:")
                log.error(str(ex))
            except asyncio.CancelledError:
                pass
            except Exception as ex:
                log.exception(f"Error in connect to Discord: {str(ex)}")
            else:
                return

            if fail_to_shutdown:
                await self.shutdown()

        self.loop.create_task(_connect())

    async def disconnect(self):
        if self.client is None:
            return

        await call_event(DiscordClosingEvent(self.client))

        try:
            await self.client.close()
            self.client.clear()
            self.client = None
        finally:
            await asyncio.sleep(1)

    def _on_connect(self, future: asyncio.Future):
        ex = future.exception()
        if isinstance(ex, discord.DiscordException):
            log.error(f"Error in connect to Discord:")
            log.error(str(ex))
        elif ex:
            log.error(f"Error in connect to Discord: {str(ex)}", exc_info=ex)

    def __del__(self):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__


class DNCoreAPI:
    @classmethod
    def command_prefix(cls):
        return get_core().config.discord.command_prefix

    @classmethod
    def owner_id(cls):
        return get_core().config.discord.owner_id

    @classmethod
    def version(cls):
        return version_info

    @classmethod
    def loop(cls):
        return get_core().loop

    @classmethod
    def core(cls) -> DNCore:
        return get_core()

    @classmethod
    def plugins(cls) -> PluginManager:
        return get_core().plugins

    @classmethod
    def commands(cls) -> CommandManager:
        return get_core().commands

    @classmethod
    def default_commands(cls) -> DNCoreCommands:
        return get_core().default_commands

    @classmethod
    def events(cls) -> EventManager:
        return get_core().events

    @classmethod
    def client(cls) -> DiscordClient | None:
        return get_core().connected_client

    @classmethod
    def aiohttp(cls) -> aiohttp.ClientSession:
        return get_core().aio

    @classmethod
    def appconfig(cls) -> AppConfig:
        return get_core().config

    @classmethod
    def get_plugin(cls, name: str) -> Plugin | None:
        return get_core().plugins.get_plugin(name)

    @classmethod
    def get_plugin_info(cls, name: str) -> PluginInfo | None:
        return get_core().plugins.get_plugin_info(name)

    @classmethod
    def call_event(cls, event: T) -> asyncio.Task[T]:
        mgr = get_core().events
        return mgr.loop.create_task(mgr.call_event(event))

    @classmethod
    def run_coroutine(cls, coro: T, ignores: Sequence[type[Exception]] = None) -> asyncio.Task[T]:
        __ignore_frame = IGNORE_FRAME
        loop = get_core().loop

        if ignores is None:
            ignores = Exception

        async def _wrap():
            try:
                return await coro
            except ignores:
                return
            except (Exception,):
                get_caller_logger().exception(f"Exception in run_coroutine : {coro}")

        return loop.create_task(_wrap())


get_core: Callable[[], DNCore]


def _core(core):
    if locals().get("get_core"):
        raise RuntimeError("already instanced")
    global get_core

    def get_core_():
        return core

    get_core = get_core_


class AppStreamLoggerHandler(logging.StreamHandler):
    pass


class AppFileLoggerHandler(DaysRotatingFileHandler):
    pass
