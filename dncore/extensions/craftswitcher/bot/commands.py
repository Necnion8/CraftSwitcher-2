import asyncio
import re
from logging import getLogger

import discord

from dncore import DNCoreAPI
from dncore.command import oncommand, CommandContext
from dncore.extensions.craftswitcher import CraftSwitcher
from dncore.extensions.craftswitcher.abc import ServerState, ServerType
from dncore.extensions.craftswitcher.jardl import ServerBuild

log = getLogger(__name__)


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

    @oncommand()
    async def cmd_jardl(self, ctx: CommandContext):
        """
        {command}
        {command} (type)
        {command} (type) (mcver)
        {command} (type) (mcver) (build)
        サーバーModのダウンローダー一覧
        対応するMCバージョンの一覧
        対応するビルドの一覧
        指定されたビルドのダウンロードリンクを表示 (利用可能な場合)
        """

        args = ctx.args
        if not args:
            # list types
            types = []
            for type_, downloaders in self.swi.server_downloaders.items():
                if downloaders:
                    types.append(type_)

            ls = "\n".join(f"- {t.value}" for t in types)
            await ctx.send_info(":information: 利用可能なダウンローダー:\n" + ls)
            return

        _server_type = args.pop(0)
        try:
            server_type = ServerType(_server_type.lower())
            downloader = self.swi.server_downloaders[server_type][-1]
        except (ValueError, KeyError, IndexError):
            await ctx.send_warn(f":information: 指定されたサーバーが見つかりません: {_server_type.lower()}")
            return

        versions = await downloader.list_versions()
        if not args:
            # list mc version
            ls = []
            for v in versions:
                if not re.search(r"^\d+\.\d+", v.mc_version):  # ^x.x 以外を除外
                    continue
                ls.append(f"- {v.mc_version} ({'?' if v.builds is None else len(v.builds)} builds)")
            ls = "\n".join(ls)
            log.debug(ls)
            await ctx.send_info(f":information: {server_type.value} サーバーの対応バージョン\n" + ls)
            return

        mc_version = args.pop(0)
        for _version in versions:
            if _version.mc_version == mc_version:
                version = _version
                break
        else:
            await ctx.send_warn(f":information: 指定されたバージョンに対応していません: {mc_version}")
            return

        builds = await version.list_builds()  # type: list[ServerBuild]
        if not args:
            # list build

            def fmt(b: ServerBuild):
                s = f"- {b.build}"
                if b.updated_datetime:
                    dt = b.updated_datetime.strftime("%Y/%m/%d %H:%M")
                    s += f" ({dt})"
                if b.recommended:
                    s += " ☆"
                return s

            ls = "\n".join(fmt(b) for b in builds)
            log.debug(ls)
            await ctx.send_info(f":information: {server_type.value} サーバーのビルド一覧 (MC{mc_version})\n" + ls)
            return

        a_build = args.pop(0)
        for _build in builds:
            if _build.build == a_build:
                build = _build
                break
        else:
            await ctx.send_warn(f":information: 指定されたビルドバージョンが見つかりません: {a_build}")
            return

        if not build.is_info_loaded():
            async with ctx.typing():
                await build.fetch_info()

        # show url
        url = build.download_url
        if url:
            await ctx.send_info(f":information: {server_type.value} サーバー (MC{mc_version}, {build.build})\n"
                                f"> {url}")
        else:
            await ctx.send_info(f":information: {server_type.value} サーバー (MC{mc_version}, {build.build})\n"
                                f"> UNKNOWN")
