import asyncio
import asyncio.subprocess as subprocess
import logging
import os
import shlex
import signal
import sys
import threading
import time
from functools import partial
from pathlib import Path
from typing import Awaitable
from typing import Callable

from . import errors
from .abc import ServerState
from .config import ServerConfig, ServerGlobalConfig
from .event import *
from .utils import *

_log = logging.getLogger(__name__)


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

        self.wrapper = None  # type: ProcessWrapper | None
        self._state = ServerState.STOPPED
        self._perf_mon = None  # type: ProcessPerformanceMonitor | None
        #
        self.shutdown_to_restart = False

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
    def players(self) -> list:
        return list()  # TODO: impl players

    @property
    def perfmon(self) -> "ProcessPerformanceMonitor | None":
        return self._perf_mon

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
        data = data.lstrip()
        self.log.info(f"[OUTPUT]: {data!r}")

        if data:
            call_event(ServerProcessReadEvent(self, data))  # イベント負荷を要検証

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

    # noinspection PyMethodMayBeStatic
    async def _start_subprocess(
            self, args: list[str], term_size: tuple[int, int],
            *, read_handler: Callable[[str], Awaitable[None]],
    ):
        return await PtyProcessWrapper.spawn(
            args=args,
            cwd=self.directory,
            term_size=term_size,
            read_handler=read_handler,
        )

    async def start(self):
        if self._is_running:
            raise errors.AlreadyRunningError

        self.log.info(f"Starting {self.id} server process")
        _event = await call_event(ServerPreStartEvent(self))
        if _event.cancelled:
            raise errors.OperationCancelledError(_event.cancelled_reason or "Unknown Reason")

        def _end(_):
            ret_ = wrapper.exit_status
            self.log.info("Stopped server process (ret: %s)", ret_)
            self.state = ServerState.STOPPED
            self._perf_mon = None

        try:
            if not self.check_free_memory():
                raise errors.OutOfMemoryError

            args = await self._build_arguments()

            wrapper = self.wrapper = await self._start_subprocess(args, term_size=(80, 25), read_handler=self._term_read)
            self.loop.create_task(wrapper.wait()).add_done_callback(_end)
            try:
                await asyncio.wait_for(wrapper.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            self.log.exception("Exception in pre start", exc_info=e)
            raise errors.ServerLaunchError from e

        ret = wrapper.exit_status
        if ret is None:
            self.state = ServerState.RUNNING

        else:
            self.log.warning("Exited process: return code: %s", ret)
            raise errors.ServerLaunchError(f"Failed to launch: process exited {ret}")

        try:
            self._perf_mon = ProcessPerformanceMonitor(wrapper.pid)
        except Exception as e:
            self.log.warning("Exception in init perf.mon", exc_info=e)

    async def send_command(self, command: str):
        if not self._is_running:
            raise errors.NotRunningError

        self.log.info(f"Sending command to {self.id} server: {command}")
        self.wrapper.write(command + "\n")  # TODO: 既に入力されているテキストを消さないといけない

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

    class WinPtyProcessWrapper(ProcessWrapper):
        def __init__(self, pid: int, cwd: Path, args: list[str], pty: winpty.PTY):
            super().__init__(pid, cwd, args)
            self.pty = pty

        @classmethod
        async def spawn(
                cls, args: list[str], cwd: Path, term_size: tuple[int, int],
                *, read_handler: Callable[[str], Awaitable[None]],
        ) -> "WinPtyProcessWrapper":
            pty = winpty.PTY(*term_size)
            # noinspection PyTypeChecker
            _appname: bytes = args[0]
            # noinspection PyTypeChecker
            _cmdline: bytes = shlex.join(args[1:])
            # noinspection PyTypeChecker
            _cwd: bytes = str(cwd)

            func = partial(pty.spawn, _appname, _cmdline, _cwd, )
            loop = asyncio.get_running_loop()

            if not loop.run_in_executor(None, func):
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
                    chunk = pty_read(1024 * 8, blocking=True)  # EOFにならず、ブロックし続ける。バグ？
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
                cls, args: list[str], cwd: Path, term_size: tuple[int, int],
                *, read_handler: Callable[[str], Awaitable[None]],
        ) -> "UnixPtyProcessWrapper":
            master, slave = pty.openpty()
            try:
                p = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=slave, stdout=slave, stderr=slave, cwd=cwd, close_fds=True,
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
