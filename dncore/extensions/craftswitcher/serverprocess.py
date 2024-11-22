import asyncio
import asyncio.subprocess as subprocess
import datetime
import logging
import os
import re
import shlex
import signal
import string
import sys
import threading
import time
from functools import partial
from pathlib import Path
from shutil import which
from typing import Awaitable, Any, Callable
from uuid import UUID

import psutil

from . import errors, utilscreen as screen
from .abc import ServerState
from .config import ServerConfig, ServerGlobalConfig, ReportModule as ReportModuleConfig
from .event import *
from .jardl import ServerBuilder, ServerBuildStatus
from .utiljava import JavaPreset
from .utils import *

_log = logging.getLogger(__name__)


class ServerProcess(object):
    class Config:
        class LaunchOption:
            def __init__(self, config: ServerConfig, global_config: ServerGlobalConfig):
                self._config = config.launch_option
                self._global_config = global_config.launch_option

            @property
            def java_preset(self) -> str:
                return [
                    self._config.java_preset,
                    self._global_config.java_preset,
                ][self._config.java_preset is None]

            @property
            def java_executable(self) -> str | None:
                return [
                    self._config.java_executable,
                    self._global_config.java_executable,
                ][self._config.java_executable is None]

            @property
            def java_options(self):
                return [
                    self._config.java_options,
                    self._global_config.java_options,
                ][self._config.java_options is None]

            @property
            def jar_file(self):
                return self._config.jar_file

            @property
            def server_options(self):
                return [
                    self._config.server_options,
                    self._global_config.server_options,
                ][self._config.server_options is None]

            @property
            def max_heap_memory(self):
                return [
                    self._config.max_heap_memory,
                    self._global_config.max_heap_memory,
                ][self._config.max_heap_memory is None]

            @property
            def min_heap_memory(self):
                return [
                    self._config.min_heap_memory,
                    self._global_config.min_heap_memory,
                ][self._config.min_heap_memory is None]

            @property
            def enable_free_memory_check(self):
                return [
                    self._config.enable_free_memory_check,
                    self._global_config.enable_free_memory_check,
                ][self._config.enable_free_memory_check is None]

            @property
            def enable_reporter_agent(self):
                return [
                    self._config.enable_reporter_agent,
                    self._global_config.enable_reporter_agent,
                ][self._config.enable_reporter_agent is None]

            @property
            def enable_screen(self) -> bool:
                return [
                    self._config.enable_screen,
                    self._global_config.enable_screen,
                ][self._config.enable_screen is None]

        def __init__(self, config: ServerConfig, global_config: ServerGlobalConfig):
            self._config = config
            self._global_config = global_config
            self._launch_option = ServerProcess.Config.LaunchOption(config, global_config)

        @property
        def name(self):
            return self._config.name

        @property
        def type(self):
            return self._config.type

        @property
        def launch_option(self):
            return self._launch_option

        @property
        def enable_launch_command(self):
            return self._config.enable_launch_command

        @property
        def launch_command(self):
            return self._config.launch_command

        @property
        def stop_command(self):
            return self._config.stop_command

        @property
        def shutdown_timeout(self):
            return [
                self._config.shutdown_timeout,
                self._global_config.shutdown_timeout,
            ][self._config.shutdown_timeout is None]

        @property
        def created_at(self):
            return self._config.created_at

        @property
        def last_launch_at(self):
            return self._config.last_launch_at

        @property
        def last_backup_at(self):
            return self._config.last_backup_at

        @property
        def last_backup_id(self):
            return self._config.last_backup_id

        @last_backup_id.setter
        def last_backup_id(self, backup_id: str | UUID | None):
            self._config.last_backup_id = backup_id.hex if isinstance(backup_id, UUID) else backup_id

    def __init__(
            self, loop: asyncio.AbstractEventLoop,
            directory: Path, server_id: str,
            config: ServerConfig, global_config: ServerGlobalConfig, repomo_config: ReportModuleConfig,
            *, max_logs_line: int = None,
    ):
        self.log = ServerLoggerAdapter(_log, server_id)
        self.loop = loop
        self._directory = directory
        self.id = server_id
        self._config = config
        self.config = ServerProcess.Config(config, global_config)
        self.repomo_config = repomo_config

        self.term_size = 200, 25
        self.wrapper = None  # type: ProcessWrapper | None
        self._state = ServerState.STOPPED
        self._perf_mon = None  # type: ProcessPerformanceMonitor | None
        self._builder = None  # type: ServerBuilder | None
        self._logs = self._create_logs_list(max_logs_line)
        self._process_pid = None  # type: int | None
        #
        self.shutdown_to_restart = False
        self._current_screen_name = None  # type: str | None
        self._detaching_screen = False

    @property
    def directory(self) -> Path:
        return self._directory

    @directory.setter
    def directory(self, new_dir: Path):
        if self._directory != new_dir:
            self.log.debug("Update directory: %s -> %s", self._directory, new_dir)
        self._directory = new_dir

    @property
    def builder(self):
        return self._builder

    @builder.setter
    def builder(self, new_builder: ServerBuilder | None):
        if self._builder is not new_builder:
            self.log.debug("Set builder: %s", new_builder)
        self._builder = new_builder

    @property
    def build_status(self) -> ServerBuildStatus | None:
        if self._builder:
            return self._builder.state

    @property
    def _is_running(self):
        return self.wrapper and self.wrapper.exit_status is None

    @property
    def state(self):
        if self._is_running:
            if self._state is ServerState.STOPPED:
                self.log.warning("Process is running but is marked as stopped. (bug?)")
        else:
            return ServerState.STOPPED
        return self._state

    @state.setter
    def state(self, value: ServerState):
        if not self._is_running and value.is_running:
            raise ValueError(f"Invalid state ({value.name}): process is not running")

        if value is self._state:
            return
        old_state, self._state = self._state, value
        self.log.info(f"Change state to {value} ({self.id})")
        call_event(ServerChangeStateEvent(self, old_state))

    @property
    def logs(self):
        return self._logs

    def _create_logs_list(self, max_lines: int = None):
        try:
            _old = self._logs
        except AttributeError:
            return Logs(maxlen=max_lines)
        _new = Logs(self._logs, maxlen=max_lines)
        _new._buffer = _old._buffer
        return _new

    @property
    def players(self) -> list:
        return list()  # TODO: impl players

    @property
    def perfmon(self) -> "ProcessPerformanceMonitor | None":
        return self._perf_mon

    @property
    def pid(self) -> int | None:
        return self._process_pid

    def check_free_memory(self) -> bool:
        if self.config.enable_launch_command and self.config.launch_command:
            # ignored
            return True

        if not self.config.launch_option.enable_free_memory_check:
            return True

        jar_max = self.config.launch_option.max_heap_memory

        mem = system_memory()
        mem_available = mem.available_bytes / (1024 ** 2)
        mem_total = mem.total_bytes / (1024 ** 2)
        required = jar_max * 1.25 + mem_total * 0.125
        self.log.debug(f"Memory check -> Available:{round(mem_available, 1):,}MB, Require:{round(required, 1):,}MB")
        return mem_available > required

    async def _term_read(self, data: str):
        if self.builder and self.builder.state == ServerBuildStatus.PENDING:
            try:
                await self.builder._read(data)
            except Exception as e:
                self.log.warning("Exception in builder.on_read", exc_info=e)

        if data:
            call_event(ServerProcessReadEvent(self, data))  # イベント負荷を要検証

            _lines = []
            for line in self._logs.put_data(data):
                _lines.append(line)
                self.log.debug(f"[OUTPUT]: {line!r}")
            if _lines:
                call_event(ServerProcessReadLinesEvent(self, _lines))  # イベント負荷を要検証

    async def _build_arguments(self):
        try:
            java_preset, java_executable = self.get_java()
        except errors.UnknownJavaPreset:
            raise
        except ValueError:
            self.log.warning("No java selected")
            java_executable = which("java") or "java"
            java_preset = None

        self.log.info("Java Info:")
        self.log.info("  Preset  :  %s", java_preset and java_preset.name or None)
        self.log.info("  Command :  %s", java_executable)
        if java_preset:
            if java_info := java_preset.info:
                self.log.info("  Version :  %s (%s)", java_info.runtime_version, java_info.vendor)
            else:
                self.log.warning("  Version :  No info")

        generated_arguments = False
        if self.config.enable_launch_command and self.config.launch_command:
            args = shlex.split(string.Template(self.config.launch_command).safe_substitute(
                JAVA_EXE=java_executable,
                JAVA_MEM_ARGS=f"-Xms{self.config.launch_option.min_heap_memory}M "
                              f"-Xmx{self.config.launch_option.max_heap_memory}M",
                JAVA_ARGS=self.config.launch_option.java_options,
                SERVER_ID=self.id,
                SERVER_JAR=self.config.launch_option.jar_file,
                SERVER_ARGS=self.config.launch_option.server_options,
            ))

        else:
            generated_arguments = True
            args = [
                java_executable,
                f"-Xms{self.config.launch_option.min_heap_memory}M",
                f"-Xmx{self.config.launch_option.max_heap_memory}M",
                *shlex.split(self.config.launch_option.java_options),
                "-D" + f"swi.serverName={self.id}",
                "-jar",
                self.config.launch_option.jar_file,
                *shlex.split(self.config.launch_option.server_options),
            ]

            if self.config.launch_option.enable_reporter_agent:
                agent_file = Path(self.repomo_config.agent_file)
                if agent_file.is_file():
                    for idx, part in enumerate(args):
                        if part == "-jar":
                            args.insert(idx, "-javaagent:" + str(agent_file.absolute()) + f"={self.id}")
                            break
                else:
                    self.log.warning("Agent file not exists: %s", agent_file)

        _event = await call_event(ServerLaunchOptionBuildEvent(self, args, is_generated=generated_arguments))
        return _event.args

    # noinspection PyMethodMayBeStatic
    async def _start_subprocess(
            self, args: list[str], cwd: Path, term_size: tuple[int, int], env: dict[str, Any] = None,
            *, read_handler: Callable[[str], Awaitable[None]],
    ):
        self.log.debug("directory: %s", str(cwd))
        self.log.debug("start process: %s", shlex.join(args))
        return await PtyProcessWrapper.spawn(
            args=args,
            cwd=cwd,
            term_size=term_size,
            env=env,
            read_handler=read_handler,
        )

    async def attach_to_screen_session(self, screen_name: str, *, ignore_status=False):
        """
        Screenセッションにアタッチし、サーバープロセスと連携を再開します。

        :except AlreadyRunningError: すでにプロセスが起動中
        :except ServerLaunchError: プロセスの接続に失敗した時
        """
        if not ignore_status and self._is_running:
            raise errors.AlreadyRunningError

        self.log.debug("Trying attach to screen session: %s", screen_name)
        call_event(ServerScreenAttachPreEvent(self, screen_name))
        self._process_pid = None
        self._detaching_screen = False
        builder = self.builder
        try:
            cwd = self.directory
            env = dict(os.environ)
            env["SWITCHER_SERVER_NAME"] = self.id

            args = screen.attach_commands(screen_name, force=True)

            wrapper = self.wrapper = await self._start_subprocess(
                args, cwd, term_size=self.term_size, env=env, read_handler=self._term_read)

            try:
                await asyncio.wait_for(wrapper.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            self.log.exception("Exception in attach screen", exc_info=e)
            raise errors.ServerLaunchError(str(e)) from e

        ret = wrapper.exit_status
        if ret is None:
            self.log.info("Reattached to screen session to %s", screen_name)
            self._current_screen_name = screen_name
            self.state = ServerState.RUNNING
            self.loop.create_task(self.handle_exit_process_reattach(wrapper, builder, screen_name))
            call_event(ServerScreenAttachEvent(self, screen_name, True))

        else:
            self.log.warning("Failed to attach: return code: %s", ret)
            call_event(ServerScreenAttachEvent(self, screen_name, False))
            raise errors.ServerLaunchError(f"Failed to attach: exited {ret}")

        pid = self._process_pid = wrapper.pid
        if self._current_screen_name and (w_pid := self.get_pid_from_screen(self._current_screen_name)) is not None:
            pid = self._process_pid = w_pid
        self.create_performance_monitor(pid)

    async def start(self, *, no_build=False, skip_memory_check=False, no_screen=False):
        """
        サーバーを起動します

        準備が完了しているビルダーが設定されている場合は、no_buildが真でない限りビルドを実行します

        :except AlreadyRunningError: すでにプロセスが起動中
        :except UnknownJavaPreset: 指定されたJavaプリセットが見つからない
        :except OperationCancelledError: イベントによって中止された
        :except OutOfMemoryError: 空きメモリテストに失敗した
        :except ServerLaunchError: サーバープロセスの起動に失敗した
        """
        if self._is_running:
            raise errors.AlreadyRunningError

        # check screen session
        screen_name = getinst().screen_session_name_of(self)
        if screen.is_available() and screen_name in screen.list_names():
            self.log.warning("Startup aborted: already running screen found")
            await self.attach_to_screen_session(screen_name)

        builder = self._builder
        if no_build:
            builder = None

        if builder:
            no_screen = True
            self.log.info("Starting build process")
            await call_event(ServerBuildPreStartEvent(self))
        else:
            self.log.info(f"Starting server process")
            _event = await call_event(ServerPreStartEvent(self))
            if _event.cancelled:
                raise errors.OperationCancelledError(_event.cancelled_reason or "Unknown Reason")

        self._process_pid = None
        self._current_screen_name = None
        self._detaching_screen = False
        try:
            cwd = self.directory
            env = dict(os.environ)
            env["SWITCHER_SERVER_NAME"] = self.id

            # Add java home to environ
            try:
                if (java_preset := self.get_java_preset()) and (java_info := java_preset.info):
                    if java_home_dir := java_info.java_home_path:
                        java_home_dir += os.sep + "bin"
                        env["PATH"] = java_home_dir + os.pathsep + env["PATH"]
                        self.log.debug("java path: %s", java_home_dir)
            except errors.UnknownJavaPreset:
                pass
            except Exception as e:
                self.log.warning(f"Exception in add to java home path to environ: {e}")

            if builder:
                params = ServerBuilder.Parameters(cwd, env)
                await builder._call(params)
                args = params.args
                env = params.env
                cwd = params.cwd

                if not args:
                    raise ValueError("Empty params.args")

            else:
                if not skip_memory_check and not self.check_free_memory():
                    raise errors.OutOfMemoryError
                args = await self._build_arguments()

            # wrap screen
            if not no_screen and self.config.launch_option.enable_screen:
                if screen.is_available():
                    self._current_screen_name = screen_name
                    args = [
                        *screen.new_session_commands(screen_name),
                        *args,
                    ]
                else:
                    self.log.warning("GNU Screen not available. (Ignored)")

            wrapper = self.wrapper = await self._start_subprocess(
                args, cwd, term_size=self.term_size, env=env, read_handler=self._term_read)
            if builder:
                builder.state = ServerBuildStatus.PENDING

            try:
                await asyncio.wait_for(wrapper.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

        except errors.UnknownJavaPreset as e:
            self.log.error(f"Failed to start server: Unknown Java preset: {e}")
            if builder:
                builder.state = ServerBuildStatus.FAILED
                await builder._error(e)
            raise

        except errors.ServerProcessError as e:
            self.log.exception(f"Failed to start server: {type(e).__name__}: {e}")
            if builder:
                builder.state = ServerBuildStatus.FAILED
                await builder._error(e)
            raise

        except Exception as e:
            self.log.exception("Exception in pre start", exc_info=e)
            if builder:
                builder.state = ServerBuildStatus.FAILED
                await builder._error(e)
            raise errors.ServerLaunchError(str(e)) from e

        ret = wrapper.exit_status
        if ret is None:
            self.state = ServerState.BUILD if builder else ServerState.RUNNING
            self.loop.create_task(self.handle_exit_process(wrapper, builder, screen_name))
            self._config.last_launch_at = datetime_now()
            self._config.save()

        else:
            if builder:
                builder.state = ServerBuildStatus.FAILED
            self.log.warning("Failed to start server: Exit code %s", ret)
            raise errors.ServerLaunchError(f"process exited {ret}")

        pid = self._process_pid = wrapper.pid
        if self._current_screen_name and (w_pid := self.get_pid_from_screen(self._current_screen_name)) is not None:
            pid = self._process_pid = w_pid
        self.create_performance_monitor(pid)

    async def send_command(self, command: str):
        if not self._is_running:
            raise errors.NotRunningError

        self.log.info(f"Sending command to {self.id} server: {command}")
        self.wrapper.write(command + "\r\n")  # TODO: 既に入力されているテキストを消さないといけない

    async def stop(self):
        if not self._is_running:
            raise errors.NotRunningError

        if self.state in (ServerState.STARTING, ServerState.STOPPING):
            raise errors.ServerProcessingError

        self.log.info(f"Stopping {self.id} server")

        command = self.config.stop_command or self.config.type.spec.stop_command or "stop"

        await self.send_command(command)
        self.shutdown_to_restart = False
        self._detaching_screen = False
        self.state = ServerState.STOPPING

    async def kill(self):
        if not self._is_running:
            raise errors.NotRunningError

        self.log.info(f"Killing {self.id} server process...")
        self.shutdown_to_restart = False
        self._detaching_screen = False

        if self._current_screen_name:
            screen.kill_screen(self._current_screen_name)
        else:
            self.wrapper.kill()

    async def wait_for_shutdown(self, *, timeout: int = None):
        if timeout is None:
            timeout = self.config.shutdown_timeout
        if timeout is None:
            timeout = 15

        start_at = time.time()
        while self._is_running:
            await asyncio.sleep(0.25)

            if timeout and (time.time() - start_at) > timeout:
                raise asyncio.TimeoutError

    async def restart(self):
        await self.stop()
        self.shutdown_to_restart = True

    async def clean_builder(self):
        if ServerState.BUILD == self.state:
            raise ValueError("Already running build")
        if self.builder:
            try:
                await self.builder._clean()
            except FileNotFoundError:
                pass
            finally:
                self.builder = None

    async def handle_exit_builder(self, builder: ServerBuilder, exit_code: int):
        result = await builder._exited(exit_code)
        self.log.info("Build Result: %s", result.name)
        if ServerBuildStatus.SUCCESS == result:
            if builder.apply_server_jar(self._config):
                if self.config.enable_launch_command:
                    self.log.debug("Updated config: '%s' (command)", self.config.launch_command)
                else:
                    self.log.debug("Updated config: %s", self.config.launch_option.jar_file)
            await asyncio.sleep(1)
            await self.clean_builder()

    async def handle_exit_process(self, proc: "ProcessWrapper", builder: ServerBuilder | None, screen_name: str):
        try:
            await proc.wait()
        finally:
            if self._detaching_screen:
                self.log.info("Detached screen")
                call_event(ServerScreenDetachedEvent(self, screen_name))
            else:
                # デタッチされた？時は再アタッチを試みる
                if screen.is_available() and screen_name in screen.list_names():
                    await asyncio.sleep(1)
                    await self.attach_to_screen_session(screen_name, ignore_status=True)
                    return

            ret_ = proc.exit_status
            self.log.info("Stopped %s process (ret: %s)", "build" if builder else "server", ret_)
            self.state = ServerState.STOPPED
            self._current_screen_name = None
            self._perf_mon = None

            if builder:
                await self.handle_exit_builder(builder, ret_)

    async def handle_exit_process_reattach(self, proc: "ProcessWrapper", builder: ServerBuilder | None, screen_name: str):
        try:
            await proc.wait()
        finally:
            if self._detaching_screen:
                self.log.info("Detached screen")
                call_event(ServerScreenDetachedEvent(self, screen_name))
            else:
                # デタッチされた？時は再アタッチを試みる
                if screen.is_available() and screen_name in screen.list_names():
                    await asyncio.sleep(1)
                    await self.attach_to_screen_session(screen_name, ignore_status=True)
                    return

            ret_ = 0  # screenから終了コードを得られないので常に 0 を設定
            self.log.info("Stopped server process (by screen session)")
            self.state = ServerState.STOPPED
            self._current_screen_name = None
            self._perf_mon = None

            # 常に正常終了したことにする。※ 通常はビルダーをscreenで実行されることはない
            if builder and builder.state.is_running():
                self.log.warning("builder was running in a screen session. (bug?)")
                await self.handle_exit_builder(builder, ret_)

    def create_performance_monitor(self, pid: int):
        try:
            self._perf_mon = mon = ProcessPerformanceMonitor(pid)
        except Exception as e:
            self.log.warning("Exception in init perf.mon", exc_info=e)
            mon = None
        return mon

    def get_perf_info(self):
        if self._perf_mon:
            try:
                return self._perf_mon.info()
            except psutil.NoSuchProcess:
                self._perf_mon = None
                self.log.warning("Failed to get performance info: No such process")
        return None

    def get_status_info(self):
        return getinst().get_server_status(self)

    def get_source_id(self, *, generate=True):
        source_id = self._config.source_id
        if source_id is None and generate:
            source_id = self._config.source_id = generate_uuid().hex
            self._config.save()
        return source_id

    def get_java_executable(self) -> str:
        """
        選択されているJavaプリセットや実行可能コマンドを返します

        設定されていない場合は常に 'java' になります
        """
        try:
            return self.get_java()[1]
        except errors.UnknownJavaPreset as e:
            self.log.warning(f"Unknown java preset: {e}")
            return "java"
        except ValueError:
            self.log.warning("No java selected")
            return "java"

    def get_java_preset(self) -> JavaPreset | None:
        """
        選択されているJavaプリセットを返します

        :except UnknownJavaPreset: 設定されたプリセットが見つからない
        """
        if preset_name := self.config.launch_option.java_preset:
            if preset := getinst().get_java_preset(preset_name):
                return preset
            raise errors.UnknownJavaPreset(preset_name)
        return None

    def get_java(self) -> tuple[JavaPreset | None, str]:
        """
        選択されているJavaプリセットと実行可能コマンドを返します

        :except UnknownJavaPreset: 設定されたプリセットが見つからない
        :except ValueError: Javaが選択されていない
        """
        if executable := self.config.launch_option.java_executable:
            executable = which(executable) or executable
            return None, executable

        if preset := self.get_java_preset():
            return preset, str(preset.path.absolute()) if preset.info else preset.executable

        raise ValueError("No java selected")

    # eula

    def is_eula_accepted(self, *, ignore_not_exists=False):
        """
        eula.txt の値を読み取り、結果を false/true で返します。

        :param ignore_not_exists: ファイルが存在していない場合は :class:`FileNotFoundError` を出さず、false を返します。
        """
        eula_path = self.directory / "eula.txt"
        if not eula_path.is_file():
            if ignore_not_exists:
                return False
            raise FileNotFoundError(eula_path)

        rex = re.compile(r"^eula *= *(.*)$", re.IGNORECASE)
        with eula_path.open("r") as f:
            for line in f:
                m = rex.match(line)
                if m and m.group(1).strip().lower() == "true":
                    return True
        return False

    def set_eula_accept(self, accept: bool) -> Path:
        """
        eula.txt に値を書き込みます。

        既存のファイルがある場合は、内容を維持しつつ値を変更するように試みます。
        """
        accept_text = ["false", "true"][accept]
        eula_path = self.directory / "eula.txt"
        lines = []

        # editing
        if eula_path.is_file():
            eula_path = self.directory / "eula.txt"
            rex = re.compile(r"^eula *= *(.*)$", re.IGNORECASE)
            with eula_path.open("r") as f:
                for line in f:
                    line = line.rstrip()
                    m = rex.match(line)
                    if m:
                        line = line[:m.start(1)] + accept_text
                    lines.append(line)

        # accept value
        if not lines:
            now = datetime.datetime.now().astimezone()
            lines.extend((
                "# https://aka.ms/MinecraftEULA",
                now.strftime("# Generated by CraftSwitcher (%Y/%m/%d %H:%M:%S)"),
                f"eula={accept_text}",
            ))

        if lines[-1]:
            lines.append("")  # 空行で終わらせる

        eula_path.write_text("\n".join(lines), encoding="utf-8")
        return eula_path

    # screen

    @property
    def screen_session_name(self):
        return self._current_screen_name

    async def detach_screen(self):
        if not self._is_running or not self._current_screen_name or self._current_screen_name not in screen.list_names():
            return False

        self.log.debug("detaching screen")
        self._detaching_screen = True
        try:
            self.wrapper.write("\001d")  # detach: Ctrl+A, D
        except Exception as e:
            self.log.warning(f"Exception in write detach command: {e}")
            return False
        return True

    @staticmethod
    def get_pid_from_screen(screen_name: str):
        if session := screen.get_screen(screen_name):
            try:
                proc = psutil.Process(session.pid).children()[-1]
            except psutil.NoSuchProcess:
                return
            except IndexError:
                return
            return proc.pid


class ServerProcessList(dict[str, ServerProcess | None]):
    def append(self, server: ServerProcess):
        if server.id in self:
            raise ValueError(f"Already exists server id: {server.id}")

        self[server.id] = server

    def remove(self, server: str | ServerProcess):
        if isinstance(server, ServerProcess):
            for key, value in self.items():
                if server is value:
                    return self.pop(key)

        else:
            return self.pop(server, None)

    def get(self, server_id: str) -> ServerProcess | None:
        if server_id is None:
            return None
        return dict.get(self, server_id.lower())


# wrapper


class ProcessWrapper:
    def __init__(self, pid: int, cwd: Path, args: list[str]):
        self._read_queue = asyncio.Queue()
        self.pid = pid
        self.cwd = cwd
        self.args = args

    @classmethod
    async def spawn(
            cls, args: list[str], cwd: Path, term_size: tuple[int, int],
            *, read_handler: Callable[[str], Awaitable[None]],
    ) -> "ProcessWrapper":
        raise NotImplementedError

    async def _loop_read_handler(self, read_handler: Callable[[str], Awaitable[None]]):
        while data := await self._read_queue.get():
            if data is EOFError:
                break
            try:
                await read_handler(data)
            except Exception as e:
                _log.exception("Exception in read_handler", exc_info=e)

    def write(self, data: str):
        raise NotImplementedError

    async def flush(self):
        raise NotImplementedError

    @property
    def exit_status(self) -> int | None:
        raise NotImplementedError

    async def wait(self) -> int:
        raise NotImplementedError

    def kill(self, sig: signal.Signals = signal.SIGTERM):
        os.kill(self.pid, sig)


if sys.platform == "win32":
    import winpty
    from subprocess import list2cmdline

    class WinPtyProcessWrapper(ProcessWrapper):
        def __init__(self, pid: int, cwd: Path, args: list[str], pty: winpty.PTY):
            super().__init__(pid, cwd, args)
            self.pty = pty

        @classmethod
        async def spawn(
                cls, args: list[str], cwd: Path, term_size: tuple[int, int], env: dict[str, Any] = None,
                *, read_handler: Callable[[str], Awaitable[None]],
        ) -> "WinPtyProcessWrapper":
            pty = winpty.PTY(*term_size)
            env = env or os.environ

            # noinspection PyTypeChecker
            _appname: bytes = which(args[0], path=env.get("PATH", os.defpath)) or args[0]
            # noinspection PyTypeChecker
            _cmdline: bytes = list2cmdline(args[1:])
            # noinspection PyTypeChecker
            _cwd: bytes = str(cwd)

            _env = ("\0".join([f"{k}={v}" for k, v in env.items()]) + "\0")

            func = partial(pty.spawn, _appname, _cmdline, _cwd, _env)
            loop = asyncio.get_running_loop()

            if not await loop.run_in_executor(None, func):
                raise RuntimeError("Unable to pty.spawn")

            wrapper = cls(pty.pid, cwd, args, pty)
            loop.create_task(wrapper._loop_read_handler(read_handler))
            # loop.run_in_executor(None, wrapper._loop_reader)
            threading.Thread(target=wrapper._loop_reader, daemon=True).start()  # ExecutorだとなぜかdnCoreが落ちない
            return wrapper

        def _loop_reader(self):
            pty_read = self.pty.read
            pty_isalive = self.pty.isalive
            queue_put = self._read_queue.put_nowait
            _decode = bytes.decode

            try:
                while pty_isalive():
                    try:
                        chunk = pty_read(1024 * 8, blocking=True)  # EOFにならず、ブロックし続ける。バグ？
                    except winpty.WinptyError as e:
                        if str(e).endswith("EOF"):
                            break
                        raise e
                    queue_put(chunk)
            except Exception as e:
                _log.exception("Exception in pty.read", exc_info=e)
            finally:
                queue_put(EOFError)

        def write(self, data: str):
            # noinspection PyTypeChecker
            self.pty.write(data)

        async def flush(self):
            pass

        @property
        def exit_status(self) -> int | None:
            return self.pty.get_exitstatus()

        async def wait(self) -> int:
            while self.pty.isalive():
                await asyncio.sleep(.1)
            return self.exit_status

    PtyProcessWrapper = WinPtyProcessWrapper

else:
    import pty

    class UnixPtyProcessWrapper(ProcessWrapper):
        def __init__(self, pid: int, cwd: Path, args: list[str], process: subprocess.Process, fd: int):
            super().__init__(pid, cwd, args)
            self.process = process
            self.fd = fd

        @classmethod
        async def spawn(
                cls, args: list[str], cwd: Path, term_size: tuple[int, int], env: dict[str, Any] = None,
                *, read_handler: Callable[[str], Awaitable[None]],
        ) -> "UnixPtyProcessWrapper":
            master, slave = pty.openpty()
            try:
                p = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env, close_fds=True, preexec_fn=os.setpgrp,
                )
            except Exception as e:
                raise RuntimeError("Unable to create_subprocess_exec") from e

            finally:
                os.close(slave)

            loop = asyncio.get_running_loop()

            wrapper = cls(p.pid, cwd, args, p, master)
            loop.create_task(wrapper._loop_read_handler(read_handler))
            loop.run_in_executor(None, wrapper._loop_reader)
            return wrapper

        def _loop_reader(self):
            fd = self.fd
            os_read = os.read
            queue_put = self._read_queue.put_nowait
            _decode = bytes.decode

            try:
                while True:
                    try:
                        data = os_read(fd, 1024 * 8)
                    except OSError:
                        break
                    queue_put(_decode(data, "utf-8", errors="ignore"))
            except Exception as e:
                _log.exception("Exception in os.read", exc_info=e)
            finally:
                queue_put(EOFError)

        def write(self, data: str):
            os.write(self.fd, data.encode("utf-8"))

        async def flush(self):
            pass

        @property
        def exit_status(self) -> int | None:
            return self.process.returncode

        async def wait(self) -> int:
            return await self.process.wait()

        def kill(self, sig: signal.Signals = signal.SIGTERM):
            self.process.send_signal(sig)

    PtyProcessWrapper = UnixPtyProcessWrapper
