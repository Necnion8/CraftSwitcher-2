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


class OperationResult(BaseModel):
    result: bool
