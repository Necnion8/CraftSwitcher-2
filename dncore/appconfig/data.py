import asyncio

import discord

from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues

_schedule_save = None


class Guild(ConfigValues):
    custom_command_prefix: str | None
    channel_blacklist_mode = True
    channel_list_ids: list[int]


class DataFile(FileConfigValues):
    guilds: dict[str, Guild]
    last_shutdown_message_id: int | None
    last_shutdown_message_channel_id: int | None

    def get_guild(self, guild: discord.Guild | int, *, create=True):
        guild_id = str(guild.id if isinstance(guild, discord.Guild) else guild)
        if guild_id not in self.guilds and create:
            guild = Guild()
            self.guilds[guild_id] = guild
        else:
            guild = self.guilds.get(guild_id)
        return guild

    def save(self, *, now=False):
        global _schedule_save

        if now:
            if _schedule_save and not _schedule_save.done():
                _schedule_save.cancel()
                _schedule_save = None
            super().save()
            return

        if _schedule_save and not _schedule_save.done():
            return

        from dncore.util.instance import get_core
        _schedule_save = get_core().loop.create_task(asyncio.sleep(60))
        _schedule_save.add_done_callback(lambda _: self.save(now=True))
