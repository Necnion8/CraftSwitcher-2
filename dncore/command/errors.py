from dncore.command import CommandHandler

__all__ = [
    "CommandError",
    "CommandPermissionError",
    "CommandNotAllowedChannelTypeError",
    "CommandInternalError",
    "CommandInteractiveRunningError",
    "CommandCancelError",
    "CommandUsageError",
]


class CommandError(Exception):
    pass


class CommandPermissionError(CommandError):
    pass


class CommandNotAllowedChannelTypeError(CommandError):
    pass


class CommandInternalError(CommandError):
    def __init__(self, exception: Exception):
        self.exception = exception


class CommandInteractiveRunningError(CommandError):
    pass


class CommandCancelError(CommandError):
    pass


class CommandUsageError(CommandError):
    def __init__(self, command: str | CommandHandler = None):
        self.command = command
