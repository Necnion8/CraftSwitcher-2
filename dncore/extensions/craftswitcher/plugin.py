from dncore.discord.events import DebugCommandPreExecuteEvent
from dncore.event import onevent
from dncore.extensions.craftswitcher import CraftSwitcher
from dncore.extensions.craftswitcher.bot import BotCommandHandler
from dncore.plugin import Plugin


class CraftSwitcherPlugin(Plugin):
    def __init__(self):
        # config_path = DNCoreAPI.core().config_dir / "switcher.yml"
        config_path = self.data_dir / "config.yml"
        self.switcher = CraftSwitcher(self.loop, config_path, plugin_info=self.info)

    @property
    def config(self):
        return self.switcher.config

    @property
    def servers(self):
        return self.switcher.servers

    async def on_enable(self):
        self.register_listener(self.switcher)
        self.register_commands(BotCommandHandler(self.switcher))
        await self.switcher.init()

    async def on_disable(self):
        try:
            await self.switcher.shutdown()
        finally:
            self.unregister_commands()
            self.unregister_listener(self.switcher)

    @onevent()
    async def on_debug(self, event: DebugCommandPreExecuteEvent):
        event.globals["swi"] = self.switcher
