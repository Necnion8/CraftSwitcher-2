from asyncio import AbstractEventLoop, CancelledError
from logging import getLogger

import discord.abc
from aiohttp import ClientResponse

from dncore.abc.serializables import Embed, Emoji
from dncore.appconfig.config import DiscordSection, CleanSection
from dncore.command import CommandContext, CommandHandler, DEFAULT_GUILD_ADMIN_GROUP, DEFAULT_DEFAULT_GROUP
from dncore.command.argument import Argument
from dncore.command.errors import *
from dncore.command.events import *
from dncore.discord.events import EVENTS, DiscordGenericEvent, HelpCommandPreExecuteEvent, HelpCommandExecuteEvent
from dncore.discord.overrides import replace_overrides
from dncore.util import traceback_simple_format, safe_format
from dncore.util.discord import get_intent_names
from dncore.util.instance import get_core, call_event, run_coroutine

log = getLogger(__name__)
CHANNEL_TYPES = discord.abc.GuildChannel | discord.abc.PrivateChannel | discord.Thread


# noinspection PyMethodMayBeStatic
class DiscordClient(discord.Client):
    def __init__(self, loop: AbstractEventLoop, config: DiscordSection, **options):
        replace_overrides()

        self.loop = loop
        self.config = config

        # intents
        intent = options.get("intents")
        if intent is None:
            intent = discord.Intents.default()
        log.debug("Intents: %s", ",".join(get_intent_names(intent.value)))

        # values
        self._guilds = dict()  # type: dict[int, discord.Guild]
        self._channels = dict()  # type: dict[int, CHANNEL_TYPES]
        self._users = dict()  # type: dict[int, discord.User]
        self.owner = None  # type: discord.User | None

        # instance
        discord.Client.__init__(self, loop=loop, **options)

    @property
    def commands(self):
        return get_core().commands

    @property
    def cached_users(self) -> dict[int, discord.User]:
        users = dict(self._connection._users)
        users.update(self._users)
        return users

    @property
    def cached_guilds(self) -> dict[int, discord.Guild]:
        guilds = dict(self._connection._guilds)
        guilds.update(self._guilds)
        return guilds

    @property
    def cached_channels(self) -> dict[int, CHANNEL_TYPES]:
        channels = dict(self._connection._private_channels)
        for guild in self._connection._guilds.values():
            channels.update(guild._channels)
        channels.update(self._channels)
        return channels

    @property
    def m(self):
        return get_core().config.messages

    @property
    def activities(self):
        return get_core().activity_manager

    async def update_activity(self):
        act = self.activities.current_handler
        await self.activities.change_presence(act)

    async def process_command(self, message: discord.Message):
        if message.author.bot:
            return

        # parse prefix
        prefix = self.config.command_prefix.lower()
        if not prefix:  # disable
            return

        guild_data = get_core().data.get_guild(message.guild, create=False) if message.guild else None
        content = message.content.strip()

        if not content.lower().startswith(prefix):
            if guild_data and guild_data.custom_command_prefix:
                prefix = guild_data.custom_command_prefix.lower()
                if not content.lower().startswith(prefix):
                    return
            else:
                return

        if guild_data:
            if message.channel.id in guild_data.channel_list_ids:
                if guild_data.channel_blacklist_mode:
                    return
            elif not guild_data.channel_blacklist_mode:
                return

        if isinstance(message.channel, discord.PartialMessageable):
            log.warning("No info channel type! (intent 'guilds' not activated?)")
            return

        # parse execute name
        args = content[len(prefix):].split()
        try:
            execute_name = args.pop(0)
        except IndexError:
            e = await call_event(CommandEmptyNameMessageEvent(message, prefix))
            if not e.cancelled:
                reaction = self.m.command_empty_name.reaction
                config = get_core().config.discord.auto_clean  # type: CleanSection
                if config.delete_request and 0 < config.auto_clean_delay_with_unknown_command:
                    self.clean_auto(message, config.auto_clean_delay_with_unknown_command)

                if isinstance(reaction, Embed):
                    reaction = Embed.error(reaction.format(None))
                    delete_after = None
                    if config.delete_response and 0 < config.auto_clean_delay_with_unknown_command:
                        delete_after = config.auto_clean_delay_with_unknown_command
                    run_coroutine(message.channel.send(embed=reaction, delete_after=delete_after), (discord.HTTPException,))
                elif isinstance(reaction, Emoji):
                    run_coroutine(message.add_reaction(reaction), (discord.HTTPException,))
            return

        # get command
        handler = self.commands.get_command(execute_name)

        e = await call_event(CommandPreProcessEvent(message, prefix, handler, execute_name, args))
        if e.cancelled:
            return

        command = e.command
        if command is None:
            e = await call_event(CommandUnknownMessageEvent(message, prefix, execute_name, args))
            if not e.cancelled:
                reaction = self.m.command_unknown_error.reaction
                config = get_core().config.discord.auto_clean  # type: CleanSection
                if config.delete_request and 0 < config.auto_clean_delay_with_unknown_command:
                    self.clean_auto(message, config.auto_clean_delay_with_unknown_command)

                if isinstance(reaction, Embed):
                    reaction = Embed.error(reaction.format(None))
                    delete_after = None
                    if config.delete_response and 0 < config.auto_clean_delay_with_unknown_command:
                        delete_after = config.auto_clean_delay_with_unknown_command
                    run_coroutine(message.channel.send(embed=reaction, delete_after=delete_after), (discord.HTTPException,))
                elif isinstance(reaction, Emoji):
                    run_coroutine(message.add_reaction(reaction), (discord.HTTPException,))
            return

        # noinspection PyTypeChecker
        me = self.user  # type: discord.User
        context = CommandContext(prefix, command, message, execute_name, args, self)
        channel_type = type(message.channel).__name__

        try:
            # check interactive
            if self.commands.is_interactive_running(message.channel.id):
                log.debug("running interactive command in '%s' by '%s'", message.channel, message.author)
                raise CommandInteractiveRunningError()

            # check permission
            if not self.allowed(command, message.author, message.guild):
                log.debug("denied '%s' command permission by '%s'", execute_name, message.author)
                raise CommandPermissionError()

            # check channel type
            if not isinstance(message.channel, command.allow_channels):
                log.debug("not allowed '%s' command in '%s' %s by '%s'",
                          execute_name, message.channel, channel_type, message.author)
                raise CommandNotAllowedChannelTypeError()

            # pre executing
            log.info("[Command] %s: %s", message.author, content.strip().replace("\n", "\\n"))
            if isinstance(message.guild, discord.Guild):
                log.debug("executing from '%s' (%s) in '%s'", message.channel, channel_type, message.guild)
            else:
                log.debug("executing from '%s' (%s)", message.channel, channel_type)

            self.commands.running_commands[message.channel.id].append(context)
            context.task = self.loop.create_task(command.execute(context))
            call_event(CommandProcessEvent(context))

            # executes
            try:
                response = await context.task
            except CancelledError as e:
                if context.cancelled_by_admin:
                    raise CommandCancelError() from e
                raise

        except Exception as ex:
            error = CommandInternalError(ex) if not isinstance(ex, CommandError) else ex
            evt = await call_event(CommandExceptionEvent(context, error, None if isinstance(ex, CommandError) else ex))

            if not evt.cancelled:
                await self._error_command_handling(context, execute_name, error, message, locals())

        else:
            if isinstance(response, discord.Embed):
                if not isinstance(response, Embed):
                    response = Embed.from_dict(response.to_dict())
                response = response.format(None)
                await run_coroutine(context.send_info(response), (discord.NotFound,))

            context.clean_auto(error=False)

        finally:
            context.task = None
            running = self.commands.running_commands[message.channel.id]
            if context in running:
                running.remove(context)
            if not running:
                self.commands.running_commands.pop(message.channel.id, None)

    async def report_errors(self, context: CommandContext, error: CommandError):
        if isinstance(context.channel, discord.TextChannel) and context.channel.id in self.config.debug_channels:
            destination = context.channel
        elif get_core().config.debug.report_error_to_owners and self.owner:
            destination = self.owner
        else:
            return

        if not isinstance(error, CommandInternalError):
            return

        exc = error.exception
        message = context.message
        content = message.content.strip().replace("\n", "\\n")
        if len(content) > 60:
            content = content[:56] + " ..."

        if isinstance(message.guild, discord.Guild):
            link_url = message.jump_url
            location = f"[{message.guild} #{message.channel}]({link_url})"
            report = (f":warning: コマンド実行エラーです\n\n"
                      f"> メッセージ: {str(exc)}\n"
                      f"> 場所: {location}\n"
                      f"> 実行者: {message.author}\n"
                      f"> コマンド: `{content}`")
        else:
            report = (f":warning: コマンド実行エラー ({str(exc)})\n\n"
                      f"> メッセージ: {str(exc)}\n"
                      f"> 場所: @{message.channel} チャンネル\n"
                      f"> コマンド: `{content}`")

        require = "```py\n```"
        split_trace = ""
        trace = list(reversed(traceback_simple_format().replace("```", "\\```").splitlines()))
        line = trace.pop(0)
        while 0 <= 2000 - len(split_trace + require + line + "\n"):
            split_trace = line + "\n" + split_trace
            if trace:
                line = trace.pop(0)
            else:
                break

        try:
            await destination.send(content=f"```py\n{split_trace}```", embed=Embed.error(report))
        except Exception as e:
            log.debug(f"コマンドエラー通知を送信できませんでした: {str(e)}")

    async def find_owner(self, *, force=False):
        if self.config.owner_id:
            if not self.owner or force:
                try:
                    self.owner = await self.fetch_user(self.config.owner_id, force=force)
                except discord.HTTPException:
                    self.owner = None
        else:
            self.owner = None

        return self.owner

    async def _error_command_handling(self, context, execute_name, error, message, __locals):
        if context.self_message:
            run_coroutine(context.self_message.clear_reactions(), (discord.HTTPException,))

        report = False

        if isinstance(error, CommandUsageError):
            log.debug(f"CMD ERROR: {error.command}")
            if isinstance(error.command, str):
                command = self.commands.get_command(error.command)
            else:
                command = error.command or context.command

            usage = self.commands.get_usage(command)
            if usage:
                await self.send_command_usage(context, command, usage)
                reaction = None
            else:
                if (await call_event(HelpCommandPreExecuteEvent(
                        context, context.author, command, execute_name, Argument()))).cancelled:
                    reaction = None
                else:
                    reaction = self.m.command_usage_error.reaction

        elif isinstance(error, CommandPermissionError):
            reaction = self.m.command_permission_error.reaction

        elif isinstance(error, CommandNotAllowedChannelTypeError):
            reaction = self.m.command_disallow_channel_error.reaction

        elif isinstance(error, CommandInteractiveRunningError):
            reaction = self.m.command_interactive_running_error.reaction

        elif isinstance(error, CommandCancelError):
            reaction = self.m.command_cancel_error.reaction

        else:
            report = True
            reaction = self.m.command_internal_error.reaction
            _ex = error.exception if isinstance(error, CommandInternalError) else error
            log.error("Handling Error / %s", execute_name, exc_info=_ex)

        if isinstance(reaction, Embed):
            reaction = Embed.error(reaction.format(__locals))
            try:
                await context.send_error(reaction)
            except discord.HTTPException:
                pass
        elif isinstance(reaction, Emoji):
            run_coroutine(message.add_reaction(reaction), (discord.HTTPException,))

        context.clean_auto(error=True, force=True)

        if report:
            try:
                await self.report_errors(context, error)
            except (Exception,):
                log.debug("Exception in error reports to owner", exc_info=True)

    def _check_guild_admin_permission(self, command: CommandHandler, user: discord.User, guild: discord.Guild | None):
        if not guild:
            return False

        is_admins = guild.owner_id == user.id
        if isinstance(user, discord.Member):
            # noinspection PyUnresolvedReferences
            if user.guild_permissions.administrator:
                is_admins = True

        if is_admins and command.allow_group == DEFAULT_GUILD_ADMIN_GROUP:
            return self.commands.allowed_in_group(command, DEFAULT_GUILD_ADMIN_GROUP)

        return False

    def allowed(self, command: str | CommandHandler, author: discord.User, guild: discord.Guild | None):
        if not isinstance(command, CommandHandler):
            command = self.commands.get_command(command)
        if not command:
            return False

        # check roles and permissions
        roles = list(reversed(author.roles)) if hasattr(author, "roles") else []
        # roles.sort(key=lambda r: r.position, reverse=True)
        role_ids = [r.id for r in roles if r]

        # check permission
        if self.config.owner_id != author.id:
            if not self._check_guild_admin_permission(command, author, guild):
                if not self.commands.allowed(command, user_id=author.id, role_id=role_ids):
                    if not self.commands.allowed_in_group(command, DEFAULT_DEFAULT_GROUP):
                        return False
        return True

    async def send_command_usage(self, context: CommandContext, cmd: str | CommandHandler,
                                 usage: str | None, args: list[str] = None):
        if isinstance(cmd, CommandHandler):
            name = cmd.name
            command = cmd
        else:
            command = self.commands.get_command(cmd, allow_alias=True)
            name = cmd

        args = args if isinstance(args, Argument) else Argument(args if args else [])
        e = await call_event(HelpCommandPreExecuteEvent(context, context.author, command, name, args))

        if e.cancelled:
            return

        m = self.m.help
        command = e.command
        name = e.name
        args = e.args

        if command is None:
            return await context.send_warn(m.unknown_command)

        if not usage:
            usage = self.commands.get_usage(command)
        if not usage:
            return await context.send_warn(m.no_usage)

        aliases = sorted(alias for alias, name in self.commands.aliases.items() if command.name == name)

        if m.enable_usage_format:
            embed = m.usage_format.format(dict(
                name=command.name,
                prefix=context.prefix,
                usage=safe_format(usage, dict(name=command.name, prefix=context.prefix))
            ))
        else:
            embed = command.format_usage(usage_text=usage, command_prefix=context.prefix)

        if aliases:
            embed.add_field(name="別名:", value="`" + "`, `".join(aliases) + "`", inline=False)

        e = await call_event(HelpCommandExecuteEvent(context, context.author, command, name, args, embed))
        if e.cancelled:
            return

        return await context.send_info(e.embed)

    def clean_auto(self, message: discord.Message, delay: float = None, *, is_error=False):
        """
        指定された message をdnCoreの自動削除設定に従い削除します。

        delay を指定すると、dnCoreの設定に関わらず指定時間後に削除します。
        """
        config = get_core().config.discord.auto_clean  # type: CleanSection

        config_auto_clean_delay = config.auto_clean_delay_with_error if is_error else config.auto_clean_delay
        delay = config_auto_clean_delay if delay is None else delay
        delay = max(0, delay)

        return run_coroutine(message.delete(delay=delay), ignores=(discord.HTTPException,))

    # overrides

    async def connect(self, *, reconnect: bool = True) -> None:
        log.debug("connecting to discord...")
        await discord.Client.connect(self, reconnect=reconnect)

    async def close(self) -> None:
        try:
            await self.commands.cancel_all_running()
        except Exception as e:
            log.error(f"Failed to cancel_all_running commands: {e}")

        await discord.Client.close(self)
        if not self.is_closed():
            log.debug("disconnected from discord")

    def dispatch(self, event: str, /, *args, **kwargs) -> None:
        discord.Client.dispatch(self, event, *args, **kwargs)

        e = EVENTS.get(event)
        if e:
            try:
                call_event(e(*args, **kwargs))
            except (Exception,):
                log.exception("Failed to dispatch %s event", event)

        call_event(DiscordGenericEvent(event, *args, **kwargs))

    async def fetch_guild(self, guild_id: int, /, *, with_counts: bool = True, force=False) -> discord.Guild:
        guild = self.get_guild(guild_id)
        if guild is None:
            guild = self._guilds.get(guild_id)

        if force or guild is None:
            guild = await discord.Client.fetch_guild(self, guild_id, with_counts=with_counts)
            self._guilds[guild.id] = guild

        if guild is None:
            raise discord.NotFound(ClientResponse, None)  # type: ignore

        return guild

    async def fetch_channel(self, channel_id: int, /, *, force=False) -> CHANNEL_TYPES:
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = self._channels.get(channel_id)

        if force or channel is None:
            channel = await discord.Client.fetch_channel(self, channel_id)
            self._channels[channel.id] = channel

        if channel is None:
            raise discord.NotFound(ClientResponse, None)  # type: ignore

        return channel

    async def fetch_message(self, channel: int | CHANNEL_TYPES, message_id: int, /, *, force=False) -> discord.Message:
        if not force:
            for m in self.cached_messages:
                if m.id == message_id:
                    return m

        if isinstance(channel, int):
            channel = await self.fetch_channel(channel)

        if channel is None:
            raise discord.NotFound(ClientResponse, None)  # type: ignore

        return await channel.fetch_message(message_id)

    async def fetch_user(self, user_id: int, /, *, force=False) -> discord.User:
        user = self.get_user(user_id)
        if user is None:
            user = self._users.get(user_id)

        if force or user is None:
            user = await discord.Client.fetch_user(self, user_id)
            self._users[user.id] = user

        if user is None:
            raise discord.NotFound(ClientResponse, None)  # type: ignore

        return user

    # events

    async def on_ready(self):
        await self.update_activity()
        await self.find_owner()

    async def on_resumed(self):
        await self.update_activity()
        await self.find_owner()

    async def on_guild_join(self, guild: discord.Guild):
        self._guilds[guild.id] = guild

    async def on_guild_remove(self, guild: discord.Guild):
        self._guilds.pop(guild.id, None)

    async def on_message(self, message: discord.Message):
        if message.author.id not in self._users:
            self._users[message.author.id] = message.author

        if not self.is_ready():
            return
        await self.wait_until_ready()
        try:
            await self.process_command(message)
        except (Exception,):
            log.exception("processing error")
