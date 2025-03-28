import datetime

from croniter import croniter

from .abc import ScheduleTimer

__all__ = [
    "UnknownTimer",
    "CronScheduleTimer",
    "DatetimeScheduleTimer",
]


class UnknownTimer(ScheduleTimer):
    def __init__(self, timer_id: str):
        super().__init__(timer_id)
        self._data = {}

    def to_database(self) -> dict:
        return self._data

    def from_database(self, data: dict):
        self._data = data

    def get_remaining(self) -> float:
        return 365 * 24 * 60  # inf

    def is_elapsed(self):
        return False


class CronScheduleTimer(ScheduleTimer):
    def __init__(self, cron_format: str):
        super().__init__("cron")
        self.cron_format = cron_format
        self.croniter = croniter(cron_format, start_time=None, max_years_between_matches=2)

    def get_remaining(self) -> float:
        current = self.croniter.get_next(datetime.datetime, self.start_time)  # type: datetime.datetime
        return (current - self.start_time).total_seconds()

    def reschedule(self):
        self.croniter = croniter(self.cron_format, start_time=self.start_time, max_years_between_matches=2)

    def to_database(self) -> dict:
        return dict(cron_format=self.cron_format)

    def from_database(self, data: dict):
        self.cron_format = cron_format = data["cron_format"]
        self.croniter = croniter(cron_format, start_time=datetime.datetime.now(), max_years_between_matches=2)


class DatetimeScheduleTimer(ScheduleTimer):
    def __init__(self, target_datetime: datetime.datetime):
        super().__init__("datetime")
        self.target = target_datetime

    def get_remaining(self) -> float:
        return (self.target - self.start_time).total_seconds()

    def to_database(self) -> dict:
        return dict(target=self.target.astimezone(datetime.timezone.utc).timestamp())

    def from_database(self, data: dict):
        self.target = datetime.datetime.fromtimestamp(data["target"], datetime.timezone.utc)
