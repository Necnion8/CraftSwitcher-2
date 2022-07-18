import asyncio
from asyncio import AbstractEventLoop
from typing import Any

import discord

from dncore.util import safe_format
from dncore.util.instance import get_core


class _BaseActivity(discord.BaseActivity):
    def __init__(self, kwargs):
        discord.BaseActivity.__init__(self, **kwargs)
        self.__kwargs = kwargs

    def to_dict(self):
        return self.__kwargs


class Activity(object):
    STANDBY = 0
    ACTIVE = 100

    def __init__(self, activity: discord.BaseActivity | str | None, priority: int = 100, status=discord.Status.online):
        if isinstance(activity, discord.BaseActivity):
            self.activity = activity
        elif activity is None:
            self.activity = None
        else:
            self.activity = discord.Game(name=activity)
        self.status = status
        self._priority = priority

    @property
    def priority(self):
        return self._priority

    @priority.setter
    def priority(self, value: int):
        self._priority = value
        self._mgr.update_priority()

    @property
    def _mgr(self):
        # noinspection PyProtectedMember
        inst = ActivityManager._inst
        if not inst:
            raise ValueError("ActivityManager has not initialized")
        return inst

    def update(self):
        self._mgr.update(self)

    def format_activity(self, args: dict[str, Any] = None):
        if self.activity:
            _activity = discord.BaseActivity()
            _data = self.activity.to_dict()

            _args = dict(
                prefix=get_core().config.discord.command_prefix or "",
                guilds=len(get_core().client.guilds) if get_core().client else 0,
            )
            if args:
                _args.update(args)

            if "name" in _data:
                _data["name"] = safe_format(_data["name"], _args)
            return _BaseActivity(_data)
        else:
            return None

    # noinspection PyMethodMayBeStatic
    def get_formatted_activity(self) -> discord.BaseActivity | None:
        return self.format_activity()


class ActivityManager(object):
    _inst = None  # type: ActivityManager | None

    def __init__(self, loop: AbstractEventLoop):
        ActivityManager._inst = self
        self.loop = loop
        self.handlers = {}  # type: dict[Activity, Any]  # status: owner
        self.priority_handlers = []  # type: list[Activity]
        self.current_handler = None  # type: Activity | None
        #
        self._update_task = None  # type: asyncio.Task | None
        self._queue = []  # type: list[tuple[discord.BaseActivity | None, discord.Status | None]]

    def cleanup(self):
        ActivityManager._inst = None
        self.handlers.clear()
        self.current_handler = None

        self._queue.clear()
        if self._update_task:
            self._update_task.cancel()
            self._update_task = None

    def register_activity(self, owner, activity: Activity):
        if activity not in self.handlers:
            self.handlers[activity] = owner
            self.priority_handlers.append(activity)
            self.update_priority()

    def unregister_activity(self, *, owner=None, activity: Activity = None):
        if owner is None and activity is None:
            raise ValueError("not specified owner or activity object")

        changed = False

        if owner is None:
            self.handlers.pop(activity, None)
            if activity in self.priority_handlers:
                self.priority_handlers.remove(activity)

            if self.current_handler is activity:
                self.current_handler = None
                changed = True

        else:
            for act, o in dict(self.handlers).items():
                if activity and activity is not act:
                    continue

                if owner is o:
                    self.handlers.pop(act)
                    if self.current_handler is act:
                        self.current_handler = None
                        changed = True
                    if act in self.priority_handlers:
                        self.priority_handlers.remove(act)

        if changed:
            self.update_priority()

    def update(self, activity: Activity | None):
        if self.current_handler is not activity:
            return False

        self.loop.create_task(self.change_presence(activity))
        return True

    def update_priority(self):
        self.priority_handlers.sort(reverse=True, key=lambda h: h.priority)
        high = self.priority_handlers[0] if self.priority_handlers else None
        if high and high.priority < 0:
            high = None
        self.current_handler = high
        self.update(high)

    async def change_presence(self, activity: Activity | None):
        _activity = None
        if activity:
            _activity = activity.get_formatted_activity()
            if not _activity:
                _activity = activity.format_activity()
        _status = activity.status if activity else None

        self._queue.append((_activity, _status))
        self.loop.create_task(self._update_presence())

    async def _update_presence(self):
        if not self.client:
            self._queue.clear()
            return

        if self._update_task and not self._update_task.done():
            return

        async def _change():
            if not self.client or not self._queue:
                self._update_task = None
                return

            activity, status = self._queue[-1]
            self._queue.clear()

            await self.client.change_presence(activity=activity, status=status)
            await asyncio.sleep(1)  # cool
            await _change()

        self._update_task = self.loop.create_task(_change())

    @property
    def client(self):
        client = get_core().client
        return client if client and client.is_ready() else None
