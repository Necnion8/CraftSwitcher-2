import asyncio
import datetime
from logging import getLogger
from typing import TYPE_CHECKING

from .abc import ScheduleTimer, ScheduleAction, ScheduleTimerProvider, ScheduleActionProvider
from .actions import UnknownAction, ACTIONS
from .timers import UnknownTimer, TIMERS
from ..database import SwitcherDatabase, model as db
from ..utils import getinst

__all__ = [
    "ActionSchedule",
    "ScheduleManager",
]

if TYPE_CHECKING:
    from ..serverprocess import ServerProcess

log = getLogger(__name__)


class ActionSchedule(object):
    def __init__(self, schedule_id: int | None, label: str, description: str | None, server_id: str,
                 *, timer: ScheduleTimer, actions: list[ScheduleAction]):
        self.id = schedule_id
        self.label = label
        self.description = description
        self.server_id = server_id
        self.timer = timer
        self.actions = actions

    async def do_actions(self, server: "ServerProcess"):
        for action in self.actions:
            try:
                if not await action.do_action(server, self):
                    break
            except Exception as e:
                log.exception("Exception in do_action by schedule", exc_info=e)
                break


class ScheduleManager(object):
    def __init__(self, loop: asyncio.AbstractEventLoop, database: "SwitcherDatabase"):
        self.loop = loop
        self.db = database
        self._schedules: list[ActionSchedule] = []
        self._timer = None  # type: asyncio.Task | None
        self.timer_providers = dict(TIMERS)  # type: dict[str, ScheduleTimerProvider]
        self.action_providers = dict(ACTIONS)  # type: dict[str, ScheduleActionProvider]

    def update_timer(self):
        if not self._schedules:
            self.clear_timer()
            return

        log.debug("update timer")
        now = datetime.datetime.now()
        old_nearest = self._schedules[0]
        self._schedules.sort(key=lambda s: s.timer.get_distance(now))

        nearest = self._schedules[0]
        if nearest is old_nearest and self._timer and not self._timer.done():
            return
        self._start_timer()

    def clear_timer(self):
        if self._timer is None:
            return
        log.debug("clear timer")
        self._timer.cancel()
        self._timer = None

    async def _timer_call(self):
        try:
            while self._schedules:
                delay = self._schedules[0].timer.get_remaining()

                if delay <= 0:
                    self._on_time()
                    continue

                await asyncio.sleep(min(delay, 60))

        finally:
            self._timer = None

    def _start_timer(self):
        self.clear_timer()
        log.debug("start timer")
        self._timer = self.loop.create_task(self._timer_call())

    def _on_time(self):
        if not self._schedules:
            return

        log.debug("on time")
        servers = getinst().servers
        now = datetime.datetime.now() + datetime.timedelta(seconds=1)

        for schedule in self._schedules:
            if not schedule.timer.is_elapsed():
                continue

            schedule.timer.set_start_time(now)
            if server := servers.get(schedule.server_id):
                self.loop.create_task(schedule.do_actions(server))

    def create_timer(self, timer_id: str, data: dict) -> ScheduleTimer | None:
        try:
            provider = self.timer_providers[timer_id]
        except KeyError:
            return None
        log.debug("create timer: %s", timer_id)
        return provider.create(data)

    def create_action(self, action_id: str, data: dict) -> ScheduleAction | None:
        try:
            provider = self.action_providers[action_id]
        except KeyError:
            return None
        log.debug("create action: %s", action_id)
        return provider.create(data)

    #

    @property
    def schedules(self):
        return self._schedules

    def get_schedule(self, schedule_id: int):
        for schedule in self.schedules:
            if schedule_id == schedule.id:
                return schedule

    def get_server_schedules(self, server_id: str):
        return [schedule for schedule in self._schedules if schedule.server_id == server_id]

    async def add_schedule(self, timer: ScheduleTimer, actions: list[ScheduleAction],
                           *, server_id: str, label: str, description: str = None) -> ActionSchedule:
        schedule = ActionSchedule(None, label, description, server_id, timer=timer, actions=actions)

        schedule_id = await self.db.add_schedule(db.Schedule(
            id=None,  # auto
            server=server_id,
            label=label,
            description=description,
            timer_id=timer.id,
            timer_data=timer.to_database(),
        ), [db.ScheduleAction(
            schedule_id=None,  # auto
            index=index,
            id=a.id,
            data=a.to_database(),
        ) for index, a in enumerate(actions)])

        schedule.id = schedule_id
        self._schedules.append(schedule)
        self.update_timer()
        return schedule

    async def remove_schedule(self, schedule: ActionSchedule | int):
        schedule_id = schedule.id if isinstance(schedule, ActionSchedule) else schedule
        deleted = False
        for _schedule in list(self._schedules):
            if schedule_id == _schedule.id:
                self._schedules.remove(_schedule)
                deleted = True
        if deleted:
            self.update_timer()
        await self.db.remove_schedule(schedule_id)
        return deleted

    async def restore_from_database(self):
        ids = await self.db.get_schedule_ids()

        for schedule in self._schedules:
            if schedule.id in ids:
                ids.remove(schedule.id)

        if not ids:
            return

        for schedule_id in ids:
            if not (item := await self.db.get_schedule(schedule_id)):
                continue

            _schedule, _actions = item  # type: db.Schedule, list[db.ScheduleAction]
            try:
                if not (timer := self.create_timer(_schedule.timer_id, _schedule.timer_data)):
                    log.warning("Unknown schedule timer: %s", _schedule.timer_id)
                    timer = UnknownTimer(_schedule.timer_id, _extra=_schedule.timer_data)

                actions = []
                for _action in _actions:
                    if not (action := self.create_action(_action.id, _action.data)):
                        log.warning("Unknown schedule action: %s", _action.id)
                        action = UnknownAction(_action.id, _extra=_action.data)
                    actions.append(action)

                schedule = ActionSchedule(
                    _schedule.id, _schedule.label, _schedule.description, _schedule.server,
                    timer=timer, actions=actions,
                )
                self._schedules.append(schedule)

            except Exception as e:
                log.exception("Exception in restore schedule from database: id=%s", _schedule.id, exc_info=e)

        self.update_timer()
