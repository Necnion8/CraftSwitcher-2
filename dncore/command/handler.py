import textwrap
from asyncio import Future
from typing import Callable, Awaitable, TYPE_CHECKING

import discord

from dncore.command import DEFAULT_DEFAULT_GROUP, DEFAULT_OWNER_GROUP
from dncore.command.argument import Argument
from dncore.util import safe_format
from dncore.util.discord import MessageSender, MessageableChannel
from dncore.util.instance import get_core, run_coroutine

__all__ = ["CommandHandler", "CommandContext"]

if TYPE_CHECKING:
    from dncore.discord.discord import DiscordClient


class CommandHandler:
    def __init__(self, name: str = None, *,
                 hid: str = None, interactive=False, clean_message=True,
                 defaults: str | bool | None = DEFAULT_OWNER_GROUP, aliases: str | list[str] = None,
                 category: str = None, allow_channels=discord.TextChannel):
        """
        :param name: コマンド名。省略して cmd_xxx から名前を設定
        :param hid: ハンドラID
        :param interactive: 対話動作コマンドかどうか。対話コマンド動作中は他のコマンドを実行できない
        :param clean_message: dnCore設定に基づき、メッセージを自動的に削除する
        :param defaults: デフォルトで有効にするグループ名。Trueで一般可
        :param aliases: デフォルトで登録する別名のリスト
        :param category: デフォルトで登録するカテゴリーID
        :param allow_channels: 実行できるチャンネルタイプ
        """
        self.func = None
        self.name = name  # type: str | None
        self.id = hid  # type: str
        self.usage = None  # type: str | None
        self.interactive = interactive
        self.clean_message = clean_message
        if defaults is True:
            self.allow_group = DEFAULT_DEFAULT_GROUP
        elif defaults is False:
            self.allow_group = None
        else:
            self.allow_group = defaults
        if isinstance(aliases, str):
            self.aliases = {aliases}  # type: set[str] | None
        elif aliases:
            self.aliases = set(aliases)
        else:
            self.aliases = None
        self.category = category
        self.allow_channels = allow_channels

    def __call__(self, func: Callable[[str], Awaitable[None]]):
        self.func = func
        func._handler = self
        if self.name is None:
            name = func.__name__
            name = name[4:] if name.startswith("cmd_") and len(name) > 4 else name
            self.name = name

        if self.id is None:
            hid = getattr(func, "__module__", None) or self.name
            if hid.startswith("dncore.extensions."):
                hid = hid.split(".")[2]
            self.id = hid + f".{self.name}"

        if self.usage is None and func.__doc__:
            self.usage = textwrap.dedent(func.__doc__)

        return func

    async def execute(self, ctx: "CommandContext"):
        raise NotImplementedError

    def format_usage(self, usage_text: str | None, command_prefix: str):
        if usage_text is None:
            usage_text = self.usage
        if not usage_text:
            raise ValueError("usage_text is empty!")

        usages = []
        arguments = []
        descriptions = []

        _arg = None
        _emp = False
        for line in usage_text.splitlines():
            _line = safe_format(line, dict(
                prefix=command_prefix,
                name=self.name,
                command=command_prefix + self.name,
            ))
            if _line.count("```") % 2:
                _emp = not _emp

            if line.startswith("{command}"):
                usages.append(_line)
            elif line.startswith("> "):
                if _arg:
                    arguments.append(_arg)
                _arg = (_line[2:], [])
            elif line or _emp:
                if _arg:
                    _arg[1].append(_line)
                else:
                    descriptions.append(_line)
        if _arg:
            arguments.append(_arg)

        description_text = list(descriptions)
        if usages:
            description_text.insert(0, "```\n" + "\n".join(usages) + "```")
        if description_text and arguments:
            description_text.append("**ㅤ**")

        embed = discord.Embed(
            title=f":paperclip: 使用法: **{self.name}** :paperclip:",
            description="\n".join(description_text) if description_text else None,
        )
        [embed.add_field(name=i[0] or "　", value="\n".join(i[1]) or "　", inline=False) for i in arguments]
        return embed

    def is_handler(self, func):
        handler = getattr(func, "_handler", None)
        return isinstance(handler, CommandHandler) and handler is self


class CommandContext(MessageSender):
    def __init__(self, prefix: str, command: CommandHandler, message: discord.Message,
                 execute_name: str, args: list[str], client: "DiscordClient"):
        MessageSender.__init__(self, message.channel, None)

        self.prefix = prefix
        self.execute_name = execute_name
        self.orig_args = args
        self.client = client
        self.me = client.user  # type: discord.abc.ClientUser
        self.content = message.content  # type: str
        self.args_content = self.content[len(self.prefix + self.execute_name) + 1:]
        self.command = command  # type: CommandHandler
        self.message = message  # type: discord.Message
        self.channel = message.channel  # type: MessageableChannel
        self.guild = message.guild  # type: discord.Guild | None
        self.author = message.author  # type: discord.User | discord.Member
        self.task = None  # type: Future | None
        # self.handler = command.handler
        self.interactive = command.interactive
        self.clean_message = command.clean_message
        self.cancelled_by_admin = False
        # auto clean
        self.delete_delay = None  # type: float | None
        self.delete_request = None  # type: bool | None
        self.delete_response = None  # type: bool | None

    def delete_requests(self, delay: float = None):
        return run_coroutine(self.message.delete(delay=delay), (discord.HTTPException,))

    @property
    def arguments(self):
        return Argument(self.orig_args)

    @property
    def args(self):
        return Argument(self.orig_args)

    def clean_auto(self, *, error=False):
        config = get_core().config.discord.auto_clean

        if self.clean_message:
            config_auto_clean_delay = config.auto_clean_delay_with_error if error else config.auto_clean_delay
            delay = config_auto_clean_delay if self.delete_delay is None else self.delete_delay
            delay = max(0, delay)

            delete = self.delete_request
            if delete is None:
                delete = config.delete_request
            if delete:
                self.delete_requests(delay=delay)

            delete = self.delete_response
            if delete is None:
                delete = config.delete_response
            if delete:
                self.delete(delay=delay)
