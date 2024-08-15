from dncore.discord.events import DebugCommandPreExecuteEvent
from dncore.event import onevent
from dncore.extensions.craftswitcher import CraftSwitcher
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
        await self.switcher.init()

    async def on_disable(self):
        await self.switcher.shutdown()

    @onevent()
    async def on_debug(self, event: DebugCommandPreExecuteEvent):
        event.globals["swi"] = self.switcher
