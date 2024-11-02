from typing import Optional, Dict, List
from uuid import UUID

from ..abc import ServerState


class SerializableData:
    def get_data_key(self) -> str:
        raise NotImplementedError

    def to_json(self) -> dict:
        raise NotImplementedError

    @classmethod
    def from_json(cls, data: dict):
        raise NotImplementedError


class EmptyResponseData(SerializableData):
    def get_data_key(self) -> str:
        return "empty-response"

    def to_json(self) -> dict:
        return {}

    @classmethod
    def from_json(cls, data: dict):
        return cls()


class InvalidData(SerializableData):
    def __init__(self, message: str):
        self.message = message

    def get_data_key(self) -> str:
        return "invalid"

    def to_json(self) -> dict:
        return dict(message=self.message)

    @classmethod
    def from_json(cls, data: dict):
        return cls(message=data["message"])


class StatusData(SerializableData):
    def __init__(self):
        self.tps: Optional[float] = None
        self.players: Optional[Dict[UUID, str]] = None
        self.max_players: Optional[int] = None
        self.cpu_usage: Optional[float] = None
        self.total_memory: Optional[int] = None
        self.free_memory: Optional[int] = None
        self.max_memory: Optional[int] = None

    def get_data_key(self) -> str:
        return "status"

    def to_json(self) -> dict:
        return dict(
            tps=self.tps,
            max_players=self.max_players,
            players={str(uuid): name for uuid, name in self.players.items()} if self.players is not None else None,
            cpu_usage=self.cpu_usage,
            total_memory=self.total_memory,
            free_memory=self.free_memory,
            max_memory=self.max_memory,
        )

    def to_api_json(self):
        return dict(
            players=dict(
                online=len(self.players) if self.players else 0,
                max=self.max_players or 0,
                ids=[dict(id=str(k), name=v) for k, v in self.players.items()] if self.players else [],
            ),
            performance=dict(
                tps=self.tps,
                cpu=dict(
                    usage=self.cpu_usage,
                ),
                memory=dict(
                    free=self.free_memory,
                    max=self.max_memory,
                    total=self.total_memory,
                )
            )
        )

    @classmethod
    def from_json(cls, data: dict):
        d = cls()
        d.tps = data.get("tps")
        d.max_players = data.get("max_players")
        players = data.get("players")
        if players is None:
            d.players = None
        else:
            d.players = {}
            for uuid_raw, player_name in players.items():
                try:
                    uuid = UUID(uuid_raw)
                except ValueError:
                    continue
                d.players[uuid] = player_name

        d.cpu_usage = data.get("cpu_usage")
        d.total_memory = data.get("total_memory")
        d.free_memory = data.get("free_memory")
        d.max_memory = data.get("max_memory")
        return d


class ServerStartRequest(SerializableData):
    def __init__(self):
        self.target_server: Optional[str] = None
        self.success = False
        self.fail_message: Optional[str] = None

    def get_data_key(self) -> str:
        return "server-start-request"

    def to_json(self) -> dict:
        return dict(
            target_server=self.target_server,
            success=self.success,
            fail_message=self.fail_message
        )

    @classmethod
    def from_json(cls, data: dict):
        request = cls()
        request.target_server = data.get("target_server")
        request.success = data.get("success")
        request.fail_message = data.get("fail_message")
        return request


class ServerStopRequest(SerializableData):
    def __init__(self):
        self.target_server: Optional[str] = None
        self.success = False
        self.fail_message: Optional[str] = None

    def get_data_key(self) -> str:
        return "server-stop-request"

    def to_json(self) -> dict:
        return dict(
            target_server=self.target_server,
            success=self.success,
            fail_message=self.fail_message
        )

    @classmethod
    def from_json(cls, data: dict):
        request = cls()
        request.target_server = data.get("target_server")
        request.success = data.get("success")
        request.fail_message = data.get("fail_message")
        return request


class ServerListRequest(SerializableData):
    def __init__(self):
        self.servers: Optional[List[str]] = None

    def get_data_key(self) -> str:
        return "server-list-request"

    def to_json(self) -> dict:
        return dict(servers=self.servers)

    @classmethod
    def from_json(cls, data: dict):
        request = cls()
        request.servers = data.get("servers")
        return request


class ServerRestartRequest(SerializableData):
    def __init__(self):
        self.target_server: Optional[str] = None
        self.success = False
        self.fail_message: Optional[str] = None

    def get_data_key(self) -> str:
        return "server-restart-request"

    def to_json(self) -> dict:
        return dict(
            target_server=self.target_server,
            success=self.success,
            fail_message=self.fail_message
        )

    @classmethod
    def from_json(cls, data: dict):
        request = cls()
        request.target_server = data.get("target_server")
        request.success = data.get("success")
        request.fail_message = data.get("fail_message")
        return request


class ServerChangeStateData(SerializableData):
    def __init__(self, server: str = None, state: ServerState = None):
        self.server: Optional[str] = server
        self.state: Optional[int] = state.old_value if state else None

    def get_data_key(self) -> str:
        return "server-change-state"

    def to_json(self) -> dict:
        return dict(
            server=self.server,
            state=self.state
        )

    @classmethod
    def from_json(cls, data: dict):
        return cls(
            server=data.get("server"),
            state=ServerState.of_old_value(data.get("state", -1)),
        )


class ServerStateRequest(SerializableData):
    def __init__(self, server: str, state: int = None):
        self.server = server
        self.state = state

    def get_data_key(self) -> str:
        return "server-state-request"

    def to_json(self) -> dict:
        return dict(
            server=self.server,
            state=self.state
        )

    @classmethod
    def from_json(cls, data: dict):
        return cls(data.get("server"))


class ServerAddData(SerializableData):
    def __init__(self, server: str):
        self.server = server

    def get_data_key(self) -> str:
        return "server-add"

    def to_json(self) -> dict:
        return dict(server=self.server)

    @classmethod
    def from_json(cls, data: dict):
        return cls(server=data["server"])


class ServerRemoveData(SerializableData):
    def __init__(self, server: str):
        self.server = server

    def get_data_key(self) -> str:
        return "server-remove"

    def to_json(self) -> dict:
        return dict(server=self.server)

    @classmethod
    def from_json(cls, data: dict):
        return cls(server=data["server"])


def get_data_class(key: str):
    if key == "invalid":
        return InvalidData
    elif key == "empty-response":
        return EmptyResponseData
    elif key == "status":
        return StatusData
    elif key == "server-start-request":
        return ServerStartRequest
    elif key == "server-stop-request":
        return ServerStopRequest
    elif key == "server-list-request":
        return ServerListRequest
    elif key == "server-restart-request":
        return ServerRestartRequest
    elif key == "server-change-state":
        return ServerChangeStateData
    elif key == "server-state-request":
        return ServerStateRequest
    return None
