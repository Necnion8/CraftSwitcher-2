import asyncio
import datetime
from typing import Self

from croniter import croniter


class Schedule:
    def get_distance(self, target: datetime.datetime) -> float:
        """
        target との時間差 (秒)
        """
        raise NotImplemented

    def serialize(self) -> DB:
        raise NotImplemented

    @classmethod
    def deserialize(cls, model: DB) -> Self:
        raise NotImplemented

    @classmethod
    def schedule_type(cls) -> str:
        raise NotImplemented


class CronSchedule(Schedule):
    def __init__(self, cron_format: str, start_time: datetime.datetime = None):
        if start_time is None:
            start_time = datetime.datetime.now()

        self.cron_format = cron_format
        self.croniter = croniter(cron_format, start_time=start_time, max_years_between_matches=2)

    def get_distance(self, target: datetime.datetime) -> float:
        current = self.croniter.get_next(datetime.datetime, target)  # type: datetime.datetime
        return (current - target).total_seconds()


class DatetimeSchedule(Schedule):
    def __init__(self, target_datetime: datetime.datetime):
        self.target = target_datetime

    def get_distance(self, target: datetime.datetime) -> float:
        return (self.target - target).total_seconds()


class Scheduler(object):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        pass
