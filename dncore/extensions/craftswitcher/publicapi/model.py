from typing import TYPE_CHECKING

from pydantic import BaseModel

from dncore.extensions.craftswitcher import abc

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess


class Server(BaseModel):
    id: str
    name: str | None
    state: abc.ServerState
    directory: str
    is_loaded: bool

    @classmethod
    def create(cls, server: "ServerProcess"):
        return cls(
            id=server.id,
            name=server.config.name,
            state=server.state,
            directory=str(server.directory),
            is_loaded=True,
        )

    @classmethod
    def create_no_data(cls, server_id: str, directory: str):
        return cls(
            id=server_id,
            name=None,
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

