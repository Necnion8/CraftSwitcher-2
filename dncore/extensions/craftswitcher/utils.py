import asyncio
import platform
from typing import TypeVar

import psutil

from dncore import DNCoreAPI
from dncore.extensions.craftswitcher.abc import SystemMemoryInfo, ProcessInfo

T = TypeVar("T")
IS_WINDOWS = platform.system() == "Windows"
__all__ = [
    "call_event",
    "system_memory",
    "ProcessPerformanceMonitor",
]


def call_event(event: T) -> asyncio.Task[T]:
    return DNCoreAPI.call_event(event)


def system_memory():
    mem = psutil.virtual_memory()
    return SystemMemoryInfo(mem.total, mem.available)


class ProcessPerformanceMonitor(object):
    def __init__(self, pid: int):
        self.process = psutil.Process(pid)
        self.process.cpu_percent(interval=None)

    def info(self):
        mem = self.process.memory_info()
        cpu_usage = self.process.cpu_percent(interval=None)
        if IS_WINDOWS:
            cpu_usage /= psutil.cpu_count()
        return ProcessInfo(
            cpu_usage=cpu_usage,
            memory_used_size=mem.rss,
            memory_used_total_size=mem.vms,
        )
