import asyncio
import inspect
import logging
from collections import defaultdict
from enum import Enum
from typing import TypeVar, Callable, Awaitable

log = logging.getLogger(__name__)
T = TypeVar("T")
__all__ = ["Event", "Cancellable", "Priority", "EventHandler", "EventListener", "EventManager", "onevent"]


class Event:
    pass


class Cancellable:
    _cancelled: bool

    @property
    def cancelled(self):
        return getattr(self, "_cancelled", False)

    @cancelled.setter
    def cancelled(self, cancel: bool):
        setattr(self, "_cancelled", cancel)


class Priority(Enum):
    HIGHEST = 2
    HIGH = 1
    NORMAL = 0
    LOW = -1
    LOWEST = -2

    def __eq__(self, other):
        if not isinstance(other, Priority):
            raise NotImplemented
        return self.value == other.value

    def __lt__(self, other):
        if not isinstance(other, Priority):
            raise NotImplemented
        return self.value < other.value

    def __ne__(self, other):
        return not self.__eq__(other)

    def __le__(self, other):
        return self.__lt__(other) or self.__eq__(other)

    def __gt__(self, other):
        return not self.__le__(other)

    def __ge__(self, other):
        return not self.__lt__(other)


class EventHandler:
    def __init__(self, *, priority=Priority.NORMAL, monitor=False, ignore_cancelled=False, **kw):
        self.priority = priority
        self.monitor = monitor
        self.ignore_cancelled = ignore_cancelled
        self.func = None
        self.method = None
        self.other_keywords = kw

    def __call__(self, func: Callable[[Event], Awaitable[None]]):
        self.func = func
        func._handler = self
        return func


class EventListener:
    __handlers: dict[type[Event], list[EventHandler]]


class EventManager(object):
    _inst = None  # type: EventManager | None

    def __init__(self, loop: asyncio.AbstractEventLoop):
        EventManager._inst = self
        self.loop = loop
        self._listeners = defaultdict(list)  # type: dict[object, list[EventListener]] # (owner, listeners)
        self._handlers = defaultdict(list)  # type: dict[type[Event], list[EventHandler]] # (event, handlers)
        self._listener_handlers = dict()  # type: dict[EventListener, list[EventHandler]] # (listener, handlers)

    def register_listener(self, owner, listener: EventListener):
        if listener in self._listeners.values():
            return
        handlers = self._init_listener(listener)
        self._listeners[owner].append(listener)
        for e_type in handlers:
            self._handlers[e_type].extend(handlers[e_type])
        self._listener_handlers[listener] = [handler for _handlers in handlers.values() for handler in _handlers]

    def unregister_listener(self, listener: EventListener):
        for owner, listeners in dict(self._listeners).items():
            if listener in listeners:
                listeners.remove(listener)
            if not listeners:
                self._listeners.pop(owner)

        handlers = self._listener_handlers.pop(listener, [])
        for e_type, e_handlers in dict(self._handlers).items():
            for e_handler in list(e_handlers):
                if e_handler in handlers:
                    e_handlers.remove(e_handler)

            if not e_handlers:
                self._handlers.pop(e_type)

    def unregister_listeners(self, owner):
        for listener in list(self._listeners.pop(owner, [])):
            self.unregister_listener(listener)

    def cleanup(self):
        EventManager._inst = None
        self._listeners.clear()
        self._handlers.clear()
        self._listener_handlers.clear()

    @staticmethod
    def _init_listener(listener: EventListener):
        handlers = defaultdict(list)  # type: dict[type[Event], list[EventHandler]]

        for name, method in inspect.getmembers(listener, inspect.iscoroutinefunction):
            handler = getattr(method, "_handler", None)
            if isinstance(handler, EventHandler):
                handler.method = method
                sig = inspect.signature(method)
                params = sig.parameters
                if len(params) != 1:
                    log.error("イベントハンドラ %s.%s が無効な引数を受け取ります。", type(listener).__name__, name)
                    continue
                elif Event not in params[list(params.keys())[0]].annotation.mro():
                    log.error("イベントハンドラ %s.%s が無効な引数を受け取ります。", type(listener).__name__, name)
                    continue
                handlers[params[list(params.keys())[0]].annotation].append(handler)

                if handler.other_keywords:
                    log.warning("イベントハンドラ %s.%s に無効なオプションがあります: %s",
                                type(listener).__name__, name, ", ".join(handler.other_keywords.keys()))

        setattr(listener, "__handlers", handlers)
        return handlers

    async def call_event(self, event: T) -> T:
        handlers = list(self._handlers.get(type(event), []))  # type: list[EventHandler]
        handlers.sort(key=lambda h: h.priority)

        async def safe_call(hdl):
            try:
                await hdl.method(event)
            except (Exception,):
                listener_name = "None"
                for listener, listen_handlers in self._listener_handlers.items():
                    if hdl in listen_handlers:
                        listener_name = type(listener).__name__
                        break
                log.warning("イベント処理エラー (L: %s, E: %s)", listener_name, type(event).__name__, exc_info=True)

        monitors = []
        for handler in handlers:
            if handler.ignore_cancelled and getattr(event, "cancelled", False):
                continue
            if handler.monitor:
                monitors.append(safe_call(handler))
            else:
                await safe_call(handler)

        if monitors:
            self.loop.create_task(asyncio.gather(*monitors, loop=self.loop))

        return event


onevent = EventHandler
