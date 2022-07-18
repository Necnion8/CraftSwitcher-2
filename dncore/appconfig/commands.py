from dncore.configuration import ConfigValues
from dncore.configuration.files import FileConfigValues


class CommandEntry(ConfigValues):
    handler: str | None
    aliases: list[str]
    usage: str | None

    def serialize(self):
        if not self.aliases and not self.usage:
            return self.handler
        return super().serialize()

    @classmethod
    def deserialize(cls, value):
        if isinstance(value, str):
            value = dict(handler=value)
        return super().deserialize(value)


class CommandCategory(ConfigValues):
    def __init__(self, label: str = None):
        ConfigValues.__init__(self)
        if label is not None:
            self.label = label

    label: str | None
    commands: dict[str, CommandEntry]


class PermissionGroup(ConfigValues):
    commands: list[str]
    users: list[int]

    def serialize(self):
        serialized = super().serialize()
        if "*" in self.commands:
            serialized["commands"] = "*"
        return serialized

    @classmethod
    def deserialize(cls, value):
        if value:
            value = dict(value)
            if value.get("commands") == "*":
                value["commands"] = ["*"]

        return super().deserialize(value)

    def allowed_all(self):
        return "*" in self.commands and len(self.commands) == 1


class CommandsConfig(FileConfigValues):
    # カテゴリ設定とコマンド全般設定
    categories: dict[str, CommandCategory]
    # 権限グループの設定
    groups: dict[str, PermissionGroup]
    # Discord役職と権限グループの振り分け
    roles: dict[str, str]
