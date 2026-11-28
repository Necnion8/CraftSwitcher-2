from asyncio import Task
from typing import TypeVar, Sequence, Awaitable

__all__ = ["get_core", "get_plugin", "call_event", "run_coroutine"]

from dncore.util.logger import get_caller_logger

T = TypeVar("T")


def get_core():
    from dncore.dncore import get_core
    return get_core()


def get_plugin(name: str):
    return get_core().plugins.get_plugin(name)


def call_event(event: T) -> Task[T]:
    # cloned from DNCoreAPI
    from dncore.event import EventManager
    # noinspection PyProtectedMember
    mgr = EventManager._inst
    return mgr.loop.create_task(mgr.call_event(event))


def run_coroutine(coro: Awaitable[T], ignores: Sequence[type[Exception]] | None = None) -> Task[T]:
    # noinspection PyUnresolvedReferences,PyPep8Naming
    from dncore.abc import IGNORE_FRAME as __ignore_frame

    # cloned from DNCoreAPI
    loop = get_core().loop

    async def _wrap():
        try:
            return await coro
        except Exception as e:
            if not ignores or not isinstance(e, tuple(ignores)):
                get_caller_logger().exception(f"Exception in run_coroutine : {coro}", exc_info=e)

    return loop.create_task(_wrap())
