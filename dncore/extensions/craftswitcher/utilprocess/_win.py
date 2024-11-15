import asyncio
import os
import threading
from functools import partial
from logging import getLogger
from pathlib import Path
from shutil import which
from subprocess import list2cmdline
from typing import Any, Callable, Awaitable

import winpty

from . import ProcessWrapper

__all__ = [
    "WinPtyProcessWrapper",
]
log = getLogger(__name__)


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
            log.exception("Exception in pty.read", exc_info=e)
        finally:
            queue_put(EOFError)

    def write(self, data: str):
        # noinspection PyTypeChecker
        self.pty.write(data)

    async def flush(self):
        pass

    def set_size(self, size: tuple[int, int]):
        self.pty.set_size(size[0], size[1])

    @property
    def exit_status(self) -> int | None:
        return self.pty.get_exitstatus()

    async def wait(self) -> int:
        while self.pty.isalive():
            await asyncio.sleep(.1)
        return self.exit_status
