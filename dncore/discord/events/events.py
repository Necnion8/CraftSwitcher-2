from typing import TYPE_CHECKING

import discord

from dncore.command import CommandContext, CommandHandler
from dncore.command.argument import Argument
from dncore.event import Event, Cancellable

if TYPE_CHECKING:
    from dncore.discord import DiscordClient
    from dncore.plugin import Plugin

__all__ = ["DiscordInitializeEvent", "DiscordClosingEvent",
           "DebugCommandPreExecuteEvent", "HelpCommandPreExecuteEvent",
           "PreShutdownEvent", "SettingInfoCommandPreExecuteEvent",
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


class PreShutdownEvent(Event):
    def __init__(self):
        self._worker_messages = {}  # type: dict[Plugin, str]

    def set_message(self, owner: "Plugin", message: str):
        self._worker_messages[owner] = message

    def clear_message(self, owner: "Plugin"):
        self._worker_messages.pop(owner, None)

    @property
    def messages(self):
        return self._worker_messages


class SettingInfoCommandPreExecuteEvent(Event):
    LINE_TITLE_ICON = ":small_orange_diamond:"
    LINE_ICON = ":white_small_square:"

    def __init__(self, ctx: CommandContext, embed: discord.Embed):
        self.context = ctx
        self.__embed = embed
        self.extra = {}  # type: dict[Plugin, list[str]]
        self._override_embed = None  # type: discord.Embed | None

    @property
    def embed(self):
        return self.__embed

    @property
    def override_embed(self):
        return self._override_embed

    @override_embed.setter
    def override_embed(self, embed: discord.Embed):
        """
        最終的な :class:`discord.Embed` を上書きします
        """
        self._override_embed = embed

    def add_line(self, owner: "Plugin", line: str):
        try:
            lines = self.extra[owner]
        except KeyError:
            lines = self.extra[owner] = list()

        lines.append(line)

    def add_lines(self, owner: "Plugin", lines: list[str]):
        try:
            _lines = self.extra[owner]
        except KeyError:
            _lines = self.extra[owner] = list()

        _lines.extend(lines)

    def get_lines(self, owner: "Plugin") -> list[str] | None:
        try:
            return self.extra[owner]
        except KeyError:
            return None
