
__all__ = [
    "ServerProcessError",
    "AlreadyRunningError",
    "OutOfMemoryError",
    "NotRunningError",
    "ServerLaunchError",
    "ServerProcessingError",
    "OperationCancelledError",
    "NoDownloadFile",
]


class ServerProcessError(Exception):
    pass


class AlreadyRunningError(ServerProcessError):
    pass


class OutOfMemoryError(ServerProcessError):
    pass


class NotRunningError(ServerProcessError):
    pass


class ServerLaunchError(ServerProcessError):
    pass


class ServerProcessingError(ServerProcessError):
    pass


class OperationCancelledError(ServerProcessError):
    pass


class NoDownloadFile(Exception):
    pass
