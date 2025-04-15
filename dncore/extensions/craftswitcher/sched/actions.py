from typing import TYPE_CHECKING

from .abc import ScheduleAction, ScheduleActionProvider

__all__ = [
    "UnknownAction",
    "ServerStartAction",
    "ServerStopAction",
    "ServerRestartAction",
    "ServerCommandAction",
    "BackupAction",
    "ACTIONS",
]

if TYPE_CHECKING:
    from ..serverprocess import ServerProcess
    from .scheduler import ActionSchedule
    from ..files.abc import BackupType


class UnknownAction(ScheduleAction):
    def __init__(self, action_id: str, *, _extra: dict):
        super().__init__(action_id)
        self._extra = _extra

    def to_database(self) -> dict:
        return self._extra

    async def do_action(self, server: "ServerProcess", schedule: "ActionSchedule") -> bool:
        return True


class ServerStartAction(ScheduleAction):
    def __init__(self):
        super().__init__("server_start")

    def to_database(self) -> dict:
        return {}

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if not server.state.is_running:
            await server.start(no_build=True)
        return True

    class Provider(ScheduleActionProvider):
        def create(self, data: dict) -> "ServerStartAction":
            return ServerStartAction()


class ServerStopAction(ScheduleAction):
    def __init__(self):
        super().__init__("server_stop")

    def to_database(self) -> dict:
        return {}

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if server.state.is_running:
            await server.stop()
            await server.wait_for_shutdown()
        return True

    class Provider(ScheduleActionProvider):
        def create(self, data: dict) -> "ServerStopAction":
            return ServerStopAction()


class ServerRestartAction(ScheduleAction):
    def __init__(self, *, only_running=False):
        super().__init__("server_restart")
        self.only_running = only_running

    def to_database(self) -> dict:
        return dict(
            only_running=self.only_running,
        )

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if server.state.is_running:
            await server.restart()
        elif not self.only_running:
            await server.start(no_build=True)
        else:
            return False
        return True

    class Provider(ScheduleActionProvider):
        def create(self, data: dict) -> "ServerRestartAction":
            return ServerRestartAction(only_running=data["only_running"])


class ServerCommandAction(ScheduleAction):
    def __init__(self, commands: list[str]):
        super().__init__("server_command")
        self.commands = commands

    def to_database(self) -> dict:
        return dict(
            commands=self.commands,
        )

    async def do_action(self, server: "ServerProcess", scheduled: "ActionSchedule") -> bool:
        if server.state.is_running:
            for command in self.commands:
                await server.send_command(command)
            return True
        return False

    class Provider(ScheduleActionProvider):
        def create(self, data: dict) -> "ServerCommandAction":
            return ServerCommandAction(data["commands"])


class BackupAction(ScheduleAction):
    def __init__(self, backup_type: "BackupType", comments: str = None):
        super().__init__("backup")
        self.type = backup_type
        self.comments = comments

    def to_database(self) -> dict:
        return dict(
            type=self.type.name,
            comments=self.comments,
        )

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

    class Provider(ScheduleActionProvider):
        def create(self, data: dict) -> "BackupAction":
            from ..files.abc import BackupType
            return BackupAction(BackupType(data["type"], data.get("comments") or None))


ACTIONS = {
    "server_start": ServerStartAction.Provider(),
    "server_stop": ServerStopAction.Provider(),
    "server_restart": ServerRestartAction.Provider(),
    "server_command": ServerCommandAction.Provider(),
    "backup": BackupAction.Provider(),
}  # type: dict[str, ScheduleActionProvider]
