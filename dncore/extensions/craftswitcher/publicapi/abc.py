from enum import IntEnum, auto
from typing import TYPE_CHECKING

from fastapi import WebSocket, HTTPException

if TYPE_CHECKING:
    from ..abc import FileWatchInfo

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
        self.watch_files = dict()  # type: dict[str, FileWatchInfo]


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
    NO_SUPPORTED_ARCHIVE_FORMAT = auto()
    NO_AVAILABLE_DOWNLOAD = auto()

    # auth
    INVALID_AUTHENTICATION_CREDENTIALS = 400
    INCORRECT_USERNAME_OR_PASSWORD = auto()

    # user
    ALREADY_EXISTS_USER_NAME = 500
    NOT_EXISTS_USER = auto()

    # plugin
    PLUGIN_NOT_FOUND = 600
    NOT_EXISTS_PLUGIN_FILE = auto()

    # jardl
    NO_AVAILABLE_SERVER_TYPE = 700
    NOT_EXISTS_SERVER_VERSION = auto()
    NOT_EXISTS_SERVER_BUILD = auto()

    # backup
    BACKUP_ALREADY_RUNNING = 800

    def of(self, detail: str, status_code=400):
        return APIError(self, detail, status_code)


class APIError(HTTPException):
    def __init__(self, code: APIErrorCode, detail: str, status_code=400):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
