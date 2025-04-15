import datetime
from enum import IntEnum
from typing import TYPE_CHECKING

__all__ = [
    "Weeks",
    "ScheduleTimer",
    "ScheduleAction",
    "ScheduleTimerProvider",
    "ScheduleActionProvider",
]

if TYPE_CHECKING:
    from ..serverprocess import ServerProcess
    from .scheduler import ActionSchedule


class Weeks(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class ScheduleTimer:
    def __init__(self, timer_id: str):
        self.id = timer_id
        self.start_time = None  # type: datetime.datetime | None

    def to_database(self) -> dict:
        """
        データベースに保存する必要があるデータを返す
        """
        raise NotImplemented

    def get_remaining(self) -> float:
        """
        発火までの時間
        :return: 秒
        """
        raise NotImplemented

    def set_start_time(self, dt: datetime.datetime):
        self.start_time = dt
        self.reschedule()

    def reschedule(self):
        pass

    def is_elapsed(self):
        return self.get_remaining() <= 0


class ScheduleAction:
    def __init__(self, action_id: str):
        self.id = action_id

    def to_database(self) -> dict:
        """
        データベースに保存する必要があるデータを返す
        """
        raise NotImplemented

    async def do_action(self, server: "ServerProcess", schedule: "ActionSchedule") -> bool:
        """
        アクションを実行する
        :return: 実行に成功したら True を返す
        """
        raise NotImplemented


class ScheduleTimerProvider:
    def create(self, data: dict) -> ScheduleTimer:
        """
        データベースに保存されたデータから復元する
        """
        raise NotImplemented


class ScheduleActionProvider:
    def create(self, data: dict) -> ScheduleAction:
        """
        データベースに保存されたデータから復元する
        """
        raise NotImplemented
