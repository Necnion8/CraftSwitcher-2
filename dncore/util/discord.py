import asyncio
import inspect
from typing import Any, Literal

import discord

from dncore.abc import IGNORE_FRAME
from dncore.abc.serializables import Embed
from dncore.util.instance import run_coroutine

__all__ = ["get_intent_names", "MessageSender", "PartialMessageableChannel", "MessageableChannel", "EmbedType"]
PartialMessageableChannel = discord.TextChannel | discord.VoiceChannel | discord.Thread | discord.DMChannel | discord.PartialMessageable
MessageableChannel = PartialMessageableChannel | discord.GroupChannel
EmbedType = Literal['rich', 'image', 'video', 'gifv', 'article', 'link']


def get_intent_names(intent: discord.flags.flag_value | int):
    if isinstance(intent, discord.flags.flag_value):
        intent = intent.flag
    # return [name for name, value in discord.Intents.VALID_FLAGS.items() if intent & value]

    intents = sorted([(k, v) for k, v in discord.Intents.VALID_FLAGS.items()], key=lambda i: i[1], reverse=True)
    names = []
    for name, value in intents:
        if not value & ~ intent:
            names.append(name)
        intent = intent & ~ value

    if intent:
        names.append(str(intent))
    return names


class MessageSender(object):
    def __init__(self, channel: MessageableChannel, self_message: discord.Message | None):
        self.channel = channel
        self.self_message = self_message  # type: discord.Message | None

    async def send_info(self, content: str | discord.Embed | Embed, title: str = None, *,
                        args: dict[str, Any] = None, kw: dict = None, retry=True):
        __ignore_frame = IGNORE_FRAME

        if args is None:
            frame = inspect.currentframe()
            try:
                args = {k: str(v) for k, v in frame.f_back.f_locals.items() if not k.startswith("_")}
            finally:
                del frame

        embed = Embed.info(content=content, title=title).format(args)

        if kw is None:
            kw = {}

        if self.self_message is not None:
            try:
                self.self_message = await self.self_message.edit(embed=embed, **kw)
            except discord.NotFound:
                if retry:
                    self.self_message = await self.channel.send(embed=embed, **kw)
                else:
                    self.self_message = None
        else:
            self.self_message = await self.channel.send(embed=embed, **kw)

        return self.self_message

    async def send_warn(self, content: str | discord.Embed | Embed, title: str = None, *,
                        args: dict[str, Any] = None, kw: dict = None, retry=True):
        __ignore_frame = IGNORE_FRAME

        if args is None:
            frame = inspect.currentframe()
            try:
                args = {k: str(v) for k, v in frame.f_back.f_locals.items() if not k.startswith("_")}
            finally:
                del frame

        embed = Embed.warn(content=content, title=title).format(args)

        if kw is None:
            kw = {}

        if self.self_message is not None:
            try:
                self.self_message = await self.self_message.edit(embed=embed, **kw)
            except discord.NotFound:
                if retry:
                    self.self_message = await self.channel.send(embed=embed, **kw)
                else:
                    self.self_message = None
        else:
            self.self_message = await self.channel.send(embed=embed, **kw)

        return self.self_message

    async def send_error(self, content: str | discord.Embed | Embed, title: str = None, *,
                         args: dict[str, Any] = None, kw: dict = None, retry=True):
        __ignore_frame = IGNORE_FRAME

        if args is None:
            frame = inspect.currentframe()
            try:
                args = {k: str(v) for k, v in frame.f_back.f_locals.items() if not k.startswith("_")}
            finally:
                del frame

        embed = Embed.error(content=content, title=title).format(args)

        if kw is None:
            kw = {}

        if self.self_message is not None:
            try:
                self.self_message = await self.self_message.edit(embed=embed, **kw)
            except discord.NotFound:
                if retry:
                    self.self_message = await self.channel.send(embed=embed, **kw)
                else:
                    self.self_message = None
        else:
            self.self_message = await self.channel.send(embed=embed, **kw)

        return self.self_message

    def delete(self, delay: float = None):
        async def _delete():
            if delay is not None:
                await asyncio.sleep(delay)
            if self.self_message is not None:
                try:
                    await self.self_message.delete()
                except discord.HTTPException:
                    pass
                self.self_message = None

        if self.self_message is not None:
            run_coroutine(_delete())

    def typing(self):
        return self.channel.typing()
