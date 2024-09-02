from enum import IntEnum

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
    OPERATION_CANCELLED = 101
    ALREADY_EXISTS_ID = 102

    # server
    SERVER_NOT_FOUND = 200
    SERVER_NOT_LOADED = 201
    SERVER_NOT_RUNNING = 202
    SERVER_LAUNCH_ERROR = 203
    SERVER_ALREADY_RUNNING = 204
    SERVER_PROCESSING = 205

    # file
    NOT_EXISTS_PATH = 300
    ALREADY_EXISTS_PATH = 301
    NOT_EXISTS_DIRECTORY = 302
    NOT_EXISTS_FILE = 303
    NOT_EXISTS_CONFIG_FILE = 304
    NOT_ALLOWED_PATH = 305
    NOT_FILE = 306

    def of(self, detail: str, status_code=400):
        return APIError(self, detail, status_code)


class APIError(HTTPException):
    def __init__(self, code: APIErrorCode, detail: str, status_code=400):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
