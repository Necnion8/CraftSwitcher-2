import asyncio
import datetime
import functools
import logging
import platform
import re
import subprocess
from logging import getLogger
from pathlib import Path
from typing import TypeVar, TYPE_CHECKING, Any, MutableMapping, Callable, Awaitable

import psutil

from dncore import DNCoreAPI
from .abc import SystemMemoryInfo, ProcessInfo, SystemPerformanceInfo, JavaExecutableInfo, DiskUsageInfo

if TYPE_CHECKING:
    from .craftswitcher import CraftSwitcher

log = getLogger(__name__)
T = TypeVar("T")
IS_WINDOWS = platform.system() == "Windows"
__all__ = [
    "call_event",
    "is_windows",
    "system_memory",
    "system_perf",
    "disk_usage",
    "datetime_now",
    "safe_server_id",
    "check_java_executable",
    "get_java_home",
    "ProcessPerformanceMonitor",
    "ServerLoggerAdapter",
    "AsyncCallTimer",
    "getinst",
]


def call_event(event: T) -> asyncio.Task[T]:
    return DNCoreAPI.call_event(event)


def is_windows():
    return IS_WINDOWS


def system_memory(swap=False):
    mem = psutil.virtual_memory()
    if swap:
        swap = psutil.swap_memory()
        return SystemMemoryInfo(mem.total, mem.available, swap.total, swap.free)
    return SystemMemoryInfo(mem.total, mem.available)


def system_perf():
    # noinspection PyTypeChecker
    percent = psutil.cpu_percent(interval=None, percpu=True)  # type: list[float]
    return SystemPerformanceInfo(sum(percent), len(percent))


def disk_usage(path: str | Path):
    info = psutil.disk_usage(str(path))
    return DiskUsageInfo(info.total, info.used, info.free)


def datetime_now():
    return datetime.datetime.now(datetime.timezone.utc)


def safe_server_id(s: str):
    """
    サーバーIDとして正しい値に変換します
    """
    return s.lower().replace(" ", "_")


def parse_java_major_version(s: str):
    """
    "1.8" や "22.0.1" などのテキストからメジャーバージョンを出力します

    解析できない場合は -1 を返します
    """
    if s is None:
        return -1
    try:
        return int(s)
    except ValueError:
        pass
    m = re.search(r"^(\d+\.\d+)", s)
    if m:
        v = float(m.group(1))
        # eg. 17, 22 OR 1.8 -> 8
        return int(v) if 1 < int(v) else int(v * 10) % 10
    return -1


async def check_java_executable(path: Path) -> JavaExecutableInfo | None:
    path = path.resolve()
    p = await asyncio.create_subprocess_exec(
        path, "-XshowSettings:properties", "-version",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    java_home = str(path.parent.parent)

    if await p.wait() == 0:
        data_values = [
            ["java.specification.version =", None],
            ["java.home =", None],
            ["java.class.version =", None],
            ["java.runtime.version =", None],
            ["java.vendor =", None],
            ["java.vendor.version =", None],
        ]

        while line := await p.stdout.readline():
            line = line.strip().decode()
            for index, (prefix, value) in enumerate(data_values):
                if value is None and line.startswith(prefix):
                    value = line[len(prefix)+1:].strip()
                    data_values[index][1] = value
                    continue

        specification_version = data_values[0][1]
        java_home_path = data_values[1][1] or java_home
        runtime_version = data_values[3][1] or None

        java_major_version = parse_java_major_version(specification_version or runtime_version)

        return JavaExecutableInfo(
            executable=(Path(java_home_path) / "bin" / path.name).resolve(),
            specification_version=specification_version,
            java_home_path=java_home_path,
            java_major_version=java_major_version,
            class_version=float(data_values[2][1] or 0) or None,
            runtime_version=runtime_version,
            vendor=data_values[4][1] or None,
            vendor_version=data_values[5][1] or None,
        )

    p = await asyncio.create_subprocess_exec(
        path, "-version",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    match = None
    while line := await p.stdout.readline():
        line = line.strip().decode()
        m = re.search("version \"(.+)\"", line)
        if m:
            match = m

    if match:  # last
        runtime_version = match.group(1)
        return JavaExecutableInfo(
            executable=path,
            runtime_version=runtime_version,
            java_home_path=java_home,
            java_major_version=parse_java_major_version(runtime_version),
        )
    return None


async def get_java_home(exe_path: Path) -> str | None:
    info = await check_java_executable(exe_path)
    return info and info.java_home_path or None


class ProcessPerformanceMonitor(object):
    def __init__(self, pid: int):
        self.process = psutil.Process(pid)
        self.process.cpu_percent(interval=None)
        self.cached_info = None  # type: ProcessInfo | None

    def info(self):
        mem = self.process.memory_info()
        cpu_usage = self.process.cpu_percent(interval=None)
        self.cached_info = info = ProcessInfo(
            cpu_usage=cpu_usage,
            memory_used_size=mem.rss,
            memory_virtual_used_size=mem.vms,
        )
        return info


class ServerLoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger: logging.Logger, server_name: str):
        super().__init__(logger)
        self._server_name = server_name

    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        return f"[{self._server_name}] {msg}", kwargs


class AsyncCallTimer(object):
    RUNNING_TIMERS = set()  # type: set[AsyncCallTimer]

    @classmethod
    def cancel_all_timers(cls):
        for timer in set(cls.RUNNING_TIMERS):
            asyncio.create_task(timer.stop(cancel=True))

    def __init__(self, task: Callable[[], Awaitable[bool | None]], delay: float, period: float):
        self.task = task
        self.delay = delay
        self.period = period
        self._interrupt = False
        self._task = None  # type: asyncio.Task | None

    @property
    def is_running(self):
        return self._task and not self._task.done()

    async def start(self, *, restart=False):
        if self.is_running and not restart:
            return
        if self.is_running:
            await self.stop()

        self._interrupt = False
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self, *, cancel=False):
        self._interrupt = True
        if self._task:
            if cancel:
                self._task.cancel()
            try:
                await self._task
            except (Exception,):
                pass
        self._task = None

    async def _run(self):
        self.RUNNING_TIMERS.add(self)
        try:
            await asyncio.sleep(self.delay)
            while not self._interrupt:
                try:
                    ret = await self.task()
                except Exception as e:
                    log.warning("Exception in timer task:", exc_info=e)
                else:
                    if ret is False:
                        return

                if self._interrupt:
                    return
                await asyncio.sleep(self.period)
        finally:
            self.RUNNING_TIMERS.discard(self)

    @classmethod
    def create(cls, period: float, delay=0.0):
        def _wrap(func):
            @functools.wraps(func)
            async def wrapped(*args):
                return await func(*args)
            return cls(wrapped, delay, period)
        return _wrap


def getinst() -> "CraftSwitcher":
    from dncore.extensions.craftswitcher import CraftSwitcher
    try:
        return CraftSwitcher._inst
    except AttributeError:
        raise RuntimeError("CraftSwitcher is not instanced")
