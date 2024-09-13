from dncore.discord.events import DebugCommandPreExecuteEvent
from dncore.event import onevent
from dncore.extensions.craftswitcher import CraftSwitcher, SwitcherExtension, EditableFile, ExtensionInfo
from dncore.extensions.craftswitcher.abc import ServerState
from dncore.extensions.craftswitcher.bot import BotCommandHandler, BotActivity
from dncore.extensions.craftswitcher.event import ServerChangeStateEvent
from dncore.extensions.craftswitcher.ext import SwitcherExtensionManager
from dncore.plugin import Plugin


class CraftSwitcherPlugin(Plugin, SwitcherExtension):
    def __init__(self):
        super().__init__()
        # config_path = DNCoreAPI.core().config_dir / "switcher.yml"
        config_path = self.data_dir / "config.yml"
        self.extensions = SwitcherExtensionManager()
        self.ext_info = ExtensionInfo.create(self.info)
        self.switcher = CraftSwitcher(self.loop, config_path, plugin_info=self.info, extensions=self.extensions)
        self.activity = BotActivity()

    @property
    def config(self):
        return self.switcher.config

    @property
    def servers(self):
        return self.switcher.servers

    def update_activity(self):
        conf = self.config.discord.activities

        servers = sorted(
            (s for s in self.servers.values() if s and conf.target_server.is_target(s)),
            key=lambda s: s.state,
        )
        players = sum(len(s.players) for s in servers)

        if not servers:
            setting = conf.no_server.activity
            priority = conf.no_server_priority
        else:
            status = servers[-1].state
            if ServerState.STARTING == status:
                setting = conf.starting
                priority = conf.starting_priority
            elif ServerState.STOPPING == status:
                setting = conf.stopping
                priority = conf.stopping_priority
            elif ServerState.STARTED == status or ServerState.RUNNING == status:
                if 0 < players:
                    setting = conf.started_joined
                    priority = conf.started_joined_priority
                else:
                    setting = conf.started
                    priority = conf.started_priority
            else:  # default
                setting = conf.stopped
                priority = conf.stopped_priority

        args = dict(
            players=players,
            servers=len(servers),
            servers_online=sum(1 for s in servers if s.state in (ServerState.STARTING, ServerState.RUNNING, )),
        )
        self.activity.change(setting, priority, args)

    async def on_enable(self):
        self.register_listener(self.switcher)
        self.register_commands(BotCommandHandler(self.switcher))
        self.register_activity(self.activity)
        await self.switcher.init()
        self.extensions.add(self, self.ext_info)

    async def on_disable(self):
        self.extensions.remove(self)
        try:
            await self.switcher.shutdown()
        finally:
            self.unregister_commands()
            self.unregister_listener(self.switcher)

    async def on_file_update(self, editable_file: EditableFile):
        # TODO: reload switcher config
        pass

    @onevent()
    async def on_debug(self, event: DebugCommandPreExecuteEvent):
        event.globals["swi"] = self.switcher

    @onevent(monitor=True)
    async def on_state(self, _: ServerChangeStateEvent):
        self.update_activity()
