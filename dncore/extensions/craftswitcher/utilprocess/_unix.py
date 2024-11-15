import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
from asyncio import subprocess as subprocess
from logging import getLogger
from pathlib import Path
from typing import Any, Callable, Awaitable

from . import ProcessWrapper

__all__ = [
    "UnixPtyProcessWrapper",
]
log = getLogger(__name__)


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
        wrapper.set_size(term_size)
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
            log.exception("Exception in os.read", exc_info=e)
        finally:
            queue_put(EOFError)

    def write(self, data: str):
        os.write(self.fd, data.encode("utf-8"))

    async def flush(self):
        pass

    def set_size(self, size: tuple[int, int]):
        """
        https://stackoverflow.com/a/6420070
        """
        winsize = struct.pack("HHHH", size[1], size[0], 0, 0)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)

    @property
    def exit_status(self) -> int | None:
        return self.process.returncode

    async def wait(self) -> int:
        return await self.process.wait()

    def kill(self, sig: signal.Signals = signal.SIGTERM):
        self.process.send_signal(sig)
