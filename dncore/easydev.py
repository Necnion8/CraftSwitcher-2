from dncore import DNCoreAPI
from dncore.command import oncommand, CommandContext
from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues
from dncore.discord import events
from dncore.event import onevent
from dncore.plugin import Plugin
from dncore.util.discord import Embed

__all__ = ["DNCoreAPI", "Plugin",
           "onevent", "oncommand", "CommandContext", "events", "Embed",
           "FileConfigValues", "ConfigValues",
           ]

#
#  Example Plugin
#
from logging import getLogger
from dncore.discord.events import ReadyEvent

log = getLogger(__name__)


class ExamplePlugin(Plugin):
    def __init__(self):
        # set values
        pass

    async def on_enable(self):
        # init plugin
        pass

    async def on_disable(self):
        # cleanup plugin
        pass

    @onevent(monitor=True)
    async def on_ready(self, _: ReadyEvent):
        # Discord Ready
        client = DNCoreAPI.client()
        log.info("ログインしました: %s", client.user)

    @oncommand(defaults=True)
    async def cmd_say(self, ctx: CommandContext):
        """
        {command} (内容)
        指定された内容をボットが発言してくれます
        """
        if not ctx.args:
            await ctx.channel.send(content="こんにちは！")

        else:
            await ctx.channel.send(content=ctx.args_content)

#
#
#
