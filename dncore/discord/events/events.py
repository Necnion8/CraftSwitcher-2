from typing import TYPE_CHECKING

import discord

from dncore.command import CommandContext, CommandHandler
from dncore.command.argument import Argument
from dncore.event import Event, Cancellable

if TYPE_CHECKING:
    from dncore.discord import DiscordClient

__all__ = ["DiscordInitializeEvent", "DiscordClosingEvent",
           "DebugCommandPreExecuteEvent", "HelpCommandPreExecuteEvent",
           ]


class DiscordInitializeEvent(Event):
    def __init__(self, client: "DiscordClient"):
        self._client = client

    @property
    def client(self) -> "DiscordClient":
        return self._client


class DiscordClosingEvent(Event):
    def __init__(self, client: "DiscordClient"):
        self._client = client

    @property
    def client(self) -> "DiscordClient":
        return self._client


class DebugCommandPreExecuteEvent(Event):
    def __init__(self, ctx: CommandContext, __globals: dict):
        self.context = ctx
        self.globals = __globals


class HelpCommandPreExecuteEvent(Event, Cancellable):
    def __init__(self, ctx: CommandContext, author: discord.User | discord.Member,
                 command: CommandHandler | None, name: str, args: Argument):
        self.context = ctx
        self.author = author
        self.command = command
        self.name = name
        self.args = args
