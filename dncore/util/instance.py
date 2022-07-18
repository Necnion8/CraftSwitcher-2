from asyncio import Task
from typing import TypeVar, Sequence

__all__ = ["get_core", "get_plugin", "call_event", "run_coroutine"]

from dncore.util.logger import get_caller_logger

T = TypeVar("T")


def get_core():
    from dncore.dncore import get_core
    return get_core()


def get_plugin(name: str):
    return get_core().events.get_plugin(name)


def call_event(event: T) -> Task[T]:
    # cloned from DNCoreAPI
    from dncore.event import EventManager
    # noinspection PyProtectedMember
    mgr = EventManager._inst
    return mgr.loop.create_task(mgr.call_event(event))


def run_coroutine(coro: T, ignores: Sequence[type[Exception]] = None) -> Task[T]:
    # noinspection PyUnresolvedReferences,PyPep8Naming
    from dncore.abc import IGNORE_FRAME as __ignore_frame

    # cloned from DNCoreAPI
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
