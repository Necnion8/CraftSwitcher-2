from typing import TYPE_CHECKING

from .abc import ScheduleAction

__all__ = [
    "UnknownAction",
    "ServerStartAction",
    "ServerStopAction",
    "ServerRestartAction",
    "ServerCommandAction",
    "BackupAction",
]

if TYPE_CHECKING:
    from ..serverprocess import ServerProcess
    from .scheduler import ActionSchedule
    from ..files.abc import BackupType


class UnknownAction(ScheduleAction):
    def __init__(self, action_id: str):
        super().__init__(action_id)
        self._data = {}

    def to_database(self) -> dict:
        return self._data

    def from_database(self, data: dict):
        self._data = data

    async def do_action(self, server: "ServerProcess", schedule: "ActionSchedule") -> bool:
        return True


class ServerStartAction(ScheduleAction):
    def __init__(self):
        super().__init__("server_start")

    def to_database(self) -> dict:
        return {}

    def from_database(self, data: dict):
        pass

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if not server.state.is_running:
            await server.start(no_build=True)
        return True


class ServerStopAction(ScheduleAction):
    def __init__(self):
        super().__init__("server_stop")

    def to_database(self) -> dict:
        return {}

    def from_database(self, data: dict):
        pass

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if server.state.is_running:
            await server.stop()
            await server.wait_for_shutdown()
        return True


class ServerRestartAction(ScheduleAction):
    def __init__(self, *, only_running=False):
        super().__init__("server_restart")
        self.only_running = only_running

    def to_database(self) -> dict:
        return dict(
            only_running=self.only_running,
        )

    def from_database(self, data: dict):
        self.only_running = data["only_running"]

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if server.state.is_running:
            await server.restart()
        elif not self.only_running:
            await server.start(no_build=True)
        else:
            return False
        return True


class ServerCommandAction(ScheduleAction):
    def __init__(self, commands: list[str]):
        super().__init__("server_command")
        self.commands = commands

    def to_database(self) -> dict:
        return dict(
            commands=self.commands,
        )

    def from_database(self, data: dict):
        self.commands = data["commands"]

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if server.state.is_running:
            for command in self.commands:
                await server.send_command(command)
            return True
        return False


class BackupAction(ScheduleAction):
    def __init__(self, backup_type: BackupType, comments: str = None):
        super().__init__("backup")
        self.type = backup_type
        self.comments = comments

    def to_database(self) -> dict:
        return dict(
            type=self.type.name,
        )

    def from_database(self, data: dict):
        from ..files.abc import BackupType
        self.type = BackupType(data["type"])

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        from ..utils import getinst
        from ..files.abc import BackupType, FileTaskResult

        if server.state.is_running:
            await server.stop()

        backups = getinst().backups
        if backups.get_running_task_by_server(server):
            return False
        elif BackupType.SNAPSHOT == self.type and not backups.is_enabled_snapshot():
            return False

        if BackupType.SNAPSHOT == self.type:
            task = await backups.create_snapshot(server, comments=self.comments)
        else:
            task = await backups.create_full_backup(server, comments=self.comments)

        try:
            await task
        except (Exception,):
            return False
        else:
            return FileTaskResult.SUCCESS == task.result
