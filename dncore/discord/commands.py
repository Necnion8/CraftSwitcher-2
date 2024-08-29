import asyncio
import re
from logging import getLogger
from pathlib import Path
from typing import Awaitable, Any
from typing import Callable

import discord

from dncore.abc.serializables import Embed
from dncore.appconfig.commands import CommandCategory
from dncore.command import DEFAULT_OWNER_GROUP, CommandContext, oncommand, CommandManager, DEFAULT_GUILD_OWNER_GROUP
from dncore.command.errors import CommandUsageError
from dncore.discord.events import *
from dncore.event import EventListener, onevent
from dncore.plugin import PluginZipFileLoader, PluginModuleLoader, PluginManager, PluginInfo, sorted_plugins
from dncore.plugin.errors import PluginException, PluginOperationError
from dncore.util import safe_format
from dncore.util.instance import get_core, call_event, run_coroutine

log = getLogger(__name__)


class SettingCommand(object):
    def __init__(self, owner: Any, name: str, usage: str, function: Callable[[CommandContext], Awaitable[None | Embed]]):
        self.owner = owner
        self.name = name.lower()
        self.usage = usage
        self.function = function


class SettingCommandGroup(object):
    def __init__(self, description: str):
        self.description = description
        self.commands = {}  # type: dict[str, SettingCommand]

    def add(self, owner: Any, name: str, usage: str, function: Callable[[CommandContext], Awaitable[None | Embed]]):
        self.commands[name.lower()] = SettingCommand(owner, name, usage, function)
        return self


