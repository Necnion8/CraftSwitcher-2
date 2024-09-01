from typing import Any

import discord

from dncore.abc.serializables import ActivitySetting
from dncore.discord.status import Activity


class BotActivity(Activity):
    def __init__(self):
        super().__init__(None, status=discord.Status.dnd)
        self.__args = None

    def change(self, setting: ActivitySetting | None, priority: int, args: dict[str, Any]):
        if setting:
            self.status = setting.status
            self.activity = discord.Game(name=setting.activity) if setting.activity else None
        else:
            self.status = None
            self.activity = None
            priority = -1

        self.__args = args
        self.priority = priority

    def get_formatted_activity(self) -> discord.BaseActivity | None:
        return self.format_activity(self.__args)
