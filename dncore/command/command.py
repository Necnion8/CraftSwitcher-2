import asyncio
import inspect
from asyncio import AbstractEventLoop
from collections import defaultdict
from logging import getLogger
from pathlib import Path
from typing import Any, Iterable

from dncore.appconfig import CommandsConfig
from dncore.appconfig.commands import PermissionGroup, CommandCategory, CommandEntry
from dncore.command import DEFAULT_CATEGORY, DEFAULT_DEFAULT_GROUP, DEFAULT_OWNER_GROUP, DEFAULT_GUILD_OWNER_GROUP
from dncore.command.handler import CommandHandler, CommandContext
from dncore.configuration.files import CnfErr
from dncore.util.instance import call_event

__all__ = ["CommandManager", "oncommand"]

from dncore.util.logger import taskmessage

log = getLogger(__name__)


class CommandManager(object):
    def __init__(self, loop: AbstractEventLoop, config_path: Path, *, errors=CnfErr.RAISE):
        self.loop = loop
        self.config = CommandsConfig(path=config_path, errors=errors)
        self._handlers_of_parent = defaultdict(list)  # type: dict[Any, list[CommandHandler]]
        # self._parents_of_handler = {}  # type: dict[CommandHandler, Any]
        self._handlers = {}  # type: dict[str, CommandHandler]  # hid : hdlr
        self._commands = {}  # type: dict[str, str]  # name : hid
        self._aliases = {}  # type: dict[str, str]  # alias : name
        self._custom_usage = {}  # type dict[str, str]  # name : usage
        self._whitelists_of_role = defaultdict(set)  # type: dict[int, set[str] | bool]  # roleId : commands
        self._whitelists_of_user = defaultdict(set)  # type: dict[int, set[str] | bool]  # userId : commands
        self._whitelists_of_group = defaultdict(set)  # type: dict[str, set[str] | bool]  # groupName : commands
        self._changed_flag = False
        self.running_commands = defaultdict(list)  # type: dict[int, list[CommandContext]]  # chId : context

    def register_class(self, parent, clazz, handle_base_id: str = None) -> list[CommandHandler]:
        handlers = self.__find_handlers(clazz)
        if not handlers:
            return []
            # raise ValueError("handler not found!")

        base_id = handle_base_id + "." if handle_base_id else None

        for handler in handlers:
            hid = (base_id + handler.name if base_id else handler.id).lower()
            if hid in self._handlers:
                raise ValueError(f"already registered handler id: {hid}")

        self._handlers_of_parent[parent].extend(handlers)

        for handler in handlers:
            hid = (base_id + handler.name if base_id else handler.id).lower()
            handler.id = hid
            self._handlers[hid] = handler
            self._update_defaults(handler)

        return handlers

    def register(self, parent, handler: CommandHandler, handle_base_id: str = None):
        hid = (f"{handle_base_id}.{handler.name}" if handle_base_id else handler.id).lower()

        if hid in self._handlers:
            raise ValueError(f"already registered handler id: {hid}")

        self._handlers_of_parent[parent].append(handler)
        self._handlers[hid] = handler
        self._update_defaults(handler)

    def _update_defaults(self, handler: CommandHandler):
        if handler.allow_group is None:  # disable defaults
            return

        allow_group = handler.allow_group.lower()
        category_name = handler.category.lower() if handler.category else DEFAULT_CATEGORY
        name = handler.name.lower()
        hid = handler.id.lower()

        # list registered
        names = set()
        handler_ids = set()
        for category in self.config.categories.values():
            for command_name, command in category.commands.items():
                names.add(command_name.lower())
                if command.handler is not None:
                    handler_ids.add(command.handler.lower())

        # check exists
        if name in names:  # already exists command name
            return
        if hid in handler_ids:  # already exists handler id
            return

        # set defaults handler
        try:
            category = self.config.categories[category_name]
        except KeyError:
            category = self.config.categories[category_name] = CommandCategory()

        command = category.commands[name] = CommandEntry()
        command.handler = hid.lower()
        if handler.aliases:
            command.aliases.extend(handler.aliases)

        # set defaults group
        groups = self.config.groups
        try:
            group = groups[allow_group]
        except KeyError:  # ignored
            pass
        else:
            if not group.allowed_all() and name not in group.commands:
                group.commands.append(name)

        self._changed_flag = True

    def unregister_handlers(self, parent):
        try:
            handlers = self._handlers_of_parent.pop(parent)
        except KeyError:
            return []

        [self._handlers.pop(handler.id, None) for handler in handlers]
        return handlers

    def unregister(self, handler: CommandHandler):
        [handlers.remove(handler) for handlers in self._handlers_of_parent.values() if handler in handlers]
        self._handlers.pop(handler.id, None)

    def cleanup(self):
        self._handlers_of_parent.clear()
        self._handlers.clear()
        self._commands.clear()
        self._aliases.clear()
        self._custom_usage.clear()
        self._whitelists_of_role.clear()
        self._whitelists_of_user.clear()
        self._whitelists_of_group.clear()

        for contexts in self.running_commands.values():
            for context in contexts:
                if context.task and not context.task.done():
                    context.task.cancel()

        self.running_commands.clear()

    @classmethod
    def __find_handlers(cls, clazz):
        handlers = []

        for name, method in inspect.getmembers(clazz, inspect.iscoroutinefunction):
            handler = getattr(method, "_handler", None)
            if not isinstance(handler, CommandHandler):
                continue

            handler.execute = method
            sig = inspect.signature(method)
            params = sig.parameters

            if len(params) != 1 or CommandContext is not params[list(params.keys())[0]].annotation:
                log.error("コマンドハンドラ %s.%s が無効な引数を取ります", type(clazz).__name__, name)
                continue

            if handler.name is None:
                log.error("コマンドハンドラ %s.%s のコマンド名が無効です", type(clazz).__name__, name)
                continue

            handlers.append(handler)

        return handlers

    @property
    def handlers(self):
        """
        handler id to CommandHandler dict
        """
        return self._handlers

    @property
    def commands(self):
        """
        name to handler id dict
        """
        return self._commands

    @property
    def aliases(self):
        """
        alias to name dict
        """
        return self._aliases

    @property
    def custom_usages(self):
        """
        name to usage dict
        """
        return self._custom_usage

    def get_handler(self, handler_id: str):
        return self._handlers.get(handler_id)

    def get_command(self, name: str, allow_alias=True):
        name = name.lower()
        try:
            hid = self._commands[name]
        except KeyError:
            if not allow_alias or name not in self._aliases:
                return None
            hid = self._commands.get(self._aliases[name])
        return None if hid is None else self._handlers.get(hid)

    def get_usage(self, command: str | CommandHandler):
        if isinstance(command, CommandHandler):
            try:
                return self._custom_usage[command.name]
            except KeyError:
                return command.usage
        return self._custom_usage.get(command)

    def allowed(self, command: str | CommandHandler, user_id: int | None, role_id: int | list[int] = None):
        if isinstance(command, CommandHandler):
            name = command.name.lower()
        else:
            name = command.lower()

        if user_id and self._find_allowed_in_users(name, user_id):
            return True

        if role_id:
            roles = [role_id] if not isinstance(role_id, list) else reversed(role_id)
            if self._find_allowed_in_roles(name, roles):
                return True

        return False

    def allowed_in_group(self, command: str | CommandHandler, group_name: str):
        name = (command.name if isinstance(command, CommandHandler) else command).lower()
        return name in self._whitelists_of_group[group_name.lower()]

    def get_commands(self, channel_type: type = None, user_id: int = None, role_id: int | list[int] = None):
        # sorted name list
        names = []
        for category in self.config.categories.values():
            names.extend(category.commands.keys())

        roles = [] if role_id is None else ([role_id] if not isinstance(role_id, list) else reversed(role_id))

        return [n for n in names
                # check handler id
                if n in self._commands
                # check handler
                and self._commands[n] in self._handlers
                # check whitelist user or role and or default group
                and (((user_id is None or self._find_allowed_in_users(n, user_id)) and
                      (role_id is None or self._find_allowed_in_roles(n, roles)))
                     or self.allowed_in_group(n, DEFAULT_DEFAULT_GROUP))
                # check channel type
                and (channel_type is None or issubclass(channel_type, self._handlers[self._commands[n]].allow_channels))
                ]

    def get_commands_from_parent(self, parent):
        if parent in self._handlers_of_parent:
            return list(self._handlers_of_parent[parent])
        return []

    def is_interactive_running(self, channel_id: int):
        for context in self.running_commands.get(channel_id, []):
            if context.interactive:
                return True
        return False

    async def cancel_all_running(self):
        fs = []
        for contexts in list(self.running_commands.values()):
            for context in list(contexts):
                if context.task and not context.task.done():
                    context.cancelled_by_admin = True
                    context.task.cancel()
                    fs.append(context.task)

        self.running_commands.clear()
        if fs:
            with taskmessage(log.info, "cancelling %s running commands...", len(fs)):
                try:
                    await asyncio.wait(fs, timeout=10)
                except asyncio.TimeoutError:
                    log.warning("time-outed!")

    def remap(self, force_save=False):
        log.debug("remapping commands")
        self._commands.clear()
        self._aliases.clear()
        self._custom_usage.clear()
        self._whitelists_of_role.clear()
        self._whitelists_of_user.clear()
        self._whitelists_of_group.clear()

        # command handlers & aliases
        for category in self.config.categories.values():
            for command_name, command in category.commands.items():
                command_name = command_name.lower()
                if command_name in self._commands:
                    continue
                self._commands[command_name] = command.handler

                if command.usage:
                    self._custom_usage[command_name] = command.usage

                for alias in command.aliases:
                    alias = alias.lower()
                    if alias not in self._aliases:
                        self._aliases[alias] = command_name

        # default category
        if DEFAULT_CATEGORY not in self.config.categories:
            self.config.categories[DEFAULT_CATEGORY] = CommandCategory()
            self.config.categories[DEFAULT_CATEGORY].label = "その他"
            self._changed_flag = True

        # default groups
        groups = self.config.groups
        try:
            default_group = groups[DEFAULT_DEFAULT_GROUP]
        except KeyError:
            default_group = groups[DEFAULT_DEFAULT_GROUP] = PermissionGroup()
            self._changed_flag = True

        if DEFAULT_OWNER_GROUP not in groups:
            groups[DEFAULT_OWNER_GROUP] = PermissionGroup()
            groups[DEFAULT_OWNER_GROUP].commands.append("*")
            self._changed_flag = True

        if DEFAULT_GUILD_OWNER_GROUP not in groups:
            groups[DEFAULT_GUILD_OWNER_GROUP] = PermissionGroup()
            self._changed_flag = True

        # roles
        for role_id, group_name in self.config.roles.items():
            try:
                role_id = int(role_id)
            except ValueError:
                continue

            try:
                group = groups[group_name]
            except KeyError:
                group = default_group

            if group.allowed_all():
                self._whitelists_of_role[role_id] = True
            else:
                commands = default_group.commands
                commands = group.commands if commands is True else {*group.commands, *commands}

                self._whitelists_of_role[role_id].update(map(str.lower, commands))

        # users
        for group_name, group in groups.items():
            if group.allowed_all():
                self._whitelists_of_group[group_name.lower()] = True
            else:
                self._whitelists_of_group[group_name.lower()].update(map(str.lower, group.commands))

            for user_id in group.users:
                if group.allowed_all():
                    self._whitelists_of_user[user_id] = True
                else:
                    self._whitelists_of_user[user_id].update(map(str.lower, group.commands))

        if self._changed_flag or force_save:
            log.debug("saving changed command mapping")
            self.save_to_config()

        commands = sum([bool(hid in self._commands.values() and handler) for hid, handler in self._handlers.items()])
        aliases = len(self._aliases)
        from dncore.command.events import CommandRemapEvent
        call_event(CommandRemapEvent(command_count=commands, aliases_count=aliases))
        return commands, aliases

    def load_from_config(self):
        self.config.load()
        self._changed_flag = False
        self.remap()

    def save_to_config(self):
        self.config.save()
        self._changed_flag = False

    def _find_allowed_in_users(self, name: str, user: int):
        if user in self._whitelists_of_user:
            allow = self._whitelists_of_user[user]
            return allow is True or name in allow
        return False

    def _find_allowed_in_roles(self, name: str, roles: Iterable[int]):
        for r_id, names in self._whitelists_of_role.items():
            if r_id in roles and (names is True or name in names):
                return True
        return False


oncommand = CommandHandler
