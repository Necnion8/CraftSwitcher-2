import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from dncore.extensions.craftswitcher import abc

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess


class Server(BaseModel):
    id: str
    name: str | None
    type: abc.ServerType
    state: abc.ServerState
    directory: str
    is_loaded: bool

    @classmethod
    def create(cls, server: "ServerProcess"):
        return cls(
            id=server.id,
            name=server.config.name,
            type=server.config.type,
            state=server.state,
            directory=str(server.directory),
            is_loaded=True,
        )

    @classmethod
    def create_no_data(cls, server_id: str, directory: str):
        return cls(
            id=server_id,
            name=None,
            type=abc.ServerType.UNKNOWN,
            state=abc.ServerState.UNKNOWN,
            directory=directory,
            is_loaded=False,
        )


class ServerOperationResult(BaseModel):
    result: bool
    server_id: str

    @classmethod
    def success(cls, server: "str | ServerProcess"):
        return cls(result=True, server_id=server if isinstance(server, str) else server.id)


class CreateServerParam(BaseModel):
    class LaunchOption(BaseModel):
        java_executable: str | None
        java_options: str | None
        jar_file: str
        server_options: str | None
        max_heap_memory: int | None
        min_heap_memory: int | None
        enable_free_memory_check: bool | None
        enable_reporter_agent: bool | None

    name: str | None
    directory: str
    type: abc.ServerType
    launch_option: LaunchOption
    enable_launch_command: bool = False
    launch_command: str = ""
    stop_command: str | None
    shutdown_timeout: int | None


class AddServerParam(BaseModel):
    directory: str


class ServerConfig(BaseModel):
    name: str | None = None
    type: abc.ServerType | None = None
    launch_option__java_executable: str | None = None
    launch_option__java_options: str | None = None
    launch_option__jar_file: str | None = None
    launch_option__server_options: str | None = None
    launch_option__max_heap_memory: int | None = None
    launch_option__min_heap_memory: int | None = None
    launch_option__enable_free_memory_check: bool | None = None
    launch_option__enable_reporter_agent: bool | None = None
    enable_launch_command: bool | None = None
    launch_command: str | None = None
    stop_command: str | None = None
    shutdown_timeout: int | None = None
    created_at: datetime.datetime | None = None
    last_launch_at: datetime.datetime | None = None
    last_backup_at: datetime.datetime | None = None

    class Config:
        @staticmethod
        def alias_generator(key: str):
            return key.replace("__", ".")


class ServerGlobalConfig(BaseModel):
    launch_option__java_executable: str = "java"
    launch_option__java_options: str = "-Dfile.encoding=UTF-8"
    launch_option__server_options: str = "--nogui"
    launch_option__max_heap_memory: int = 2048
    launch_option__min_heap_memory: int = 2048
    launch_option__enable_free_memory_check: bool = True
    launch_option__enable_reporter_agent: bool = True
    shutdown_timeout: int = 30

    class Config:
        @staticmethod
        def alias_generator(key: str):
            return key.replace("__", ".")
