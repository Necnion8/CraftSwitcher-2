import asyncio

import discord

from dncore import DNCoreAPI
from dncore.command import oncommand, CommandContext
from dncore.extensions.craftswitcher import CraftSwitcher
from dncore.extensions.craftswitcher.abc import ServerState


class BotCommandHandler(object):
    def __init__(self, switcher: CraftSwitcher):
        self.swi = switcher

    @oncommand()
    async def cmd_start(self, ctx: CommandContext):
        """
        {command} (server)
        """
        try:
            server = self.swi.servers[ctx.args[0].lower()]
            if server is None:
                raise KeyError
        except IndexError:
            return await ctx.send_warn(":warning: 起動するサーバーを指定してください")
        except KeyError:
            return await ctx.send_warn(":warning: 指定されたサーバーはありません")

        if server.state.is_running:
            return await ctx.send_warn(":warning: 指定されたサーバーはすでに起動しています")

        await server.start()
        await ctx.send_info(f":ok_hand: {server.config.name or server.id} を起動しています")

    @oncommand()
    async def cmd_stop(self, ctx: CommandContext):
        """
        {command} (server)
        """
        try:
            server = self.swi.servers[ctx.args[0].lower()]
            if server is None:
                raise KeyError
        except IndexError:
            return await ctx.send_warn(":warning: 停止するサーバーを指定してください")
        except KeyError:
            return await ctx.send_warn(":warning: 指定されたサーバーはありません")

        if not server.state.is_running:
            return await ctx.send_warn(":warning: 指定されたサーバーはすでに停止しています")

        await server.stop()
        await ctx.send_info(f":ok_hand: {server.config.name or server.id} を停止しています")

        async def _wait():
            try:
                await server.wait_for_shutdown()
            except asyncio.TimeoutError:
                return

            await ctx.send_info(f":ok_hand: {server.config.name or server.id} を停止しました。")

        DNCoreAPI.run_coroutine(_wait())

    @oncommand()
    async def cmd_list(self, ctx: CommandContext):
        """
        {command}
        """
        embed = discord.Embed()

        for server in self.swi.servers.values():
            if server is None:
                continue

            status_text = server.state.name
            if server.state == ServerState.STOPPED:
                status_logo = "🟥"
            elif server.state == ServerState.STARTED:
                status_logo = "🟩"
            elif server.state == ServerState.STARTING:
                status_logo = "🟧"
            elif server.state == ServerState.STOPPING:
                status_logo = "🟧"
            elif server.state == ServerState.RUNNING:
                status_text = "RUNNING"
                status_logo = "🟧"
            else:
                status_text = f"{server.state.name} ?"
                status_logo = "🟥"

            player_text = ""
            # if server.players is not None:
            #     player_text = str(len(server.players))
            # if server.max_player is not None:
            #     player_text += "/" + str(server.max_player)

            tps_text = ""
            # if server.tps is None:
            #     tps_text = ""
            #     tps_color_code = ""
            # else:
            #     tps_text = str(round(server.tps, 1))
            #     if server.tps > 18:
            #         tps_color_code = "yml"
            #     elif server.tps > 16:
            #         tps_color_code = "fix"
            #     else:
            #         tps_color_code = ""

            #
            if tps_text:
                name = f"{status_logo}  {server.id}  ({tps_text})"
            else:
                name = f"{status_logo}  {server.id}"
            if player_text:
                value = f"```{status_text} | {player_text}```"
            else:
                value = f"```{status_text}```"

            embed.add_field(name=name, value=value, inline=False)

        await ctx.send_info(embed, title="📋  サーバー一覧")
