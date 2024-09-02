from enum import IntEnum, auto

from fastapi import WebSocket, HTTPException

__all__ = [
    "WebSocketClient",
    "APIError",
    "APIErrorCode",
]


class WebSocketClient(object):
    _id = 0

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.id = WebSocketClient._id
        WebSocketClient._id += 1


class APIErrorCode(IntEnum):
    # other
    OUT_OF_MEMORY = 100
    OPERATION_CANCELLED = auto()
    ALREADY_EXISTS_ID = auto()

    # server
    SERVER_NOT_FOUND = 200
    SERVER_NOT_LOADED = auto()
    SERVER_NOT_RUNNING = auto()
    SERVER_LAUNCH_ERROR = auto()
    SERVER_ALREADY_RUNNING = auto()
    SERVER_PROCESSING = auto()

    # file
    NOT_EXISTS_PATH = 300
    ALREADY_EXISTS_PATH = auto()
    NOT_EXISTS_DIRECTORY = auto()
    NOT_EXISTS_FILE = auto()
    NOT_EXISTS_CONFIG_FILE = auto()
    NOT_ALLOWED_PATH = auto()
    NOT_FILE = auto()

    def of(self, detail: str, status_code=400):
        return APIError(self, detail, status_code)


class APIError(HTTPException):
    def __init__(self, code: APIErrorCode, detail: str, status_code=400):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
