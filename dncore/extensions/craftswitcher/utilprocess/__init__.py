import asyncio
import os
import signal
import sys
from logging import getLogger
from pathlib import Path
from typing import Callable, Awaitable

log = getLogger(__name__)
__all__ = [
    "ProcessWrapper",
    "PtyProcessWrapper",
]


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
                log.exception("Exception in read_handler", exc_info=e)

    def write(self, data: str):
        raise NotImplementedError

    async def flush(self):
        raise NotImplementedError

    def set_size(self, size: tuple[int, int]):
        raise NotImplementedError

    @property
    def exit_status(self) -> int | None:
        raise NotImplementedError

    async def wait(self) -> int:
        raise NotImplementedError

    def kill(self, sig: signal.Signals = signal.SIGTERM):
        os.kill(self.pid, sig)


if sys.platform == "win32":
    from ._win import WinPtyProcessWrapper as PtyProcessWrapper
else:
    from ._unix import UnixPtyProcessWrapper as PtyProcessWrapper