class DNCoreCommands(EventListener):
    def __init__(self):
        self.lang = get_core().config.messages
        commands = get_core().commands
        if "utility" not in commands.config.categories:
            commands.config.categories["utility"] = CommandCategory("ユーティリティ")

        self.debug_last_messages = []  # type: list[discord.Message]
        self.setting_commands = []  # type: list[SettingCommandGroup]

        # register
        grp = self.add_setting("コマンドプレフィックスの設定")
        grp.add(None, "setPrefix", "(ﾌﾟﾚﾌｨｯｸｽ)", self._set_prefix)
        grp.add(None, "clearPrefix", "", self._clear_prefix)
        grp = self.add_setting("コマンドチャンネルの設定")
        grp.add(None, "setBlacklist", "(ﾁｬﾝﾈﾙID..)", self._set_blacklist)
        grp.add(None, "setWhitelist", "(ﾁｬﾝﾈﾙID..)", self._set_whitelist)
        grp.add(None, "addList", "(ﾁｬﾝﾈﾙID..)", self._add_list)
        grp.add(None, "removeList", "(ﾁｬﾝﾈﾙID..)", self._remove_list)
        grp.add(None, "clearList", "", self._clear_list)

    def add_setting(self, description: str) -> SettingCommandGroup:
        group = SettingCommandGroup(description)
        self.setting_commands.append(group)
        return group

    def remove_setting(self, owner: Any):
        for group in list(self.setting_commands):
            for name, command in dict(group.commands).items():
                if command.owner == owner:
                    group.commands.pop(name)

            if not group.commands:
                self.setting_commands.remove(group)

    @property
    def data(self):
        return get_core().data

    @oncommand(defaults=True, category="utility", allow_channels=discord.TextChannel | discord.DMChannel)
    async def cmd_help(self, ctx: CommandContext):
        """
        {command} [コマンド] [..引数]

        実行できるコマンドの一覧を表示します

        > コマンド
        指定された `コマンド` の使用法を表示します
        > 引数
        引数を指定した使用法を表示します
        """
        from dncore.command import CommandManager
        cmd = get_core().commands  # type: CommandManager
        m = self.lang.help

        if ctx.arguments:
            args = ctx.arguments
            name = args.pop(0)
            return await get_core().client.send_command_usage(ctx, name, None)

        # list
        commands = [name for name in cmd.get_commands(type(ctx.channel))
                    if get_core().client.allowed(name, ctx.author, ctx.guild)]

        lines = []
        for category_name, category in cmd.config.categories.items():
            names = [name for name, entry in category.commands.items() if name in commands]
            if names:
                lines.append(safe_format(m.line, dict(
                    category=category.label or category_name,
                    commands=m.split.join(names),
                    count=len(names),
                )))

        if not lines:
            return Embed.warn(m.no_commands)

        return Embed.info(m.list).format(dict(
            lines="\n".join(lines),
            count=len(commands),
            version=get_core().version,
            discord_version=discord.__version__,
        ))

    @oncommand(defaults=True, category="utility", allow_channels=discord.TextChannel | discord.DMChannel)
    async def cmd_clean(self, ctx: CommandContext):
        """
        {command} [件数]

        ボットの発言メッセージと実行コマンドメッセージを削除します

        > 件数
        指定された `件数` メッセージを削除します。デフォルトで 100件 です
        """
        ctx.clean_auto()
        ctx.delete_request = ctx.delete_response = True
        ctx.delete_delay = 5

        try:
            search_range = max(1, min(int(ctx.arguments[0]), 9999))
        except IndexError:
            search_range = 100
        except ValueError:
            return Embed.error(self.lang.clean.search_range_invalid)

        channel = ctx.channel

        def _check(m: discord.Message):
            return m.author == get_core().client.user or m.content.lower().startswith(ctx.prefix.lower())

        try:
            try:
                if not isinstance(channel, discord.TextChannel):
                    raise RuntimeError

                async with ctx.typing():
                    msgs = await channel.purge(limit=search_range, check=_check, reason="Clean Command")
                count = len(msgs)

            except (discord.Forbidden, RuntimeError):
                if isinstance(channel, discord.abc.GuildChannel):
                    perms = channel.permissions_for(channel.guild.me)
                    if not perms.read_message_history:
                        return Embed.error(self.lang.clean.no_perm_read_history)
                    delete_users = perms.manage_messages
                else:
                    delete_users = False

                fs = []

                async with channel.typing():
                    async for message in channel.history(limit=search_range):
                        if (delete_users or message.author == get_core().client.user) and _check(message):
                            fs.append(get_core().loop.create_task(message.delete()))

                    await asyncio.wait(fs)
                count = len(fs)

        except discord.HTTPException as e:
            return Embed.error(self.lang.clean.error).format(args=dict(message=str(e)))

        return Embed.info(self.lang.clean.deleted).format(dict(count=count))

    @oncommand(defaults=DEFAULT_GUILD_OWNER_GROUP)
    async def cmd_setting(self, ctx: CommandContext):
        mode = ctx.arguments.get(0, "info").lower()

        if mode == "info":
            return await self._info(ctx)

        for group in self.setting_commands:
            try:
                command = group.commands[mode]
                break
            except KeyError:
                pass
        else:
            raise CommandUsageError

        ctx.orig_args.pop(0)
        return await command.function(ctx)

    @oncommand(defaults=DEFAULT_OWNER_GROUP)
    async def cmd_debug(self, ctx: CommandContext):
        if not ctx.arguments:
            return Embed.error(self.lang.debug.specify_code)

        ctx.clean_message = False

        size = len(ctx.prefix + ctx.execute_name + " ")
        content = ctx.content[size:]

        if content.startswith("```") and content.endswith("```"):
            content = "\n".join(content.rstrip("`\n").split("\n")[1:])
        content = content.strip("` \n")

        from dncore.dncore import DNCoreAPI

        __globals = dict(
            discord=discord,
            asyncio=asyncio,
            core=get_core(),
            loop=get_core().loop,
            client=get_core().client,
            me=get_core().client.user,
            ctx=ctx,
            message=ctx.message,
            channel=ctx.channel,
            author=ctx.author,
            guild=ctx.guild,
            api=DNCoreAPI,
            m=ctx.message,
            ch=ctx.channel,
            g=ctx.guild,
            getplugin=DNCoreAPI.get_plugin,
            getplugininfo=DNCoreAPI.plugins().get_plugin_info,
        )
        await call_event(DebugCommandPreExecuteEvent(ctx, __globals))

        exc = result = None
        try:
            result = eval(content, __globals)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as e:
            exc = e

        if exc:
            lines = content.splitlines()
            for idx, line in enumerate(reversed(lines)):
                if not line:
                    continue

                if line and not line.startswith(("return", "  ")):
                    lines[-idx-1] = f"r = {line}"
                    lines.append("return r")
                break

            script = "async def __exec():\n  " + "\n  ".join(lines)
            try:
                exec(script, __globals, locals())
                result = await locals()["__exec"]()
            except Exception as e:
                log.info("Debug Executing", exc_info=True)

                [run_coroutine(m.delete(), ignores=(discord.HTTPException,)) for m in self.debug_last_messages]
                m = await ctx.send_error(f"{type(e).__name__}: {e}", title="実行結果")
                self.debug_last_messages.clear()
                self.debug_last_messages.append(m)
                self.debug_last_messages.append(ctx.message)
                return

        result = repr(result)
        log.info("Debug Result: %s", result)
        result = result.replace("```", "\\```")
        max_size = 2000 - 9
        if len(result) > max_size:
            result = "... " + result[len(result) - max_size - 4:]

        [run_coroutine(m.delete(), ignores=(discord.HTTPException,)) for m in self.debug_last_messages]
        m = await ctx.send_info(f"```py\n{result.replace('{', '{{').replace('}', '}}')}```",
                                title="実行結果")
        self.debug_last_messages.clear()
        self.debug_last_messages.append(m)
        self.debug_last_messages.append(ctx.message)

    @oncommand(defaults=DEFAULT_OWNER_GROUP)
    async def cmd_shutdown(self, ctx: CommandContext):
        """
        {command}
        ボットを停止します
        """
        if not await self._ask_confirm_shutdown(ctx):
            return

        m = await ctx.send_warn(self.lang.shutdown.shutdown)
        await ctx.delete_requests()

        if ctx.guild:
            self.data.last_shutdown_message_id = m.id
            self.data.last_shutdown_message_channel_id = m.channel.id
            self.data.save()

        get_core().loop.create_task(get_core().shutdown())

    @oncommand(defaults=DEFAULT_OWNER_GROUP)
    async def cmd_restart(self, ctx: CommandContext):
        """
        {command}
        ボットを再起動します
        """
        if not await self._ask_confirm_shutdown(ctx):
            return

        m = await ctx.send_warn(self.lang.shutdown.restarting)
        await ctx.delete_requests()

        if ctx.guild:
            self.data.last_shutdown_message_id = m.id
            self.data.last_shutdown_message_channel_id = m.channel.id
            self.data.save()

        get_core().loop.create_task(get_core().shutdown(restart=True))

    @oncommand(defaults=DEFAULT_OWNER_GROUP, aliases="dnc", interactive=True)
    async def cmd_dncore(self, ctx: CommandContext):
        """
        dnCore 管理コマンド
        ```md
        {prefix}{name} info  # default
        {prefix}{name} reconnect
        {prefix}{name} reloadconfig
        {prefix}{name} reloadcommands

        # Plugin Manage: info, enable, disable
        {prefix}{name} pmi (plugin)
        {prefix}{name} pme (plugin)
        {prefix}{name} pmd (plugin)
        # Plugin Manage: load, unload, reload
        {prefix}{name} pml (plugin.dcp)
        {prefix}{name} pml (/extension)
        {prefix}{name} pmu (plugin)
        {prefix}{name} pmr (plugin)

        # Plugin To File: toPlugin, toExtension
        {prefix}{name} pm2p (plugin) [fileExtraName]
        {prefix}{name} pm2e (plugin)

        # Plugin File To File: ExtToPlugin, PluginToExt
        {prefix}{name} pf2p (extModName) [fileExtraName]
        {prefix}{name} pf2e (plFileName)```
        """
        mode = ctx.arguments.get(0, "info").lower()
        cmdmgr = get_core().commands  # type: CommandManager
        plmgr = get_core().plugins  # type: PluginManager

        if mode == "info":
            plugins = sorted(plmgr.plugins.values(),
                             key=lambda pi: (not pi.enabled, pi.name))
            plugins = list(pi.name if pi.enabled else f"*{pi.name}*" for pi in plugins)

            handlers = cmdmgr.handlers
            commands = cmdmgr.commands
            running = [c for cc in cmdmgr.running_commands.values() for c in cc]
            aliases = list(cmdmgr.aliases)
            registered = sum([bool(hid in commands.values() and handler) for hid, handler in handlers.items()])
            disabled_text = f" ({len(commands)-registered} disabled)" if len(commands) - registered else ""
            client = get_core().client
            owner_text = f"**{client.owner}**" if client.owner else "*unknown*"
            version = get_core().version

            embed = discord.Embed()
            embed.add_field(name=":small_orange_diamond: System Info:",
                            value=f":white_small_square: Bot Owner: {owner_text}\n" +
                                  f":white_small_square: Joined Guild: **{len(client.guilds)}**\n" +
                                  f":white_small_square: Running Task: **{len(asyncio.all_tasks())}**\n",
                            inline=False)
            embed.add_field(name=":small_orange_diamond: System Version:",
                            value=f":white_small_square: dnCore **v{version.numbers}** ({version.release_date})\n" +
                                  f":white_small_square: discord.py **v{discord.__version__}**",
                            inline=False)
            embed.add_field(name=f":small_orange_diamond: Plugin List ({len(plugins)}):",
                            value=":white_small_square: " + ", ".join(plugins),
                            inline=False)
            embed.add_field(name=f":small_orange_diamond: Commands ({len(commands)}):",
                            value=f":white_small_square: Enabled: **{registered}** commands{disabled_text}\n" +
                                  f":white_small_square: Aliases: **{len(aliases)}**\n" +
                                  f":white_small_square: Running: **{len(running)}**",
                            inline=False)

            return Embed.info(embed)

        elif mode == "reconnect":
            if not get_core().config.discord.token:
                await ctx.send_error(":warning: ボットトークンが設定されていません。")
                return

            m = await ctx.send_warn(":recycle: Discordに再接続しています･･･")
            m_id = m.id
            ch_id = m.channel.id
            await ctx.delete_requests()

            async def _reconnect_task():
                try:
                    await get_core().connect(reconnect=True, fail_to_shutdown=True)

                except Exception as e:
                    log.error("Failed to reconnect to discord from command", exc_info=e)
                    return

                await asyncio.sleep(1)
                client = get_core().client
                if client:
                    await client.wait_until_ready()

                    try:
                        m = await client.fetch_message(ch_id, m_id)
                    except discord.HTTPException:
                        return

                    await m.edit(embed=Embed.info(":ok_hand: Discordに再接続しました。"), delete_after=5)

            get_core().loop.create_task(_reconnect_task())

        elif mode == "reloadconfig":
            try:
                get_core().config.load()

            except Exception as e:
                log.warning("Failed to reload config from command", exc_info=e)
                return Embed.error(":exclamation: エラーが発生しました。")
            return Embed.info(":ok_hand: dnCore設定ファイルを再読み込みしました。")

        elif mode == "reloadcommands":
            try:
                cmdmgr.config.load()
                cmdmgr.remap()

            except Exception as e:
                log.warning("Failed to reload commands from command", exc_info=e)
                return Embed.error(":exclamation: エラーが発生しました。")
            return Embed.info(":ok_hand: コマンド設定を再読み込みしました。")

        elif mode in ("pmi", "pminfo"):
            try:
                plugin_name = ctx.arguments[1]
            except IndexError:
                return Embed.warn(":grey_exclamation: プラグインを指定してください。")

            plugin = plmgr.get_plugin_info(plugin_name)
            if not plugin:
                return Embed.error(":grey_exclamation: プラグインが見つかりません。")

            state = ("Disabled", "Enabled")[plugin.enabled]
            if plugin.instance:
                commands = cmdmgr.get_commands_from_parent(plugin.instance)
                commands = [f"`{n}`" for n in sorted(c.name for c in commands)]
            else:
                commands = ["N/A"]

            source_file = None
            if isinstance(plugin.loader, PluginZipFileLoader):
                source_file = plugin.loader.plugin_file
            elif isinstance(plugin.loader, PluginModuleLoader):
                source_file = plugin.loader.module_directory
            if source_file:
                try:
                    source_file = Path(source_file).absolute().relative_to(Path().absolute()).as_posix()
                except ValueError:
                    source_file = source_file.name if source_file else None
            source = f" ({source_file})" if source_file else ""

            description_lines = [
                f":white_small_square: Version: **{plugin.version}**",
                f":white_small_square: Status: **{state}**",
                f":white_small_square: Loader: {type(plugin.loader).__name__}{source}",
                f":white_small_square: Commands: {', '.join(commands)}",
            ]

            embed = discord.Embed(title=f":jigsaw: Plugin: {plugin.name} :jigsaw:",
                                  description="\n".join(description_lines))
            return Embed.info(embed)

        elif mode in ("pme", "pmenable"):
            try:
                plugin = plmgr.get_plugin_info(ctx.arguments[1])
            except IndexError:
                return Embed.warn(":grey_exclamation: プラグインを指定してください。")

            if not plugin:
                return Embed.error(":grey_exclamation: プラグインが見つかりません。")

            if plugin.enabled:
                return Embed.warn(":grey_exclamation: 既に有効化されています。")

            try:
                async with ctx.typing():
                    res = await plmgr.enable_plugin(plugin)
            except PluginException as e:
                return Embed.error(f":exclamation: エラー: {e}")

            if res:
                cmdmgr.remap()
                return Embed.info(f":jigsaw: {plugin.name} v{plugin.version} を有効化しました。")
            else:
                return Embed.error(f":exclamation: {plugin.name} の処理中にエラーが発生しました。")

        elif mode in ("pmd", "pmdisable"):
            try:
                plugin = plmgr.get_plugin_info(ctx.arguments[1])
            except IndexError:
                return Embed.warn(":grey_exclamation: プラグインを指定してください。")

            if not plugin:
                return Embed.error(":grey_exclamation: プラグインが見つかりません。")

            if not plugin.enabled:
                return Embed.warn(":grey_exclamation: 既に無効化されています。")

            try:
                async with ctx.typing():
                    res = await plmgr.disable_plugin(plugin)
            except PluginException as e:
                return Embed.error(f":exclamation: エラー: {e}")

            if res:
                return Embed.info(f":jigsaw: {plugin.name} v{plugin.version} を無効化しました。")
            else:
                return Embed.error(f":exclamation: {plugin.name} の処理中にエラーが発生しました。")

        elif mode in ("pmr", "pmreload"):
            try:
                plugin = plmgr.get_plugin_info(ctx.arguments[1])
            except IndexError:
                return Embed.warn(":grey_exclamation: プラグインを指定してください。")

            if not plugin:
                return Embed.error(":grey_exclamation: プラグインが見つかりません。")

            try:
                async with ctx.typing():
                    info = await plmgr.reload_plugin(plugin)

            except PluginException as e:
                return Embed.error(f":exclamation: エラー: {e}")

            if not info:
                return Embed.error(f":exclamation: {plugin.name} v{plugin.version} を再ロードできませんでした。")

            elif not info.enabled:
                return Embed.error(f":exclamation: {plugin.name} v{plugin.version} を再有効化できませんでした。")

            else:
                cmdmgr.remap()
                return Embed.info(f":jigsaw: {plugin.name} v{plugin.version} を再有効化しました。")

        elif mode in ("pml", "pmload"):
            args = ctx.arguments
            args.pop(0)
            _filename = " ".join(args)
            if not _filename:
                return Embed.warn(":grey_exclamation: ファイル名を指定してください。")

            filename = Path(Path(_filename).name)

            if _filename.startswith("/"):  # module path
                mod_dir = plmgr.extensions_directory / filename
                if not mod_dir.is_dir():
                    return Embed.error(":grey_exclamation: 指定されたモジュールが見つかりません。")

                loader = PluginModuleLoader(mod_dir, plmgr.plugin_data_dir)
                try:
                    info = loader.create_info()
                except Exception as e:
                    log.warning("Failed to load extension info", exc_info=e)
                    return Embed.error(":grey_exclamation: プラグイン情報をロードできませんでした。")

            elif _filename.endswith(".dcp"):  # plugin path
                pl_file = plmgr.plugins_directory / filename
                if not pl_file.is_file():
                    return Embed.error(":grey_exclamation: 指定されたプラグインファイルが見つかりません。")

                loader = PluginZipFileLoader(pl_file, plmgr.plugin_data_dir)
                try:
                    info = loader.create_info()
                except Exception as e:
                    log.warning("Failed to load dcp info", exc_info=e)
                    return Embed.error(":grey_exclamation: プラグイン情報をロードできませんでした。")

            else:  # name search
                _search_info = []  # type: list[PluginInfo]
                for child in plmgr.plugins_directory.iterdir():
                    if not child.is_file() or not child.name.endswith(".dcp"):
                        continue
                    try:
                        loader = PluginZipFileLoader(child, plmgr.plugin_data_dir)
                        _info = loader.create_info()
                    except (Exception,):
                        continue

                    if _filename.lower() == _info.name.lower():
                        _search_info.append(_info)

                if not _search_info:
                    return Embed.error(":grey_exclamation: プラグインファイルが見つかりません。")

                info = sorted_plugins(_search_info)[0]

            if info.name.lower() in plmgr.plugins:
                return Embed.warn(f":grey_exclamation: {info.name}プラグインは既にロードされています。")

            try:
                async with ctx.typing():
                    info = await plmgr.load_plugin(info.loader, info)
                    if not info:
                        raise PluginOperationError("Failed to load info")
                    res = await plmgr.enable_plugin(info)
                    if res:
                        cmdmgr.remap()

            except PluginException as e:
                return Embed.error(f":exclamation: エラー: {e}")

            if res:
                return Embed.info(f":jigsaw: {info.name} v{info.version} をロードし、有効化しました。")
            else:
                return Embed.error(f":exclamation: {info.name} を有効化できませんでした。")

        elif mode in ("pmu", "pmunload"):
            try:
                plugin = plmgr.get_plugin_info(ctx.arguments[1])
            except IndexError:
                return Embed.warn(":grey_exclamation: プラグインを指定してください。")

            if not plugin:
                return Embed.error(":grey_exclamation: プラグインが見つかりません。")

            try:
                if plugin.enabled:
                    async with ctx.typing():
                        await plmgr.disable_plugin(plugin)

                await plmgr.unload_plugin(plugin)

            except PluginException as e:
                return Embed.error(f":exclamation: エラー: {e}")

            return Embed.info(f":jigsaw: {plugin.name} v{plugin.version} をアンロードしました。")

        elif mode == "pm2p":
            try:
                plugin = plmgr.get_plugin_info(ctx.arguments[1])
            except IndexError:
                return Embed.warn(":grey_exclamation: プラグインを指定してください。")
            extra_name = " ".join(ctx.arguments[2:]) or None

            if not plugin:
                return Embed.error(":grey_exclamation: プラグインが見つかりません。")

            loader = plugin.loader
            if not isinstance(loader, PluginModuleLoader):
                return Embed.error(f":grey_exclamation: このプラグインは処理できません。")

            try:
                async with ctx.typing():
                    packed_path = await loader.pack_to_plugin_file(plmgr.plugins_directory, info=plugin, extra_name=extra_name)

            except FileExistsError:
                return Embed.error(f":grey_exclamation: 同じ名前のファイルが存在します。")

            return Embed.info(f":ok_hand: {packed_path.name} として書き出しました。")

        elif mode == "pm2e":
            try:
                plugin = plmgr.get_plugin_info(ctx.arguments[1])
            except IndexError:
                return Embed.warn(":grey_exclamation: プラグインを指定してください。")

            if not plugin:
                return Embed.error(":grey_exclamation: プラグインが見つかりません。")

            loader = plugin.loader
            if not isinstance(loader, PluginZipFileLoader):
                return Embed.error(f":grey_exclamation: このプラグインは処理できません。")

            try:
                async with ctx.typing():
                    unpacked_path = await loader.unpack_to_extension_module(plmgr.extensions_directory, info=plugin)

            except FileExistsError:
                return Embed.error(f":grey_exclamation: 同じ名前のモジュールが存在します。")

            return Embed.info(f":ok_hand: {unpacked_path.name} モジュールとして書き出しました。")

        elif mode == "pf2p":
            try:
                mod_dir = plmgr.extensions_directory / ctx.arguments[1]
            except IndexError:
                return Embed.warn(":grey_exclamation: モジュール名を指定してください。")
            extra_name = " ".join(ctx.arguments[2:]) or None

            if not mod_dir.is_dir():
                return Embed.error(":grey_exclamation: 見つかりません")

            try:
                async with ctx.typing():
                    packed_path = await plmgr.pack_to_plugin_file(mod_dir, extra_name=extra_name)

            except FileExistsError:
                return Embed.error(f":grey_exclamation: 同じ名前のファイルが存在します。")

            return Embed.info(f":ok_hand: {packed_path.name} として書き出しました。")

        elif mode == "pf2e":
            try:
                plugin_file = plmgr.plugins_directory / ctx.arguments[1]
            except IndexError:
                return Embed.warn(":grey_exclamation: ファイル名を指定してください。")

            if not plugin_file.is_file():
                return Embed.error(":grey_exclamation: 見つかりません")

            try:
                async with ctx.typing():
                    unpacked_path = await plmgr.unpack_to_extension_module(plugin_file)

            except FileExistsError:
                return Embed.error(f":grey_exclamation: 同じ名前のモジュールが存在します。")

            return Embed.info(f":ok_hand: {unpacked_path.name} モジュールとして書き出しました。")

        else:
            raise CommandUsageError

    # events

    @onevent()
    async def on_ready(self, _: ReadyEvent):
        m_id = self.data.last_shutdown_message_id
        ch_id = self.data.last_shutdown_message_channel_id
        if m_id and ch_id:
            try:
                m = await get_core().client.fetch_message(ch_id, m_id)
            except discord.HTTPException:
                pass
            else:
                get_core().loop.create_task(m.edit(embed=Embed.info(self.lang.shutdown.restarted), delete_after=5))
            self.data.last_shutdown_message_id = None
            self.data.last_shutdown_message_channel_id = None
            self.data.save()

    @onevent()
    async def on_help_error(self, event: HelpCommandPreExecuteEvent):
        if event.cancelled or not event.command:
            return
        if not event.command.is_handler(self.cmd_setting):
            return

        event.cancelled = True
        groups = []
        for group in self.setting_commands:
            s = ["# " + group.description or ""]
            for command in group.commands.values():
                s.append(f"{{prefix}}{{name}} {command.name} " + (command.usage or ""))
            groups.append("\n".join(s))

        s = "ギルド設定コマンド\n```md\n" + "\n\n".join(groups) + "```"

        ctx = event.context
        await ctx.send_info(event.command.format_usage(s, ctx.prefix))

    async def _ask_confirm_shutdown(self, ctx: CommandContext, *, timeout=10):
        """
        PreShutdownEventを実行し、シャットダウンを確認する必要があるプラグインをチェックします。

        タスクがないか、timeoutで指定された時間が経過するまでに実行者の yes が確認されると True を返します。
        """
        pre_event = PreShutdownEvent()
        await call_event(pre_event)
        if pre_event.messages:
            ctx.interactive = True
            ctx.delete_response = False

            tasks = self.lang.shutdown.task_pending_format_split.join(
                self.lang.shutdown.task_pending_format.format(plugin=owner.info.name, message=message)
                for owner, message in pre_event.messages.items()
            )
            await ctx.send_warn(self.lang.shutdown.task_pending, args=dict(
                count=len(pre_event.messages),
                tasks=tasks,
                timeout=timeout,
            ))

            def check(_m: discord.Message):
                return _m.author == ctx.author and _m.channel == ctx.channel

            try:
                msg = await ctx.client.wait_for("message", check=check, timeout=timeout)
            except asyncio.TimeoutError:
                ctx.delete()
                ctx.delete_requests()
                return False

            if msg.content.lower() in (
                    "y", "yes", "confirm", "ok",
                    "n", "no", "cancel",
            ):
                run_coroutine(msg.delete(), (discord.HTTPException,))

            if msg.content.lower() not in ("y", "yes", "confirm", "ok"):
                ctx.delete()
                ctx.delete_requests()
                return False

        return True

    # guild setting

    async def _info(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=False)
        if data:
            prefix = data.custom_command_prefix
            blacklist_mode = data.channel_blacklist_mode
            channel_ids = data.channel_list_ids
        else:
            prefix = None
            blacklist_mode = True
            channel_ids = []

        prefix_text = f"**{prefix}**" if prefix else "未設定"
        channel_list_mode = "禁止チャンネル" if blacklist_mode else "許可チャンネル"
        channel_names = " ".join(f"<#{ch_id}>" for ch_id in channel_ids)

        icon = SettingInfoCommandPreExecuteEvent.LINE_ICON
        description_lines = [
            f"{icon} カスタムプレフィックス: {prefix_text}",
            f"{icon} {channel_list_mode}: {channel_names}",
        ]

        embed = discord.Embed(title=f":wrench: ギルド設定 :wrench:",
                              description="\n".join(description_lines))

        pre_event = SettingInfoCommandPreExecuteEvent(ctx, embed)
        await call_event(pre_event)

        if pre_event.override_embed is not None:
            embed = pre_event.override_embed

        elif pre_event.extra:
            for lines in pre_event.extra.values():
                description_lines.extend(lines)
            embed.description = "\n".join(description_lines)

        return Embed.info(embed)

    async def _set_prefix(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=True)
        try:
            new_prefix = ctx.arguments[0].lower()
        except IndexError:
            return Embed.warn(":grey_exclamation: 新しいプレフィックスを指定してください。")

        data.custom_command_prefix = new_prefix
        self.data.save()
        return Embed.info(f":ok_hand: プレフィックスを **`{new_prefix}`** に変更しました。")

    async def _clear_prefix(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=False)
        if not data or not data.custom_command_prefix:
            return Embed.warn(":grey_exclamation: カスタムプレフィックスは設定されていません。")

        data.custom_command_prefix = None
        self.data.save()
        return Embed.info(f":ok_hand: カスタムプレフィックス設定を削除しました。")

    async def _set_blacklist(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=True)

        if not ctx.arguments:
            return Embed.warn(":grey_exclamation: チャンネルID が指定されていません。")

        channel_regex = re.compile(r"^(<#(\d{18})>|(\d{18}))$")
        channel_ids = []
        for ch in ctx.arguments:
            m = channel_regex.match(ch)
            if m:
                try:
                    channel_id = int(m.group(2) or m.group(3))
                except ValueError:
                    continue
                channel_ids.append(channel_id)

        if not channel_ids:
            return Embed.warn(":grey_exclamation: チャンネルID が正しくありません。")

        data.channel_list_ids.clear()
        data.channel_list_ids.extend(channel_ids)
        data.channel_blacklist_mode = True
        self.data.save()

        channel_names = " ".join(f"<#{ch_id}>" for ch_id in channel_ids)
        return Embed.info(f":ok_hand: 禁止チャンネルを設定: {channel_names}")

    async def _set_whitelist(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=True)

        if not ctx.arguments:
            return Embed.warn(":grey_exclamation: チャンネルID が指定されていません。")

        channel_regex = re.compile(r"^(<#(\d{18})>|(\d{18}))$")
        channel_ids = []
        for ch in ctx.arguments:
            m = channel_regex.match(ch)
            if m:
                try:
                    channel_id = int(m.group(2) or m.group(3))
                except ValueError:
                    continue
                channel_ids.append(channel_id)

        if not channel_ids:
            return Embed.warn(":grey_exclamation: チャンネルID が正しくありません。")

        data.channel_list_ids.clear()
        data.channel_list_ids.extend(channel_ids)
        data.channel_blacklist_mode = False
        self.data.save()

        channel_names = " ".join(f"<#{ch_id}>" for ch_id in channel_ids)
        return Embed.info(f":ok_hand: 許可チャンネルを設定: {channel_names}")

    async def _add_list(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=True)

        if not ctx.arguments:
            return Embed.warn(":grey_exclamation: チャンネルID が指定されていません。")

        channel_regex = re.compile(r"^(<#(\d{18})>|(\d{18}))$")
        channel_ids = []
        for ch in ctx.arguments:
            m = channel_regex.match(ch)
            if m:
                try:
                    channel_id = int(m.group(2) or m.group(3))
                except ValueError:
                    continue
                if channel_id not in channel_ids:
                    channel_ids.append(channel_id)

        if not channel_ids:
            return Embed.warn(":grey_exclamation: チャンネルID が正しくありません。")

        data.channel_list_ids.extend(ch_id for ch_id in channel_ids if ch_id not in data.channel_list_ids)
        self.data.save()

        mode = "禁止チャンネル" if data.channel_blacklist_mode else "許可チャンネル"
        channel_names = " ".join(f"<#{ch_id}>" for ch_id in data.channel_list_ids)
        return Embed.info(f":ok_hand: {mode}を再設定: {channel_names}")

    async def _remove_list(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=True)

        if not ctx.arguments:
            return Embed.warn(":grey_exclamation: チャンネルID が指定されていません。")

        channel_regex = re.compile(r"^(<#(\d{18})>|(\d{18}))$")
        channel_ids = []
        for ch in ctx.arguments:
            m = channel_regex.match(ch)
            if m:
                try:
                    channel_id = int(m.group(2) or m.group(3))
                except ValueError:
                    continue
                channel_ids.append(channel_id)

        if not channel_ids:
            return Embed.warn(":grey_exclamation: チャンネルID が正しくありません。")

        for ch_id in list(data.channel_list_ids):
            if ch_id in data.channel_list_ids and ch_id in channel_ids:
                data.channel_list_ids.remove(ch_id)

        if not data.channel_blacklist_mode and not data.channel_list_ids:
            data.channel_blacklist_mode = True
            self.data.save()
            return Embed.info(":ok_hand: チャンネルホワイトリスト設定を解除しました。")

        self.data.save()
        mode = "禁止チャンネル" if data.channel_blacklist_mode else "許可チャンネル"
        channel_names = " ".join(f"<#{ch_id}>" for ch_id in data.channel_list_ids)
        return Embed.info(f":ok_hand: {mode}を再設定: {channel_names}")

    async def _clear_list(self, ctx: CommandContext):
        data = self.data.get_guild(ctx.guild, create=False)
        if data:
            data.channel_blacklist_mode = True
            data.channel_list_ids.clear()
            self.data.save()

        return Embed.info(":ok_hand: チャンネルホワイトリスト設定を解除しました。")
