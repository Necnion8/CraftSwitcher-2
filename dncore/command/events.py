import discord

from dncore.command import CommandHandler, CommandContext
from dncore.command.errors import CommandError
from dncore.event import Event, Cancellable

__all__ = ["CommandRemapEvent", "CommandPreProcessEvent", "CommandProcessEvent", "CommandExceptionEvent",
           "CommandEmptyNameMessageEvent", "CommandUnknownMessageEvent"]


class CommandRemapEvent(Event):
    def __init__(self, command_count: int, aliases_count: int):
        self.command_count = command_count
        self.aliases_count = aliases_count


class CommandEvent:
    command: CommandHandler


class CommandPreProcessEvent(Event, Cancellable, CommandEvent):
    def __init__(self, message: discord.Message, prefix: str, command: CommandHandler | None,
                 execute_name: str, arguments: list[str]):
        self.message = message
        self.prefix = prefix
        self.command = command  # type: CommandHandler | None
        self.execute_name = execute_name
        self.arguments = arguments


class CommandProcessEvent(Event, CommandEvent):
    def __init__(self, context: CommandContext):
        self.message = context.message
        self.prefix = context.prefix
        self.command = context.command
        self.context = context


class CommandExceptionEvent(Event, Cancellable, CommandEvent):
    def __init__(self, context: CommandContext, error: CommandError, exception: Exception | None):
        self.context = context
        self.error = error
        self.command = context.command
        self.exception = exception


class CommandEmptyNameMessageEvent(Event, Cancellable):
    def __init__(self, message: discord.Message, prefix: str):
        self.message = message
        self.prefix = prefix


class CommandUnknownMessageEvent(Event, Cancellable):
    def __init__(self, message: discord.Message, prefix: str, execute_name: str, args: list[str]):
        self.message = message
        self.prefix = prefix
        self.execute_name = execute_name
        self.arguments = args
