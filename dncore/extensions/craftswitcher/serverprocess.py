import asyncio
import asyncio.subprocess as subprocess
import logging
import shlex
import signal
import time
from pathlib import Path
from typing import Any
from typing import Callable

from . import errors
from .abc import ServerState
from .config import ServerConfig, ServerGlobalConfig
from .event import *
from .utils import *

_log = logging.getLogger(__name__)


# noinspection PyMethodMayBeStatic
class ProcessReader:
    def subprocess_args(self, **kwargs) -> dict[str, Any]:
        raise NotImplemented

    async def loop_read(self, process: subprocess.Process):
        raise NotImplemented


class TextProcessReader(ProcessReader):
    def subprocess_args(self, **kwargs) -> dict[str, Any]:
        return dict(
            kwargs,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    async def loop_read(self, process: subprocess.Process):
        reader = process.stdout
        while line := await reader.readline():
            line = line.rstrip()
            _log.info(f"[OUTPUT] %s", line.decode("utf-8"))


class ServerProcess(object):
    class Config:
        class LaunchOption:
            def __init__(self, config: ServerConfig, global_config: ServerGlobalConfig):
                self._config = config.launch_option
                self._global_config = global_config.launch_option

            @property
            def java_executable(self):
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

    def __init__(
            self, loop: asyncio.AbstractEventLoop,
            directory: Path, server_id: str,
            config: ServerConfig, global_config: ServerGlobalConfig,
    ):
        self.log = ServerLoggerAdapter(_log, server_id)
        self.loop = loop
        self.directory = directory
        self.id = server_id
        self._config = config
        self.config = ServerProcess.Config(config, global_config)

        self.process_reader_type = TextProcessReader  # type: Callable[[], ProcessReader]
        self._state = ServerState.STOPPED
        self._process = None  # type: subprocess.Process | None
        self._perf_mon = None  # type: ProcessPerformanceMonitor | None
        self._process_read_loop_task = None  # type: asyncio.Task | None
        #
        self.shutdown_to_restart = False

    @property
    def process(self):
        return self._process

    @property
    def _is_running(self):
        return self.process and self.process.returncode is None

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
        self._state = value
        self.log.info(f"Change state to {value} ({self.id})")
        call_event(ServerChangeStateEvent(self, value))

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

    async def _process_read_loop(self, process: subprocess.Process, reader: ProcessReader):
        try:
            await reader.loop_read(process)
        finally:
            ret = await process.wait()
            self.log.info("Stopped server process (ret: %s)", ret)
            self.state = ServerState.STOPPED

    async def _build_arguments(self):
        generated_arguments = False
        if self.config.enable_launch_command and self.config.launch_command:
            args = shlex.split(self.config.launch_command)

        else:
            generated_arguments = True
            args = [
                self.config.launch_option.java_executable,
                f"-Xms{self.config.launch_option.min_heap_memory}M",
                f"-Xmx{self.config.launch_option.max_heap_memory}M",
                *shlex.split(self.config.launch_option.java_options),
                "-D" + f"swi.serverName={self.id}",
                "-jar",
                self.config.launch_option.jar_file,
                *shlex.split(self.config.launch_option.server_options),
            ]

            if self.config.launch_option.enable_reporter_agent:
                # TODO: add agent option
                pass

        _event = await call_event(ServerLaunchOptionBuildEvent(self, args, is_generated=generated_arguments))
        return _event.args

    async def _start_subprocess(self, args: list[str], reader: ProcessReader):
        return await subprocess.create_subprocess_exec(
            args[0], *args[1:], **reader.subprocess_args(
                cwd=self.directory,
                start_new_session=True,
            )
        )

    async def start(self):
        if self._is_running:
            raise errors.AlreadyRunningError

        if self._process_read_loop_task and not self._process_read_loop_task.done():
            try:
                await self._process_read_loop_task
            except (Exception,):
                pass

        self.log.info(f"Starting {self.id} server process")
        _event = await call_event(ServerPreStartEvent(self))
        if _event.cancelled:
            raise errors.OperationCancelledError(_event.cancelled_reason or "Unknown Reason")

        try:
            if not self.check_free_memory():
                raise errors.OutOfMemoryError

            args = await self._build_arguments()
            reader = self.process_reader_type()
            p = self._process = await self._start_subprocess(args, reader)

            self._process_read_loop_task = self.loop.create_task(self._process_read_loop(p, reader))
            try:
                await asyncio.wait_for(p.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            self.log.exception("Exception in pre start", exc_info=e)
            raise errors.ServerLaunchError from e

        if p.returncode is None:
            self.state = ServerState.RUNNING

        else:
            self.log.warning("Exited process: return code: %s", p.returncode)
            raise errors.ServerLaunchError(f"Failed to launch: process exited {p.returncode}")

        try:
            self._perf_mon = ProcessPerformanceMonitor(p.pid)
        except Exception as e:
            self.log.warning("Exception in init perf.mon", exc_info=e)

    async def send_command(self, command: str):
        if not self._is_running:
            raise errors.NotRunningError

        self.log.info(f"Sending command to {self.id} server: {command}")
        self._process.stdin.write(command.encode("utf-8") + b"\n")
        await self._process.stdin.drain()

    async def stop(self):
        if not self._is_running:
            raise errors.NotRunningError

        if self.state in (ServerState.STARTING, ServerState.STOPPING):
            raise errors.ServerProcessingError

        self.log.info(f"Stopping {self.id} server")

        command = self.config.stop_command or self.config.type.spec.stop_command or "stop"

        await self.send_command(command)
        self.shutdown_to_restart = False
        self.state = ServerState.STOPPING

    async def kill(self):
        if not self._is_running:
            raise errors.NotRunningError

        self.log.info(f"Killing {self.id} server process...")
        self._process.send_signal(signal.SIGKILL)

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
