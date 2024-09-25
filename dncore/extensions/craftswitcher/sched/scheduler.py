import asyncio
import datetime
from typing import Self

from croniter import croniter

from ..database import model as db


# スケジュールタイミングを処理するクラスと、ラベルやアクションを設定する内部用のクラスをわける？


class Schedule:
    def __init__(self, label: str, description: str = None, *, sched_id: int = None):
        self.label = label
        self.description = description
        self.id = sched_id

    def get_distance(self, target: datetime.datetime) -> float:
        """
        target との時間差 (秒)
        """
        raise NotImplemented

    def serialize(self) -> db.Schedule:
        raise NotImplemented

    def _serialize(self, data) -> db.Schedule:
        return db.Schedule(id=self.id, label=self.label, description=self.description, data=data)

    @classmethod
    def deserialize(cls, model: db.Schedule) -> Self:
        raise NotImplemented

    @classmethod
    def schedule_type(cls) -> str:
        raise NotImplemented


class CronSchedule(Schedule):
    SCHED_TYPE = "cron"

    def __init__(self, label: str, description: str = None, *, sched_id: int = None,
                 cron_format: str, start_time: datetime.datetime = None):
        super().__init__(label, description, sched_id=sched_id)

        if start_time is None:
            start_time = datetime.datetime.now()

        self.cron_format = cron_format
        self.croniter = croniter(cron_format, start_time=start_time, max_years_between_matches=2)

    def get_distance(self, target: datetime.datetime) -> float:
        current = self.croniter.get_next(datetime.datetime, target)  # type: datetime.datetime
        return (current - target).total_seconds()

    def serialize(self) -> db.Schedule:
        return self._serialize(dict(
            cron_format=self.cron_format,
        ))

    @classmethod
    def deserialize(cls, model: db.Schedule) -> Self:
        return cls(
            model.label, model.description, sched_id=model.id,
            cron_format=model.data["cron_format"], start_time=None,
        )

    @classmethod
    def schedule_type(cls) -> str:
        return cls.SCHED_TYPE


class DatetimeSchedule(Schedule):
    SCHED_TYPE = "datetime"

    def __init__(self, label: str, description: str = None, *, sched_id: int = None,
                 target_datetime: datetime.datetime):
        super().__init__(label, description, sched_id=sched_id)

        self.target = target_datetime

    def get_distance(self, target: datetime.datetime) -> float:
        return (self.target - target).total_seconds()

    def serialize(self) -> db.Schedule:
        return self._serialize(dict(
            target=self.target.isoformat(),
        ))

    @classmethod
    def deserialize(cls, model: db.Schedule) -> Self:
        return cls(
            model.label, model.description, sched_id=model.id,
            target_datetime=datetime.datetime.fromisoformat(model.data["target"]),
        )

    @classmethod
    def schedule_type(cls) -> str:
        return cls.SCHED_TYPE


class Scheduler(object):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        pass
